import os
import json
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf
import anthropic
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

anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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


# ── 4. Sustainability screener ────────────────────────────────────────────────

# Curated default universe – liquid large-caps with known ESG coverage
DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "JPM", "V",
    "UNH", "XOM", "JNJ", "PG", "MA", "HD", "CVX", "MRK", "ABBV", "PEP",
    "KO", "AVGO", "COST", "TMO", "MCD", "ACN", "NKE", "CSCO", "ABT", "DHR",
    "LIN", "NEE", "ADBE", "TXN", "CRM", "WMT", "BMY", "QCOM", "PM", "HON",
    "AMGN", "ORCL", "UNP", "LOW", "MS", "GS", "CAT", "BA", "RTX", "INTC",
]


class SustainabilityRequest(BaseModel):
    symbols: Optional[list[str]] = None  # None → use DEFAULT_UNIVERSE
    top_n: int = 10


def _fetch_esg(symbol: str) -> Optional[dict]:
    """Return ESG scores for a symbol via yfinance, or None if unavailable."""
    try:
        ticker = yf.Ticker(symbol)
        sus = ticker.sustainability
        if sus is None or sus.empty:
            return None
        col = sus.columns[0]
        row = sus[col]

        def _val(key):
            v = row.get(key)
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return str(v)

        return {
            "total_esg": _val("totalEsg"),
            "environment_score": _val("environmentScore"),
            "social_score": _val("socialScore"),
            "governance_score": _val("governanceScore"),
            "esg_performance": str(row.get("esgPerformance", "")),
            "controversy_level": _val("highestControversy"),
            "peer_group": str(row.get("peerGroup", "")),
        }
    except Exception:
        return None


def _fetch_price_perf(symbols: list[str], days: int = 30) -> dict:
    """Return {symbol: pct_return_30d} from Alpaca bars."""
    end = datetime.now()
    start = end - timedelta(days=days + 10)  # buffer for weekends/holidays
    result: dict = {s: None for s in symbols}
    try:
        bars = data_client.get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
                feed=DataFeed.IEX,
            )
        )
        for sym in symbols:
            sym_bars = bars.get(sym)
            if sym_bars and len(sym_bars) >= 2:
                first_close = float(sym_bars[0].close)
                last_close = float(sym_bars[-1].close)
                if first_close > 0:
                    result[sym] = round((last_close - first_close) / first_close * 100, 2)
    except Exception:
        pass
    return result


@app.get("/api/sustainability/universe")
def get_universe():
    """Return the default stock universe used by the screener."""
    return {"symbols": DEFAULT_UNIVERSE, "count": len(DEFAULT_UNIVERSE)}


@app.post("/api/sustainability/screen")
def screen_sustainability(req: SustainabilityRequest):
    """
    AI-powered sustainability screener.
    1. Fetches ESG scores from Yahoo Finance for each symbol.
    2. Fetches 30-day price performance from Alpaca.
    3. Asks Claude to rank and recommend the best sustainability+performance stocks.
    """
    symbols = [s.upper() for s in (req.symbols or DEFAULT_UNIVERSE)]
    top_n = max(1, min(req.top_n, len(symbols)))

    # ── Step 1: ESG data ──────────────────────────────────────────────────────
    esg_data: dict = {}
    for sym in symbols:
        esg = _fetch_esg(sym)
        if esg and esg.get("total_esg") is not None:
            esg_data[sym] = esg

    if not esg_data:
        raise HTTPException(404, "No ESG data found for any of the requested symbols.")

    # ── Step 2: Price performance ─────────────────────────────────────────────
    syms_with_esg = list(esg_data.keys())
    price_perf = _fetch_price_perf(syms_with_esg)

    # ── Step 3: Combine into a payload for Claude ─────────────────────────────
    combined = []
    for sym in syms_with_esg:
        combined.append({
            "symbol": sym,
            **esg_data[sym],
            "price_return_30d_pct": price_perf.get(sym),
        })

    prompt = f"""You are a quantitative ESG analyst. Below is ESG and price-performance data for {len(combined)} stocks.

Data (JSON):
{json.dumps(combined, indent=2)}

Your task:
1. Rank the stocks by a combined sustainability + price-performance score.
   - Prioritise lower totalEsg score (Yahoo Finance uses lower = better, i.e. less controversy/risk).
   - Reward higher environment, social, and governance sub-scores where available.
   - Penalise stocks with high controversy_level (higher number = worse).
   - Give moderate weight to positive 30-day price momentum (price_return_30d_pct).
2. Select the top {top_n} stocks.
3. For each selected stock provide: symbol, your composite_score (0-100, higher = better), brief_rationale (1-2 sentences).
4. Also provide a one-paragraph overall_summary of the results.

Respond ONLY with valid JSON in this exact schema:
{{
  "top_picks": [
    {{"symbol": "...", "composite_score": 0, "brief_rationale": "..."}}
  ],
  "overall_summary": "..."
}}"""

    try:
        msg = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        agent_result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"Claude returned non-JSON response: {e}")
    except Exception as e:
        raise HTTPException(500, f"Claude API error: {e}")

    # ── Step 4: Enrich response with raw ESG data ─────────────────────────────
    raw_lookup = {item["symbol"]: item for item in combined}
    for pick in agent_result.get("top_picks", []):
        sym = pick.get("symbol")
        if sym and sym in raw_lookup:
            pick["esg_data"] = raw_lookup[sym]

    return {
        "screened_count": len(combined),
        "top_n": top_n,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        **agent_result,
    }
