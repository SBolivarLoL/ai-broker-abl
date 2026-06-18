"""
AI features — objective 4 (advisory). All four features below NEVER place orders.

Builds on the existing Alpaca backend (main.py). This file adds an APIRouter that
main.py loads with `app.include_router(router)`.

Endpoints:
  GET  /api/ai/commentary        -> 1. natural-language commentary on your holdings
  GET  /api/ai/news/{symbol}     -> 2. summary of the LATEST news (live web search)
  POST /api/ai/parse-order       -> 3. natural language -> structured order intent (prefills the order ticket; does NOT execute)
  GET  /api/ai/why-moved/{symbol}-> 4. AI explanation of a recent price move (live web search)

News & "why moved" use Claude's web_search tool so they reflect the most recent
information instead of stale training data or stale cached news.

Needs secret: ANTHROPIC_API_KEY (plus the existing ALPACA_* keys).
"""
import os
from datetime import datetime, timedelta
from typing import Optional

import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

import ai_prompts as P

router = APIRouter()

# Own client instances (same keys as main.py) — keeps this module decoupled.
_trading = TradingClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True)
_data = StockHistoricalDataClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"))
_claude = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

# Claude's live web-search tool — gives us fresh news instead of stale data.
_WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search"}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _text_of(content) -> str:
    return "\n".join(b.text for b in content if getattr(b, "type", None) == "text").strip()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _ask_with_search(system: str, user: str, max_tokens: int = 800) -> str:
    """Call Claude with the live web-search tool; let it run its searches to completion."""
    messages = [{"role": "user", "content": user}]
    resp = None
    for _ in range(4):  # web_search may pause_turn; resume until done
        resp = _claude.messages.create(
            model=P.MODEL, max_tokens=max_tokens, system=system,
            tools=[_WEB_SEARCH], messages=messages,
        )
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue
        break
    return _text_of(resp.content)


def _build_portfolio() -> dict:
    a = _trading.get_account()
    positions = [
        {
            "symbol": p.symbol,
            "qty": float(p.qty),
            "avg_entry": float(p.avg_entry_price),
            "current_price": float(p.current_price) if p.current_price else None,
            "unrealized_plpc": float(p.unrealized_plpc) * 100 if p.unrealized_plpc else None,
        }
        for p in _trading.get_all_positions()
    ]
    return {
        "cash": float(a.cash),
        "equity": float(a.equity),
        "buying_power": float(a.buying_power),
        "positions": positions,
    }


def _mid_price(symbol: str) -> Optional[float]:
    q = _data.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=[symbol.upper()]))
    item = q[symbol.upper()]
    bid = float(item.bid_price) if item.bid_price else None
    ask = float(item.ask_price) if item.ask_price else None
    if bid and ask:
        return (bid + ask) / 2
    return ask or bid


def _recent_move(symbol: str) -> dict:
    """Last daily close vs the prior close, as a % move."""
    end = datetime.now()
    start = end - timedelta(days=7)
    bars = _data.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=symbol.upper(), timeframe=TimeFrame.Day,
        start=start, end=end, feed=DataFeed.IEX,
    ))
    series = bars.data.get(symbol.upper(), []) if hasattr(bars, "data") else bars[symbol.upper()]
    if len(series) < 2:
        return {"last_close": None, "prev_close": None, "change_pct": None}
    last_close = float(series[-1].close)
    prev_close = float(series[-2].close)
    return {
        "last_close": last_close,
        "prev_close": prev_close,
        "change_pct": (last_close - prev_close) / prev_close * 100 if prev_close else None,
    }


# ── 1. Portfolio commentary (natural language) ────────────────────────────────
@router.get("/api/ai/commentary")
def ai_commentary():
    try:
        portfolio = _build_portfolio()
        resp = _claude.messages.create(
            model=P.MODEL, max_tokens=600, system=P.COMMENTARY_SYSTEM,
            messages=[{"role": "user", "content": f"Here are my holdings:\n{P.portfolio_summary(portfolio)}\n\nGive me your commentary."}],
        )
        return {"commentary": _text_of(resp.content)}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── 2. News / earnings summary per ticker (LIVE web search) ───────────────────
