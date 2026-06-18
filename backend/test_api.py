"""
Integration tests for objectives 1, 2, and 3.
Runs against the real Alpaca paper trading API — no mocks.
"""
import time
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def _cancel_orders_after_session():
    """Keep the paper account demoable: cancel any orders these tests leave open."""
    yield
    try:
        client.delete("/api/orders")
    except Exception:
        pass


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

    def test_account_buying_power_non_negative(self):
        assert client.get("/api/account").json()["buying_power"] >= 0

    def test_account_cash_non_negative(self):
        assert client.get("/api/account").json()["cash"] >= 0

    def test_account_id_is_non_empty(self):
        assert client.get("/api/account").json()["id"]

    def test_day_pnl_is_internally_consistent(self):
        d = client.get("/api/account").json()
        assert d["day_pnl"] == pytest.approx(d["equity"] - d["last_equity"], abs=1e-6)

    def test_day_pnl_pct_is_internally_consistent(self):
        d = client.get("/api/account").json()
        if d["last_equity"] > 0:
            expected = (d["equity"] - d["last_equity"]) / d["last_equity"] * 100
            assert d["day_pnl_pct"] == pytest.approx(expected, abs=1e-6)
        else:
            assert d["day_pnl_pct"] == 0.0

    def test_positions_have_expected_shape(self):
        positions = client.get("/api/positions").json()
        if not positions:
            pytest.skip("no open positions")
        for p in positions:
            for field in ("symbol", "qty", "avg_entry", "side"):
                assert field in p, f"Missing field: {field}"
            assert isinstance(p["symbol"], str) and p["symbol"]


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

    def test_symbol_is_normalized_to_uppercase(self):
        r = client.post("/api/prices", json={"symbols": ["aapl"]})
        assert r.status_code == 200
        assert "AAPL" in r.json()

    def test_mid_is_between_bid_and_ask(self):
        spy = client.post("/api/prices", json={"symbols": ["SPY"]}).json()["SPY"]
        assert spy["bid"] <= spy["mid"] <= spy["ask"]

    def test_price_timestamp_is_iso8601(self):
        from datetime import datetime
        spy = client.post("/api/prices", json={"symbols": ["SPY"]}).json()["SPY"]
        datetime.fromisoformat(spy["timestamp"])  # raises ValueError if malformed

    def test_missing_symbols_field_returns_422(self):
        r = client.post("/api/prices", json={})
        assert r.status_code == 422

    def test_mixed_valid_and_invalid_symbol_errors(self):
        r = client.post("/api/prices", json={"symbols": ["SPY", "FAKESYM123XYZ"]})
        assert r.status_code in (400, 500)

    def test_bars_ohlc_within_high_low(self):
        for bar in client.get("/api/prices/SPY/bars?days=5").json():
            assert bar["l"] <= bar["o"] <= bar["h"]
            assert bar["l"] <= bar["c"] <= bar["h"]

    def test_bars_volume_non_negative(self):
        for bar in client.get("/api/prices/SPY/bars?days=5").json():
            assert bar["v"] >= 0

    def test_bars_are_chronological(self):
        timestamps = [b["t"] for b in client.get("/api/prices/SPY/bars?days=10").json()]
        assert timestamps == sorted(timestamps)

    def test_bars_symbol_is_case_insensitive(self):
        r = client.get("/api/prices/spy/bars?days=5")
        assert r.status_code == 200
        assert len(r.json()) > 0


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

    def test_valid_limit_order_echoes_type_and_price(self):
        # Limit far below market so it rests open instead of filling.
        r = client.post("/api/orders", json={
            "symbol": "AAPL", "qty": 1, "side": "buy",
            "order_type": "limit", "limit_price": 1.00,
        })
        assert r.status_code == 200
        data = r.json()
        assert "limit" in data["type"].lower()
        assert data["limit_price"] == 1.00
        client.delete(f"/api/orders/{data['id']}")

    def test_order_symbol_is_normalized_to_uppercase(self):
        r = client.post("/api/orders", json={
            "symbol": "aapl", "qty": 1, "side": "buy",
            "order_type": "limit", "limit_price": 1.00,
        })
        assert r.status_code == 200
        assert r.json()["symbol"] == "AAPL"
        client.delete(f"/api/orders/{r.json()['id']}")

    def test_order_side_is_case_insensitive(self):
        r = client.post("/api/orders", json={
            "symbol": "AAPL", "qty": 1, "side": "BUY",
            "order_type": "limit", "limit_price": 1.00,
        })
        assert r.status_code == 200
        assert "buy" in r.json()["side"].lower()
        client.delete(f"/api/orders/{r.json()['id']}")

    def test_invalid_side_is_rejected(self):
        # Regression: an invalid side must NOT silently become a SELL order.
        r = client.post("/api/orders", json={
            "symbol": "SPY", "qty": 1, "side": "hodl", "order_type": "market",
        })
        assert r.status_code == 400
        client.delete("/api/orders")  # defensive: nothing should have been placed

    def test_invalid_order_type_is_rejected(self):
        # Regression: a typo'd order_type must NOT silently become a market order.
        r = client.post("/api/orders", json={
            "symbol": "SPY", "qty": 1, "side": "buy",
            "order_type": "stop", "limit_price": 1.00,
        })
        assert r.status_code == 400
        client.delete("/api/orders")

    def test_zero_qty_rejected(self):
        r = client.post("/api/orders", json={
            "symbol": "SPY", "qty": 0, "side": "buy", "order_type": "market",
        })
        assert r.status_code in (400, 422)

    def test_negative_qty_rejected(self):
        r = client.post("/api/orders", json={
            "symbol": "SPY", "qty": -5, "side": "buy", "order_type": "market",
        })
        assert r.status_code in (400, 422)

    def test_cancel_nonexistent_order_returns_error(self):
        r = client.delete("/api/orders/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 400

    def test_gtc_limit_order_accepted(self):
        r = client.post("/api/orders", json={
            "symbol": "AAPL", "qty": 1, "side": "buy",
            "order_type": "limit", "limit_price": 1.00, "time_in_force": "gtc",
        })
        assert r.status_code == 200
        client.delete(f"/api/orders/{r.json()['id']}")

    def test_list_orders_status_filters_return_lists(self):
        for status in ("open", "closed", "all"):
            r = client.get(f"/api/orders?status={status}")
            assert r.status_code == 200
            assert isinstance(r.json(), list)


# ── Objective 5: Portfolio intelligence ───────────────────────────────────────

class TestPortfolioIntelligence:
    def test_overview_returns_required_fields(self):
        r = client.get("/api/portfolio/overview")
        assert r.status_code == 200
        data = r.json()
        for field in (
            "account", "positions", "largest_position",
            "concentration_warning", "position_count",
        ):
            assert field in data, f"Missing field: {field}"
        assert "portfolio_value" in data["account"]
        assert isinstance(data["positions"], list)

    def test_overview_weights_are_valid_when_positions_exist(self):
        r = client.get("/api/portfolio/overview")
        assert r.status_code == 200
        positions = r.json()["positions"]
        if not positions:
            pytest.skip("no open positions")
        total_weight = sum(p["weight_pct"] for p in positions)
        # Weights are against total portfolio value, so cash keeps invested weight below 100%.
        assert 0 < total_weight <= 100.5

    def test_risk_returns_required_fields(self):
        r = client.get("/api/portfolio/risk")
        assert r.status_code == 200
        data = r.json()
        for field in (
            "beta_vs_spy", "sharpe_30d", "max_drawdown_pct", "var_95_daily",
            "positions", "as_of", "warnings", "excluded_symbols",
        ):
            assert field in data, f"Missing field: {field}"

    def test_risk_var_is_negative_or_null(self):
        r = client.get("/api/portfolio/risk")
        assert r.status_code == 200
        var = r.json()["var_95_daily"]
        if var is not None:
            assert var <= 0

    def test_intelligence_aapl_returns_fundamentals(self):
        r = client.get("/api/intelligence/AAPL")
        assert r.status_code == 200
        data = r.json()
        assert data.get("symbol") == "AAPL"
        assert "fundamentals" in data
        assert "filings" in data
        assert data["filings"]["form4_count_90d"] >= 0

    def test_intelligence_spy_returns_edgar_null(self):
        r = client.get("/api/intelligence/SPY")
        assert r.status_code == 200
        data = r.json()
        assert data.get("edgar") is None
        assert "note" in data
        assert data.get("price") is not None

    def test_compute_risk_metrics_negative_var_and_exclusions(self):
        positions = [
            {"symbol": "AAA", "market_value": 6000.0},
            {"symbol": "BBB", "market_value": 4000.0},
        ]
        bars_by_symbol = {
            "AAA": [
                {"t": "2025-05-01", "c": 100.0},
                {"t": "2025-05-02", "c": 101.0},
                {"t": "2025-05-03", "c": 102.0},
            ],
            "BBB": [{"t": "2025-05-03", "c": 50.0}],
        }
        spy_bars = [
            {"t": "2025-05-01", "c": 400.0},
            {"t": "2025-05-02", "c": 401.0},
            {"t": "2025-05-03", "c": 402.0},
        ]
        from intelligence import compute_risk_metrics

        result = compute_risk_metrics(positions, bars_by_symbol, spy_bars)
        assert result["var_95_daily"] is not None
        assert result["var_95_daily"] <= 0
        assert "BBB" in result["excluded_symbols"]

    def test_compute_overview_flags_overweight(self):
        from intelligence import compute_overview

        account = {"portfolio_value": 10000.0, "day_pnl": 50.0, "day_pnl_pct": 0.5}
        positions = [
            {"symbol": "BIG", "qty": 10, "market_value": 3000.0, "unrealized_plpc": 5.0},
            {"symbol": "SMALL", "qty": 5, "market_value": 7000.0, "unrealized_plpc": -1.0},
        ]
        result = compute_overview(account, positions)
        big = next(p for p in result["positions"] if p["symbol"] == "BIG")
        assert "OVERWEIGHT" in big["flags"]
        assert result["concentration_warning"] is True
