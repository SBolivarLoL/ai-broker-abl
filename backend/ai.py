"""
AI features — objectives 4, 5, 6.

Builds on top of the existing Alpaca backend (main.py). This file adds an
APIRouter that main.py loads with `app.include_router(router)`.

Endpoints:
  GET  /api/portfolio/metrics   -> objective 5: risk metrics / overview
  POST /api/ai/chat             -> objective 4: AI co-pilot (advisory)
  POST /api/ai/ideas            -> objective 4: structured trade ideas
  GET  /api/ai/review           -> objective 4/5: portfolio analysis in plain language
  POST /api/ai/agent            -> objective 6: agentic agent (propose -> approve -> execute)

Needs secret: ANTHROPIC_API_KEY (plus the existing ALPACA_* keys).
"""
import os
from typing import Optional

import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

import ai_prompts as P

router = APIRouter()

# Own client instances (same keys as main.py) — keeps this module decoupled.
_trading = TradingClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True)
_data = StockHistoricalDataClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"))
_claude = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


# ── Helpers ───────────────────────────────────────────────────────────────────
def _build_portfolio() -> dict:
    """Snapshot of the account in a shape the prompts/metrics understand."""
    a = _trading.get_account()
    positions = [
        {
            "symbol": p.symbol,
            "qty": float(p.qty),
            "avg_entry": float(p.avg_entry_price),
            "current_price": float(p.current_price) if p.current_price else None,
            "market_value": float(p.market_value) if p.market_value else None,
            "unrealized_pl": float(p.unrealized_pl) if p.unrealized_pl else None,
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


def _text_of(content) -> str:
    return "\n".join(b.text for b in content if b.type == "text").strip()


def _get_quote(symbol: str) -> dict:
    q = _data.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=[symbol.upper()]))
    item = q[symbol.upper()]
    bid = float(item.bid_price) if item.bid_price else None
    ask = float(item.ask_price) if item.ask_price else None
    mid = (bid + ask) / 2 if bid and ask else None
    return {"symbol": symbol.upper(), "bid": bid, "ask": ask, "mid": mid}


def _place_order(o: dict) -> dict:
    """Place a market order via Alpaca (qty OR notional)."""
    side = OrderSide.BUY if o["side"].lower() == "buy" else OrderSide.SELL
    kwargs = {"symbol": o["ticker"].upper(), "side": side, "time_in_force": TimeInForce.DAY}
    if o.get("qty"):
        kwargs["qty"] = o["qty"]
    elif o.get("notional"):
        kwargs["notional"] = o["notional"]
    else:
        raise HTTPException(400, "order needs 'qty' or 'notional'")
    res = _trading.submit_order(MarketOrderRequest(**kwargs))
    return {
        "id": str(res.id),
        "ticker": res.symbol,
        "side": str(res.side),
        "qty": float(res.qty) if res.qty else 0.0,
        "status": str(res.status),
        "submitted_at": res.submitted_at.isoformat() if res.submitted_at else None,
    }


# ── Objective 5: Risk metrics / overview (pure calculation) ───────────────────
@router.get("/api/portfolio/metrics")
def portfolio_metrics():
    try:
        p = _build_portfolio()
        positions = p["positions"]
        positions_value = sum((pos["market_value"] or 0) for pos in positions)
        total_value = positions_value + p["cash"]

        if positions:
            largest = max(positions, key=lambda x: (x["market_value"] or 0))
        else:
            largest = {"symbol": "—", "market_value": 0}

        weights = [(pos["market_value"] or 0) / total_value if total_value else 0 for pos in positions]
        herfindahl = sum(w * w for w in weights)

        day_pl = sum((pos["unrealized_pl"] or 0) for pos in positions)
        cost_basis = sum(pos["avg_entry"] * pos["qty"] for pos in positions)

        return {
            "total_value": total_value,
            "cash_pct": (p["cash"] / total_value * 100) if total_value else 0,
            "positions_count": len(positions),
            "largest_position_pct": ((largest["market_value"] or 0) / total_value * 100) if total_value else 0,
            "top_holding": largest["symbol"],
            "diversification_score": round(max(0, min(100, (1 - herfindahl) * 100))),
            "day_pl": day_pl,
            "day_pl_pct": (day_pl / cost_basis * 100) if cost_basis else 0,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Objective 4: AI Co-pilot ──────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]

@router.post("/api/ai/chat")
def ai_chat(req: ChatRequest):
    """Free-form Q&A about the portfolio (advisory)."""
    try:
        portfolio = _build_portfolio()
        # Want the AI to search the web live (current news/prices)? Add:
        #   tools=[{"type": "web_search_20260209", "name": "web_search"}]
        # and handle stop_reason == "pause_turn". For the demo we rely on
        # Alpaca data + the model's own knowledge.
        resp = _claude.messages.create(
            model=P.MODEL,
            max_tokens=1500,
            system=f"{P.COPILOT_SYSTEM}\n\nCurrent portfolio:\n{P.portfolio_summary(portfolio)}",
            messages=[{"role": m.role, "content": m.content} for m in req.messages],
        )
        return {"reply": _text_of(resp.content)}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/ai/ideas")
