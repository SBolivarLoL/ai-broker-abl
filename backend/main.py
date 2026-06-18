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

import intelligence

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
        side_normalized = req.side.lower()
        if side_normalized not in ("buy", "sell"):
            raise HTTPException(400, f"Invalid side: {req.side!r} (expected 'buy' or 'sell')")
        side = OrderSide.BUY if side_normalized == "buy" else OrderSide.SELL

        order_type_normalized = req.order_type.lower()
        if order_type_normalized not in ("market", "limit"):
            raise HTTPException(400, f"Invalid order_type: {req.order_type!r} (expected 'market' or 'limit')")

        tif = TimeInForce.GTC if req.time_in_force.lower() == "gtc" else TimeInForce.DAY

        if order_type_normalized == "limit":
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


# ── 5. Portfolio intelligence (overview, risk, EDGAR) ─────────────────────────

def _get_account_snapshot() -> dict:
    a = trading_client.get_account()
    return {
        "portfolio_value": float(a.portfolio_value),
        "day_pnl": float(a.equity) - float(a.last_equity),
        "day_pnl_pct": (
            (float(a.equity) - float(a.last_equity)) / float(a.last_equity) * 100
            if float(a.last_equity) > 0 else 0.0
        ),
    }


def _get_positions_enriched() -> tuple[dict, list[dict]]:
    """Account snapshot plus positions with market value, weight, and Alpaca fields."""
    account = _get_account_snapshot()
    portfolio_value = account["portfolio_value"]
    raw_positions = trading_client.get_all_positions()

    enriched: list[dict] = []
    for p in raw_positions:
        market_value = float(p.market_value) if p.market_value else 0.0
        current_price = float(p.current_price) if p.current_price else None
        if current_price is None and market_value and float(p.qty):
            current_price = market_value / float(p.qty)

        weight_pct = (market_value / portfolio_value * 100) if portfolio_value > 0 else 0.0
        enriched.append({
            "symbol": p.symbol,
            "qty": float(p.qty),
            "current_price": current_price,
            "market_value": market_value,
            "weight_pct": round(weight_pct, 4),
            "unrealized_plpc": float(p.unrealized_plpc) * 100 if p.unrealized_plpc else None,
        })

    return account, enriched


@app.get("/api/portfolio/overview")
def portfolio_overview():
    """Objective 5: Alpaca-only portfolio summary with weights and concentration flags."""
    try:
        account, positions = _get_positions_enriched()
        return intelligence.compute_overview(account, positions)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/portfolio/risk")
def portfolio_risk():
    """Objective 5: 30-day risk metrics from Alpaca bars."""
    try:
        _, positions = _get_positions_enriched()
        symbols = [p["symbol"] for p in positions]
        all_symbols = list({*symbols, "SPY"})
        bars_by_symbol = intelligence.fetch_bars(all_symbols, days=30, data_client=data_client)
        spy_bars = bars_by_symbol.get("SPY", [])
        return intelligence.compute_risk_metrics(positions, bars_by_symbol, spy_bars)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/intelligence/{symbol}")
def symbol_intelligence(symbol: str):
    """Objective 5: EDGAR fundamentals and filing activity for a single symbol."""
    sym = symbol.upper()
    try:
        quotes = data_client.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=sym)
        )
        q = quotes.get(sym)
        if not q or (not q.bid_price and not q.ask_price):
            raise HTTPException(404, f"Unknown symbol: {sym}")

        price: float | None = None
        if q.bid_price and q.ask_price:
            price = (float(q.bid_price) + float(q.ask_price)) / 2
        elif q.ask_price:
            price = float(q.ask_price)
        elif q.bid_price:
            price = float(q.bid_price)

        if intelligence.is_non_company_instrument(sym):
            return {
                "symbol": sym,
                "price": price,
                "edgar": None,
                "note": "Non-company instrument — no EDGAR filings (e.g. ETF)",
            }

        cik = intelligence.resolve_cik(sym)
        if not cik:
            raise HTTPException(404, f"No EDGAR CIK for symbol: {sym}")

        try:
            facts = intelligence.get_company_facts(sym)
            filings = intelligence.get_recent_filings(sym)
        except ValueError:
            return {
                "symbol": sym,
                "cik": cik,
                "price": price,
                "edgar": None,
                "note": "No EDGAR company facts available for this instrument",
            }
        except Exception:
            return {
                "symbol": sym,
                "cik": cik,
                "price": price,
                "edgar": None,
                "note": "EDGAR data temporarily unavailable",
            }

        fundamentals = intelligence.compute_fundamental_ratios(facts, price)
        flags = intelligence.build_intelligence_flags(filings)

        return {
            "symbol": sym,
            "cik": cik,
            "price": price,
            "fundamentals": fundamentals,
            "filings": filings,
            "flags": flags,
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(404, f"Unknown symbol: {sym}")
    except Exception as e:
        raise HTTPException(500, str(e))