@router.get("/api/ai/news/{symbol}")
def ai_news(symbol: str):
    try:
        sym = symbol.upper()
        user = (
            f"Today is {_today()}. Use web search to find the most recent news about the stock {sym} "
            f"(the company behind that ticker) from the last few days, and summarize it."
        )
        return {"symbol": sym, "summary": _ask_with_search(P.NEWS_SYSTEM, user, max_tokens=900)}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── 3. Natural-language -> order intent parser (stops before executing) ───────
class ParseRequest(BaseModel):
    text: str

@router.post("/api/ai/parse-order")
def ai_parse_order(req: ParseRequest):
    """
    Turns "buy 100 euros of Apple" into a structured order intent that prefills the
    order ticket (objective 3). It does NOT execute anything — your teammate's
    POST /api/orders endpoint does the actual placing after the user confirms.
    """
    try:
        resp = _claude.messages.create(
            model=P.MODEL, max_tokens=600, system=P.PARSE_SYSTEM,
            tool_choice={"type": "tool", "name": "order_intent"},
            tools=[{
                "name": "order_intent",
                "description": "The structured trading intent parsed from the user's text.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "ticker symbol, e.g. AAPL"},
                        "side": {"type": "string", "enum": ["buy", "sell"]},
                        "amount_type": {"type": "string", "enum": ["cash", "shares"]},
                        "amount": {"type": "number"},
                        "order_type": {"type": "string", "enum": ["market", "limit"]},
                        "limit_price": {"type": ["number", "null"]},
                        "currency": {"type": "string", "description": "e.g. USD, EUR (if the user mentioned one)"},
                        "needs_clarification": {"type": "boolean"},
                        "clarification": {"type": "string"},
                    },
                    "required": ["symbol", "side", "amount_type", "amount", "order_type", "needs_clarification"],
                },
            }],
            messages=[{"role": "user", "content": req.text}],
        )
        intent = next((b.input for b in resp.content if b.type == "tool_use"), None)
        if not intent:
            raise HTTPException(500, "could not parse the request")

        symbol = intent["symbol"].upper()
        ticket = {
            "symbol": symbol,
            "side": intent["side"],
            "order_type": intent.get("order_type", "market"),
            "limit_price": intent.get("limit_price"),
            "time_in_force": "day",
            "qty": None,
        }
        notional = None
        if intent["amount_type"] == "shares":
            ticket["qty"] = intent["amount"]
        else:
            notional = intent["amount"]
            price = _mid_price(symbol)
            if price:
                ticket["qty"] = round(notional / price, 4)

        return {
            "order_ticket": ticket,
            "notional": notional,
            "currency": intent.get("currency", "USD"),
            "needs_clarification": intent.get("needs_clarification", False),
            "clarification": intent.get("clarification", ""),
            "interpretation": f"{intent['side'].upper()} "
                              f"{(str(intent['amount']) + ' shares') if intent['amount_type'] == 'shares' else ('$' + str(intent['amount']))} "
                              f"of {symbol} ({ticket['order_type']})",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── 4. "Why did this stock move?" (LIVE web search) ───────────────────────────
@router.get("/api/ai/why-moved/{symbol}")
def ai_why_moved(symbol: str):
    try:
        sym = symbol.upper()
        move = _recent_move(sym)
        if move["change_pct"] is None:
            move_txt = "I could not determine the exact recent price move."
        else:
            move_txt = (f"{sym} moved {move['change_pct']:+.2f}% recently "
                        f"(from ${move['prev_close']:.2f} to ${move['last_close']:.2f}).")
        user = (
            f"Today is {_today()}. {move_txt}\n\n"
            f"Use web search to find the latest news from the last few days that explains this move, "
            f"then explain why {sym} likely moved."
        )
        return {"symbol": sym, "move": move, "explanation": _ask_with_search(P.WHY_MOVED_SYSTEM, user, max_tokens=900)}
    except Exception as e:
        raise HTTPException(500, str(e))