def ai_ideas():
    """Structured trade ideas via a tool."""
    try:
        portfolio = _build_portfolio()
        resp = _claude.messages.create(
            model=P.MODEL,
            max_tokens=1500,
            system=P.IDEAS_SYSTEM,
            tool_choice={"type": "any"},
            tools=[{
                "name": "propose_orders",
                "description": "Propose a trade idea (buy or sell).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "side": {"type": "string", "enum": ["buy", "sell"]},
                        "qty": {"type": "number", "description": "number of shares (or notional)"},
                        "notional": {"type": "number", "description": "dollar amount (or qty)"},
                        "rationale": {"type": "string", "description": "short justification"},
                    },
                    "required": ["ticker", "side", "rationale"],
                },
            }],
            messages=[{"role": "user", "content": f"My portfolio:\n{P.portfolio_summary(portfolio)}\n\nGive trade ideas."}],
        )
        ideas = [b.input for b in resp.content if b.type == "tool_use" and b.name == "propose_orders"]
        return {"ideas": ideas}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/ai/review")
def ai_review():
    """Portfolio analysis in plain language (objective 5 narrative)."""
    try:
        portfolio = _build_portfolio()
        resp = _claude.messages.create(
            model=P.MODEL,
            max_tokens=600,
            system=P.REVIEW_SYSTEM,
            messages=[{"role": "user", "content": f"Analyze my portfolio:\n{P.portfolio_summary(portfolio)}"}],
        )
        return {"review": _text_of(resp.content)}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Objective 6: Agentic trading agent ────────────────────────────────────────
class OrderIntent(BaseModel):
    ticker: str
    side: str
    qty: Optional[float] = None
    notional: Optional[float] = None
    rationale: str = ""

class AgentRequest(BaseModel):
    instruction: str = ""
    approve: bool = False
    approved_orders: list[OrderIntent] = []

_QUOTE_TOOL = {
    "name": "get_quote",
    "description": "Fetch the current price of a ticker.",
    "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]},
}
_ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "side": {"type": "string", "enum": ["buy", "sell"]},
        "qty": {"type": "number"},
        "notional": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["ticker", "side", "rationale"],
}
_PROPOSE_TOOL = {"name": "propose_order", "description": "Propose an order (do NOT execute).", "input_schema": _ORDER_SCHEMA}
_PLACE_TOOL = {"name": "place_order", "description": "Place an order via Alpaca (actually execute).", "input_schema": _ORDER_SCHEMA}

@router.post("/api/ai/agent")
def ai_agent(req: AgentRequest):
    """
    Agentic loop:
      approve=False -> the agent analyzes (get_quote) and PROPOSES orders (propose_order).
      approve=True  -> the agent EXECUTES the approved orders (place_order) via Alpaca.
    """
    try:
        portfolio = _build_portfolio()
        tools = [_QUOTE_TOOL, _PLACE_TOOL if req.approve else _PROPOSE_TOOL]
        proposed, executed = [], []

        if req.approve:
            user_content = (
                f"My portfolio:\n{P.portfolio_summary(portfolio)}\n\n"
                f"Approved orders to execute:\n"
                + "\n".join(str(o.model_dump()) for o in req.approved_orders)
            )
        else:
            user_content = f"My portfolio:\n{P.portfolio_summary(portfolio)}\n\nInstruction: {req.instruction}"

        messages = [{"role": "user", "content": user_content}]

        for _ in range(6):  # max 6 rounds
            resp = _claude.messages.create(
                model=P.MODEL,
                max_tokens=1500,
                system=P.agent_system(req.approve),
                tools=tools,
                messages=messages,
            )

            if resp.stop_reason != "tool_use":
                return {"message": _text_of(resp.content), "proposed_orders": proposed, "executed_orders": executed}

            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                if block.name == "get_quote":
                    result = _get_quote(block.input["ticker"])
                elif block.name == "propose_order":
                    proposed.append(block.input)
                    result = {"ok": "proposal recorded (not executed)"}
                elif block.name == "place_order":
                    placed = _place_order(block.input)
                    executed.append(placed)
                    result = placed
                else:
                    result = {"error": "unknown tool"}
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(result)})
            messages.append({"role": "user", "content": tool_results})

        return {"message": "Agent reached the maximum number of steps.", "proposed_orders": proposed, "executed_orders": executed}
    except Exception as e:
        raise HTTPException(500, str(e))
