"""Objective 5: EDGAR fundamentals, portfolio overview, and risk metrics."""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone

import httpx

SEC_USER_AGENT = "AI-Broker-Paper-Trading/1.0 (hackathon portfolio-intelligence demo)"
SEC_TIMEOUT = httpx.Timeout(5.0, connect=3.0)

TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# Module-level in-memory caches (session lifetime)
_ticker_cik_map: dict[str, str] | None = None
_companyfacts_cache: dict[str, dict] = {}
_submissions_cache: dict[str, dict] = {}

REVENUE_TAGS = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax")
NET_INCOME_TAG = "NetIncomeLoss"
EPS_TAG = "EarningsPerShareDiluted"
ASSETS_TAG = "Assets"
LIABILITIES_TAG = "Liabilities"
SHARES_TAG = "CommonStockSharesOutstanding"

INSIDER_ACTIVITY_THRESHOLD = 5
OVERWEIGHT_THRESHOLD_PCT = 20.0
MIN_BARS_FOR_RISK = 3
TRADING_DAYS_PER_YEAR = 252
VAR_Z_95 = 1.645
NON_COMPANY_INSTRUMENTS = {
    "SPY", "QQQ", "DIA", "IWM", "VTI", "VOO", "IVV", "TLT", "GLD", "SLV",
}


def _sec_headers() -> dict[str, str]:
    return {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}


def load_ticker_cik_map() -> dict[str, str]:
    """Fetch and cache SEC ticker → zero-padded CIK mapping."""
    global _ticker_cik_map
    if _ticker_cik_map is not None:
        return _ticker_cik_map

    with httpx.Client(timeout=SEC_TIMEOUT, headers=_sec_headers()) as client:
        resp = client.get(TICKER_CIK_URL)
        resp.raise_for_status()
        raw = resp.json()

    mapping: dict[str, str] = {}
    for entry in raw.values():
        ticker = str(entry.get("ticker", "")).upper()
        cik = str(entry.get("cik_str", "")).zfill(10)
        if ticker and cik:
            mapping[ticker] = cik

    _ticker_cik_map = mapping
    return mapping


def resolve_cik(symbol: str) -> str | None:
    """Return zero-padded CIK for a ticker, or None if not in SEC registry."""
    return load_ticker_cik_map().get(symbol.upper())


def is_non_company_instrument(symbol: str) -> bool:
    """Known demo-relevant ETFs and funds should not be treated as operating companies."""
    return symbol.upper() in NON_COMPANY_INSTRUMENTS


def _fetch_companyfacts(cik: str) -> dict:
    if cik in _companyfacts_cache:
        return _companyfacts_cache[cik]

    url = COMPANYFACTS_URL.format(cik=cik)
    with httpx.Client(timeout=SEC_TIMEOUT, headers=_sec_headers()) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()

    _companyfacts_cache[cik] = data
    return data


def _fetch_submissions(cik: str) -> dict:
    if cik in _submissions_cache:
        return _submissions_cache[cik]

    url = SUBMISSIONS_URL.format(cik=cik)
    with httpx.Client(timeout=SEC_TIMEOUT, headers=_sec_headers()) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()

    _submissions_cache[cik] = data
    return data


def _iter_fact_entries(facts: dict, tag: str) -> list[dict]:
    gaap = facts.get("facts", {}).get("us-gaap", {})
    tag_data = gaap.get(tag)
    if not tag_data:
        return []

    entries: list[dict] = []
    for unit_entries in tag_data.get("units", {}).values():
        entries.extend(unit_entries)
    return entries


def _latest_fact(entries: list[dict], *, form: str | None = None) -> dict | None:
    filtered = [e for e in entries if form is None or e.get("form") == form]
    if not filtered:
        filtered = entries
    if not filtered:
        return None

    filtered.sort(key=lambda e: (e.get("end", ""), e.get("filed", "")), reverse=True)
    return filtered[0]


def _fact_value(entries: list[dict], *, form: str | None = None) -> tuple[float | None, str | None]:
    latest = _latest_fact(entries, form=form)
    if not latest:
        return None, None
    val = latest.get("val")
    if val is None:
        return None, latest.get("end")
    return float(val), latest.get("end")


def _first_available_fact(facts: dict, tags: tuple[str, ...], *, form: str | None = None) -> tuple[float | None, str | None]:
    for tag in tags:
        entries = _iter_fact_entries(facts, tag)
        value, end = _fact_value(entries, form=form)
        if value is not None:
            return value, end
    return None, None


