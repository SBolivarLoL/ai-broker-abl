"""
AI features — objective 4 (advisory). All four features below NEVER place orders.

Builds on the existing Alpaca backend (main.py). This file adds an APIRouter that
main.py loads with `app.include_router(router)`.

Endpoints:
  GET  /api/ai/commentary        -> 1. natural-language commentary on your holdings
  GET  /api/ai/news/{symbol}     -> 2. plain-language news/earnings summary for a ticker
  POST /api/ai/parse-order       -> 3. natural language -> structured order intent (prefills the order ticket; does NOT execute)
  GET  /api/ai/why-moved/{symbol}-> 4. AI explanation of a recent price move

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

# News client is optional — wrapped so a missing/renamed import never breaks the app.
try:
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest
    _news = NewsClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"))
except Exception:
    _news = None
    NewsRequest = None


# ── Helpers ───────────────────────────────────────────────────────────────────
def _text_of(content) -> str:
    return "\n".join(b.text for b in content if b.type == "text").strip()


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


def _get_news(symbol: str, limit: int = 10) -> list[dict]:
    if not _news or not NewsRequest:
        return []
    res = _news.get_news(NewsRequest(symbols=symbol.upper(), limit=limit))
    items = getattr(res, "news", None)
    if items is None and hasattr(res, "data") and isinstance(res.data, dict):
        items = res.data.get("news", [])
    out = []
    for it in (items or []):
        created = getattr(it, "created_at", None)
        out.append({
            "headline": getattr(it, "headline", ""),
            "summary": getattr(it, "summary", ""),
            "source": getattr(it, "source", ""),
            "url": getattr(it, "url", ""),
            "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created),
        })
    return out


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


# ── 2. News / earnings summary per ticker ─────────────────────────────────────
@router.get("/api/ai/news/{symbol}")
def ai_news(symbol: str):
    try:
        news = _get_news(symbol)
        if news:
            joined = "\n".join(f"- {n['headline']} ({n['source']}): {n['summary'][:300]}" for n in news)
            user = f"Recent news for {symbol.upper()}:\n{joined}\n\nSummarize it."
        else:
            user = f"There is no recent news available for {symbol.upper()}. Say so briefly."
        resp = _claude.messages.create(
            model=P.MODEL, max_tokens=500, system=P.NEWS_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        return {"symbol": symbol.upper(), "summary": _text_of(resp.content), "article_count": len(news)}
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

        # Build a ticket that matches your teammate's POST /api/orders shape.
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
            # cash amount -> approximate qty using the current price (NOTE: Alpaca is USD).
            notional = intent["amount"]
            price = _mid_price(symbol)
            if price:
                ticket["qty"] = round(notional / price, 4)

        return {
            "order_ticket": ticket,        # prefill the order form with this
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


# ── 4. "Why did this stock move?" ─────────────────────────────────────────────
@router.get("/api/ai/why-moved/{symbol}")
def ai_why_moved(symbol: str):
    try:
        move = _recent_move(symbol)
        news = _get_news(symbol, limit=8)
        headlines = "\n".join(f"- {n['headline']}" for n in news) or "(no recent headlines available)"
        if move["change_pct"] is None:
            move_txt = "Recent price move: unknown (not enough data)."
        else:
            move_txt = (f"{symbol.upper()} moved {move['change_pct']:+.2f}% "
                        f"(from ${move['prev_close']:.2f} to ${move['last_close']:.2f}).")
        resp = _claude.messages.create(
            model=P.MODEL, max_tokens=500, system=P.WHY_MOVED_SYSTEM,
            messages=[{"role": "user", "content": f"{move_txt}\n\nRecent headlines:\n{headlines}\n\nWhy did it likely move?"}],
        )
        return {"symbol": symbol.upper(), "move": move, "explanation": _text_of(resp.content)}
    except Exception as e:
        raise HTTPException(500, str(e))
