"""
Integration tests for objectives 1, 2, and 3.
Runs against the real Alpaca paper trading API — no mocks.
"""
import time
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

# ── Objective 1: Connected broker account ─────────────────────────────────────

class TestAccount:
    def test_account_is_reachable(self):
        r = client.get("/api/account")
        assert r.status_code == 200

    def test_account_is_active(self):
        r = client.get("/api/account")
        data = r.json()
        assert data["status"] == "AccountStatus.ACTIVE"

    def test_account_has_required_fields(self):
        r = client.get("/api/account")
        data = r.json()
        for field in ("id", "currency", "cash", "buying_power", "portfolio_value", "equity", "day_pnl"):
            assert field in data, f"Missing field: {field}"

    def test_account_has_positive_portfolio_value(self):
        r = client.get("/api/account")
        assert r.json()["portfolio_value"] > 0

    def test_account_currency_is_usd(self):
        r = client.get("/api/account")
        assert r.json()["currency"] == "USD"

    def test_positions_endpoint_returns_list(self):
        r = client.get("/api/positions")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ── Objective 2: Market view – live prices ────────────────────────────────────

class TestMarketView:
    def test_single_symbol_price(self):
        r = client.post("/api/prices", json={"symbols": ["AAPL"]})
        assert r.status_code == 200
        assert "AAPL" in r.json()

    def test_multiple_symbol_prices(self):
        r = client.post("/api/prices", json={"symbols": ["AAPL", "SPY", "MSFT"]})
        assert r.status_code == 200
        data = r.json()
        for sym in ("AAPL", "SPY", "MSFT"):
            assert sym in data

    def test_price_has_bid_ask_mid(self):
        r = client.post("/api/prices", json={"symbols": ["SPY"]})
        spy = r.json()["SPY"]
        for field in ("bid", "ask", "mid", "timestamp"):
            assert field in spy, f"Missing field: {field}"

    def test_price_values_are_positive(self):
        r = client.post("/api/prices", json={"symbols": ["SPY"]})
        spy = r.json()["SPY"]
        assert spy["bid"] > 0
        assert spy["ask"] > 0
        assert spy["mid"] > 0

    def test_ask_gte_bid(self):
        r = client.post("/api/prices", json={"symbols": ["AAPL"]})
        aapl = r.json()["AAPL"]
        assert aapl["ask"] >= aapl["bid"]

    def test_bars_returns_ohlcv(self):
        r = client.get("/api/prices/SPY/bars?days=5")
        assert r.status_code == 200
        bars = r.json()
        assert len(bars) > 0
        for bar in bars:
            for field in ("t", "o", "h", "l", "c", "v"):
                assert field in bar

    def test_bars_high_gte_low(self):
        r = client.get("/api/prices/SPY/bars?days=5")
        for bar in r.json():
            assert bar["h"] >= bar["l"]

    def test_invalid_symbol_returns_error(self):
        r = client.post("/api/prices", json={"symbols": ["FAKESYM123XYZ"]})
        assert r.status_code in (400, 500)


# ── Objective 3: Order ticket – buy / sell ────────────────────────────────────

class TestOrderTicket:
    placed_order_id: str = None

    def test_place_market_buy(self):
        r = client.post("/api/orders", json={
            "symbol": "SPY",
            "qty": 1,
            "side": "buy",
            "order_type": "market",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["symbol"] == "SPY"
        assert "buy" in data["side"].lower()
        assert data["id"]
        TestOrderTicket.placed_order_id = data["id"]

    def test_list_orders_includes_placed_order(self):
        r = client.get("/api/orders?status=all")
        assert r.status_code == 200
        ids = [o["id"] for o in r.json()]
        assert TestOrderTicket.placed_order_id in ids

    def test_cancel_specific_order(self):
        # Place a limit order far from market so it stays open to cancel
        r = client.post("/api/orders", json={
            "symbol": "AAPL",
            "qty": 1,
            "side": "buy",
            "order_type": "limit",
            "limit_price": 1.00,
        })
        assert r.status_code == 200
        order_id = r.json()["id"]

        cancel = client.delete(f"/api/orders/{order_id}")
        assert cancel.status_code == 200
        assert cancel.json()["cancelled"] == order_id

    def test_place_market_sell_without_position_returns_error(self):
        # Selling a symbol we definitely don't hold should fail
        r = client.post("/api/orders", json={
            "symbol": "BRK.B",
            "qty": 999999,
            "side": "sell",
            "order_type": "market",
        })
        assert r.status_code in (400, 422)

    def test_limit_order_requires_limit_price(self):
        r = client.post("/api/orders", json={
            "symbol": "AAPL",
            "qty": 1,
            "side": "buy",
            "order_type": "limit",
        })
        assert r.status_code == 400

    def test_cancel_all_orders(self):
        r = client.delete("/api/orders")
        assert r.status_code == 200
        assert r.json()["cancelled"] == "all"

    def test_open_orders_empty_after_cancel_all(self):
        client.delete("/api/orders")
        time.sleep(1)  # paper API needs a moment to process cancellations
        r = client.get("/api/orders?status=open")
        assert r.status_code == 200
        # all remaining orders should be cancelled/pending_cancel, not actionable
        actionable = {"new", "accepted", "partially_filled", "pending_new"}
        open_orders = [o for o in r.json() if any(s in o["status"].lower() for s in actionable)]
        assert open_orders == []

    def test_order_response_has_required_fields(self):
        r = client.post("/api/orders", json={
            "symbol": "SPY",
            "qty": 1,
            "side": "buy",
            "order_type": "market",
        })
        data = r.json()
        for field in ("id", "symbol", "qty", "side", "type", "status", "submitted_at"):
            assert field in data
        client.delete("/api/orders")