def get_company_facts(symbol: str) -> dict:
    """Fetch raw SEC company facts for a ticker."""
    cik = resolve_cik(symbol)
    if not cik:
        raise ValueError(f"No SEC CIK for symbol {symbol.upper()}")
    try:
        return _fetch_companyfacts(cik)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise ValueError(f"No EDGAR company facts for symbol {symbol.upper()}") from exc
        raise


def get_recent_filings(symbol: str) -> dict:
    """Extract recent 10-K/10-Q dates and Form 4 count in last 90 days."""
    cik = resolve_cik(symbol)
    if not cik:
        raise ValueError(f"No SEC CIK for symbol {symbol.upper()}")

    submissions = _fetch_submissions(cik)
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])

    last_10k: str | None = None
    last_10q: str | None = None
    form4_count_90d = 0

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=90)

    for form, filing_date in zip(forms, dates):
        if form == "10-K" and last_10k is None:
            last_10k = filing_date
        elif form == "10-Q" and last_10q is None:
            last_10q = filing_date

        if form == "4":
            try:
                filed = datetime.strptime(filing_date, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            if filed >= cutoff:
                form4_count_90d += 1

    return {
        "last_10k": last_10k,
        "last_10q": last_10q,
        "form4_count_90d": form4_count_90d,
    }


def compute_fundamental_ratios(facts: dict, price: float | None) -> dict:
    """Derive fundamentals and ratios from SEC company facts and optional market price."""
    annual_revenue, revenue_end = _first_available_fact(facts, REVENUE_TAGS, form="10-K")
    annual_net_income, _ = _fact_value(_iter_fact_entries(facts, NET_INCOME_TAG), form="10-K")
    annual_eps, eps_end = _fact_value(_iter_fact_entries(facts, EPS_TAG), form="10-K")

    if annual_revenue is None:
        annual_revenue, revenue_end = _first_available_fact(facts, REVENUE_TAGS)
    if annual_net_income is None:
        annual_net_income, _ = _fact_value(_iter_fact_entries(facts, NET_INCOME_TAG))
    if annual_eps is None:
        annual_eps, eps_end = _fact_value(_iter_fact_entries(facts, EPS_TAG))

    total_assets, _ = _fact_value(_iter_fact_entries(facts, ASSETS_TAG))
    total_liabilities, _ = _fact_value(_iter_fact_entries(facts, LIABILITIES_TAG))
    shares_outstanding, _ = _fact_value(_iter_fact_entries(facts, SHARES_TAG))

    profit_margin: float | None = None
    if annual_revenue and annual_revenue != 0 and annual_net_income is not None:
        profit_margin = annual_net_income / annual_revenue

    debt_to_equity: float | None = None
    if total_assets is not None and total_liabilities is not None:
        equity = total_assets - total_liabilities
        if equity > 0:
            debt_to_equity = total_liabilities / equity

    pe_ratio: float | None = None
    if price is not None and annual_eps is not None and annual_eps > 0:
        pe_ratio = price / annual_eps

    return {
        "revenue": annual_revenue,
        "revenue_as_of": revenue_end,
        "net_income": annual_net_income,
        "eps_diluted": annual_eps,
        "eps_as_of": eps_end,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "shares_outstanding": shares_outstanding,
        "profit_margin": profit_margin,
        "debt_to_equity": debt_to_equity,
        "pe_ratio": pe_ratio,
    }


def build_intelligence_flags(filings: dict) -> list[str]:
    flags: list[str] = []
    if filings.get("form4_count_90d", 0) >= INSIDER_ACTIVITY_THRESHOLD:
        flags.append("INSIDER_ACTIVITY")
    return flags


def fetch_bars(symbols: list[str], days: int, data_client) -> dict[str, list[dict]]:
    """Thin wrapper around Alpaca daily bars (IEX feed)."""
    from alpaca.data.enums import DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    if not symbols:
        return {}

    end = datetime.now()
    start = end - timedelta(days=days)
    bars_response = data_client.get_stock_bars(
        StockBarsRequest(
            symbol_or_symbols=[s.upper() for s in symbols],
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed=DataFeed.IEX,
        )
    )

    result: dict[str, list[dict]] = {}
    for sym in symbols:
        upper = sym.upper()
        bar_list = bars_response.data.get(upper, []) if hasattr(bars_response, "data") else bars_response[upper]
        result[upper] = [
            {
                "t": b.timestamp.date().isoformat(),
                "c": float(b.close),
            }
            for b in bar_list
        ]
    return result


def _daily_returns(closes_by_date: dict[str, float]) -> dict[str, float]:
    dates = sorted(closes_by_date.keys())
    returns: dict[str, float] = {}
    for i in range(1, len(dates)):
        prev, curr = dates[i - 1], dates[i]
        prev_close = closes_by_date[prev]
        if prev_close <= 0:
            continue
        returns[curr] = (closes_by_date[curr] - prev_close) / prev_close
    return returns


def _std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return statistics.stdev(values)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return statistics.mean(values)


def compute_risk_metrics(
    positions: list[dict],
    bars_by_symbol: dict[str, list[dict]],
    spy_bars: list[dict],
) -> dict:
    """Pure risk computation from position weights and bar closes."""
    warnings: list[str] = []
    excluded_symbols: list[str] = []

    if not positions:
        return {
            "beta_vs_spy": 0.0,
            "sharpe_30d": 0.0,
            "max_drawdown_pct": 0.0,
            "var_95_daily": 0.0,
            "positions": [],
            "as_of": {"start": None, "end": None},
            "warnings": ["no positions"],
            "excluded_symbols": [],
            "note": "no positions",
        }

    total_value = sum(float(p.get("market_value") or 0) for p in positions)
    if total_value <= 0:
        warnings.append("portfolio market value is zero")

    position_metrics: list[dict] = []
    symbol_returns: dict[str, dict[str, float]] = {}

    all_dates: set[str] = set()
    for bar in spy_bars:
        all_dates.add(bar["t"])

    for pos in positions:
        symbol = pos["symbol"].upper()
        bars = bars_by_symbol.get(symbol, [])
        closes = {b["t"]: b["c"] for b in bars}
        all_dates.update(closes.keys())

        if len(closes) < MIN_BARS_FOR_RISK:
            excluded_symbols.append(symbol)
            warnings.append(f"insufficient bars for {symbol}")
            weight_pct = (float(pos.get("market_value") or 0) / total_value * 100) if total_value > 0 else 0.0
            position_metrics.append({
                "symbol": symbol,
                "return_30d_pct": None,
                "daily_volatility": None,
                "weight_pct": round(weight_pct, 4),
            })
            continue

        sorted_dates = sorted(closes.keys())
        first_close = closes[sorted_dates[0]]
        last_close = closes[sorted_dates[-1]]
        return_30d_pct = ((last_close - first_close) / first_close * 100) if first_close > 0 else None

        daily_rets = list(_daily_returns(closes).values())
        daily_vol = _std(daily_rets)
        symbol_returns[symbol] = _daily_returns(closes)

        weight_pct = (float(pos.get("market_value") or 0) / total_value * 100) if total_value > 0 else 0.0
        position_metrics.append({
            "symbol": symbol,
            "return_30d_pct": round(return_30d_pct, 4) if return_30d_pct is not None else None,
            "daily_volatility": round(daily_vol, 6) if daily_vol is not None else None,
            "weight_pct": round(weight_pct, 4),
        })

    included = [p for p in positions if p["symbol"].upper() not in excluded_symbols]
    if not included:
        date_range = _date_range_from_bars(bars_by_symbol, spy_bars)
        return {
            "beta_vs_spy": None,
            "sharpe_30d": None,
            "max_drawdown_pct": None,
            "var_95_daily": None,
            "positions": position_metrics,
            "as_of": date_range,
            "warnings": warnings,
            "excluded_symbols": excluded_symbols,
        }

    spy_closes = {b["t"]: b["c"] for b in spy_bars}
    spy_returns = _daily_returns(spy_closes)

    if len(spy_returns) < MIN_BARS_FOR_RISK:
        warnings.append("insufficient SPY bars for beta")

    included_total_value = sum(float(p.get("market_value") or 0) for p in included)
    weights = {}
    for pos in included:
        sym = pos["symbol"].upper()
        mv = float(pos.get("market_value") or 0)
        weights[sym] = (mv / included_total_value) if included_total_value > 0 else 0.0

    common_dates = sorted(
        d for d in all_dates
        if d in spy_returns
        and all(d in symbol_returns.get(p["symbol"].upper(), {}) for p in included)
    )

    portfolio_returns: list[float] = []
    aligned_spy_returns: list[float] = []
    for d in common_dates:
        day_ret = 0.0
        for pos in included:
            sym = pos["symbol"].upper()
            day_ret += weights.get(sym, 0.0) * symbol_returns[sym][d]
        portfolio_returns.append(day_ret)
        aligned_spy_returns.append(spy_returns[d])

    date_range = {
        "start": common_dates[0] if common_dates else None,
        "end": common_dates[-1] if common_dates else None,
    }

    port_vol = _std(portfolio_returns)
    port_mean = _mean(portfolio_returns)

    sharpe_30d: float | None = None
    if port_vol and port_vol > 0 and port_mean is not None:
        sharpe_30d = (port_mean / port_vol) * math.sqrt(TRADING_DAYS_PER_YEAR)

    var_95_daily: float | None = None
    if port_vol is not None:
        var_95_daily = round(-VAR_Z_95 * port_vol * 100, 4)

    beta_vs_spy: float | None = None
    if len(aligned_spy_returns) >= MIN_BARS_FOR_RISK and len(portfolio_returns) >= MIN_BARS_FOR_RISK:
        spy_mean = _mean(aligned_spy_returns)
        port_mean_aligned = _mean(portfolio_returns)
        if spy_mean is not None and port_mean_aligned is not None:
            spy_var = statistics.variance(aligned_spy_returns)
            if spy_var > 0:
                cov = sum(
                    (p - port_mean_aligned) * (s - spy_mean)
                    for p, s in zip(portfolio_returns, aligned_spy_returns)
                ) / (len(portfolio_returns) - 1)
                beta_vs_spy = round(cov / spy_var, 4)
    elif len(spy_returns) < MIN_BARS_FOR_RISK:
        beta_vs_spy = None

    max_drawdown_pct = _max_drawdown_pct(portfolio_returns)

    return {
        "beta_vs_spy": beta_vs_spy,
        "sharpe_30d": round(sharpe_30d, 4) if sharpe_30d is not None else None,
        "max_drawdown_pct": max_drawdown_pct,
        "var_95_daily": var_95_daily,
        "positions": position_metrics,
        "as_of": date_range,
        "warnings": warnings,
        "excluded_symbols": excluded_symbols,
    }


def _date_range_from_bars(
    bars_by_symbol: dict[str, list[dict]],
    spy_bars: list[dict],
) -> dict[str, str | None]:
    dates: set[str] = set()
    for bars in bars_by_symbol.values():
        for b in bars:
            dates.add(b["t"])
    for b in spy_bars:
        dates.add(b["t"])
    if not dates:
        return {"start": None, "end": None}
    sorted_dates = sorted(dates)
    return {"start": sorted_dates[0], "end": sorted_dates[-1]}


def _max_drawdown_pct(daily_returns: list[float]) -> float | None:
    if not daily_returns:
        return None

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in daily_returns:
        equity *= 1.0 + r
        peak = max(peak, equity)
        if peak > 0:
            dd = (equity - peak) / peak
            max_dd = min(max_dd, dd)

    return round(max_dd * 100, 4)


def compute_overview(account: dict, positions: list[dict]) -> dict:
    """Pure overview computation from account snapshot and enriched positions."""
    portfolio_value = float(account.get("portfolio_value") or 0)

    enriched: list[dict] = []
    largest_position: dict | None = None
    max_weight = -1.0

    for pos in positions:
        mv = float(pos.get("market_value") or 0)
        weight_pct = (mv / portfolio_value * 100) if portfolio_value > 0 else 0.0
        flags: list[str] = []
        if weight_pct > OVERWEIGHT_THRESHOLD_PCT:
            flags.append("OVERWEIGHT")

        entry = {
            "symbol": pos["symbol"],
            "qty": pos.get("qty"),
            "market_value": mv,
            "weight_pct": round(weight_pct, 4),
            "unrealized_plpc": pos.get("unrealized_plpc"),
            "flags": flags,
        }
        enriched.append(entry)

        if weight_pct > max_weight:
            max_weight = weight_pct
            largest_position = {
                "symbol": pos["symbol"],
                "weight_pct": round(weight_pct, 4),
            }

    concentration_warning = any(
        float(p.get("weight_pct") or 0) > OVERWEIGHT_THRESHOLD_PCT for p in enriched
    )

    return {
        "account": {
            "portfolio_value": portfolio_value,
            "day_pnl": account.get("day_pnl"),
            "day_pnl_pct": account.get("day_pnl_pct"),
        },
        "positions": enriched,
        "largest_position": largest_position,
        "concentration_warning": concentration_warning,
        "position_count": len(enriched),
    }
