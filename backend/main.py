import os
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

trading_client = TradingClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY"),
    paper=True,
)
data_client = StockHistoricalDataClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY"),
)

app = FastAPI(title="AI Broker – Paper Trading")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Objectives 4, 5, 6 (AI co-pilot, portfolio intelligence, agentic agent) — zie ai.py
from ai import router as ai_router  # noqa: E402
app.include_router(ai_router)


# ── 1. Connected broker account ───────────────────────────────────────────────

@app.get("/api/account")
def get_account():
    """Objective 1: live paper account info."""
    try:
        a = trading_client.get_account()
        return {
            "id": str(a.id),
            "status": str(a.status),
            "currency": a.currency,
            "cash": float(a.cash),
            "buying_power": float(a.buying_power),
            "portfolio_value": float(a.portfolio_value),
            "equity": float(a.equity),
            "last_equity": float(a.last_equity),
            "day_pnl": float(a.equity) - float(a.last_equity),
            "day_pnl_pct": (
                (float(a.equity) - float(a.last_equity)) / float(a.last_equity) * 100
                if float(a.last_equity) > 0 else 0.0
            ),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/positions")
def get_positions():
    """Current open positions."""
    try:
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry": float(p.avg_entry_price),
                "current_price": float(p.current_price) if p.current_price else None,
                "market_value": float(p.market_value) if p.market_value else None,
                "unrealized_pl": float(p.unrealized_pl) if p.unrealized_pl else None,
                "unrealized_plpc": float(p.unrealized_plpc) * 100 if p.unrealized_plpc else None,
                "side": str(p.side),
            }
            for p in trading_client.get_all_positions()
        ]
    except Exception as e:
        raise HTTPException(500, str(e))


# ── 2. Market view – live / recent prices ─────────────────────────────────────

class SymbolsRequest(BaseModel):
    symbols: list[str]

@app.post("/api/prices")
def get_latest_prices(req: SymbolsRequest):
    """Objective 2: latest bid/ask for one or many symbols."""
    try:
        symbols = [s.upper() for s in req.symbols]
        quotes = data_client.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=symbols)
        )
        return {
            sym: {
                "bid": float(q.bid_price) if q.bid_price else None,
                "ask": float(q.ask_price) if q.ask_price else None,
                "mid": (float(q.ask_price) + float(q.bid_price)) / 2
                       if q.ask_price and q.bid_price else None,
                "timestamp": q.timestamp.isoformat() if q.timestamp else None,
            }
            for sym, q in quotes.items()
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/prices/{symbol}/bars")
def get_bars(symbol: str, days: int = 5):
    """OHLCV daily bars for a symbol (useful for charting)."""
    try:
        end = datetime.now()
        start = end - timedelta(days=days)
        bars = data_client.get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=symbol.upper(),
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
                feed=DataFeed.IEX,
            )
        )
        return [
            {"t": b.timestamp.isoformat(), "o": float(b.open), "h": float(b.high),
             "l": float(b.low), "c": float(b.close), "v": int(b.volume)}
            for b in bars[symbol.upper()]
        ]
    except Exception as e:
        raise HTTPException(500, str(e))


# ── 3. Order ticket – buy / sell paper orders ─────────────────────────────────

class OrderRequest(BaseModel):
    symbol: str
    qty: float
    side: str          # "buy" | "sell"
    order_type: str = "market"    # "market" | "limit"
    limit_price: Optional[float] = None
    time_in_force: str = "day"    # "day" | "gtc"

@app.post("/api/orders")
def place_order(req: OrderRequest):
    """Objective 3: place a paper buy or sell order."""
    try:
        side = OrderSide.BUY if req.side.lower() == "buy" else OrderSide.SELL
        tif = TimeInForce.GTC if req.time_in_force.lower() == "gtc" else TimeInForce.DAY

        if req.order_type == "limit":
            if not req.limit_price:
                raise HTTPException(400, "limit_price required for limit orders")
            order_data = LimitOrderRequest(
                symbol=req.symbol.upper(),
                qty=req.qty,
                side=side,
                time_in_force=tif,
                limit_price=req.limit_price,
            )
        else:
            order_data = MarketOrderRequest(
                symbol=req.symbol.upper(),
                qty=req.qty,
                side=side,
                time_in_force=tif,
            )

        o = trading_client.submit_order(order_data)
        return {
            "id": str(o.id),
            "symbol": o.symbol,
            "qty": float(o.qty) if o.qty else None,
            "side": str(o.side),
            "type": str(o.order_type),
            "status": str(o.status),
            "limit_price": float(o.limit_price) if o.limit_price else None,
            "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/orders")
def list_orders(status: str = "open"):
    """List open or filled orders."""
    try:
        status_map = {
            "open": QueryOrderStatus.OPEN,
            "closed": QueryOrderStatus.CLOSED,
            "all": QueryOrderStatus.ALL,
        }
        orders = trading_client.get_orders(
            GetOrdersRequest(status=status_map.get(status, QueryOrderStatus.OPEN))
        )
        return [
            {
                "id": str(o.id),
                "symbol": o.symbol,
                "qty": float(o.qty) if o.qty else None,
                "filled_qty": float(o.filled_qty) if o.filled_qty else 0,
                "side": str(o.side),
                "type": str(o.order_type),
                "status": str(o.status),
                "limit_price": float(o.limit_price) if o.limit_price else None,
                "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
                "filled_at": o.filled_at.isoformat() if o.filled_at else None,
            }
            for o in orders
        ]
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete("/api/orders/{order_id}")
def cancel_order(order_id: str):
    """Cancel a specific open order."""
    try:
        trading_client.cancel_order_by_id(order_id)
        return {"cancelled": order_id}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/orders")
def cancel_all_orders():
    """Cancel all open orders."""
    try:
        trading_client.cancel_orders()
        return {"cancelled": "all"}
    except Exception as e:
        raise HTTPException(400, str(e))
