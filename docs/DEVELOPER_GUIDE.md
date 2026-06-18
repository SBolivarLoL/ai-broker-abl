# Developer Guide

This project is a small FastAPI backend for the AI Broker Hackathon. The backend is the source of truth today; `frontend/` exists but has no implementation yet.

## Repository Layout

```text
repo/
  backend/
    main.py              FastAPI app, Alpaca clients, and route handlers
    intelligence.py      SEC EDGAR access, caches, portfolio risk, overview logic
    requirements.txt     Python dependencies
    test_api.py          Integration and pure-function tests
  docs/
    USER_GUIDE.md
    DEVELOPER_GUIDE.md
  frontend/              Placeholder, currently empty
  .env.example           Required environment variable names
  run.sh                 Starts uvicorn on port 8000
```

## Runtime Dependencies

The backend uses:

- `fastapi` and `uvicorn` for the HTTP API.
- `alpaca-py` for paper trading, account data, quotes, and bars.
- `python-dotenv` for local `.env` loading.
- `httpx` for SEC EDGAR requests.
- `pytest` and `fastapi.testclient` for tests.

The `anthropic` package is installed but not used by the current backend routes.

## Local Setup

From the repository root:

```bash
cp .env.example .env
```

Fill in Alpaca credentials:

```bash
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
```

Install dependencies:

```bash
cd backend
python3 -m pip install -r requirements.txt
```

Return to the repository root and start the server:

```bash
cd ..
./run.sh
```

`run.sh` changes into `backend/` and runs:

```bash
uvicorn main:app --reload --port 8000
```

## Application Structure

`backend/main.py` owns the API boundary. It loads `.env`, creates the Alpaca trading and data clients, configures CORS, validates request bodies with Pydantic, and translates Python or Alpaca exceptions into HTTP errors.

`backend/intelligence.py` owns computations and external EDGAR access. Keep business logic here when it can be tested without a running FastAPI app. The module intentionally uses in-memory caches for SEC ticker, company facts, and submissions data because this is a hackathon demo server.

## Endpoint Groups

Account and positions:

- `GET /api/account`
- `GET /api/positions`

Market data:

- `POST /api/prices`
- `GET /api/prices/{symbol}/bars?days=5`

Orders:

- `POST /api/orders`
- `GET /api/orders?status=open|closed|all`
- `DELETE /api/orders/{order_id}`
- `DELETE /api/orders`

Portfolio intelligence:

- `GET /api/portfolio/overview`
- `GET /api/portfolio/risk`
- `GET /api/intelligence/{symbol}`

FastAPI also exposes generated OpenAPI documentation at `/docs` and `/redoc`.

## Portfolio Intelligence Details

`compute_overview(account, positions)` is pure. It expects an account snapshot plus enriched Alpaca positions and returns account summary, position weights, largest position, position count, and concentration warnings. Positions over `20%` are flagged as `OVERWEIGHT`.

`fetch_bars(symbols, days, data_client)` wraps Alpaca daily bars using the IEX feed. Route handlers call it before passing normalized bar data into pure calculations.

`compute_risk_metrics(positions, bars_by_symbol, spy_bars)` is pure. It computes per-position 30-day return and daily volatility, then aligns returns by date to calculate portfolio beta versus SPY, annualized Sharpe, max drawdown, and daily 95% value-at-risk.

`get_company_facts(symbol)` and `get_recent_filings(symbol)` call SEC EDGAR. The SEC requires a `User-Agent` header, configured in `SEC_USER_AGENT`. Company CIKs are resolved through `company_tickers.json` and zero-padded to 10 digits.

`compute_fundamental_ratios(facts, price)` extracts recent US-GAAP facts and derives profit margin, debt-to-equity, and P/E when enough data exists.

## Data Contracts

The backend normalizes Alpaca objects into plain JSON dictionaries before returning responses or running calculations. New route handlers should follow that pattern:

- Convert SDK objects to primitives at the API boundary.
- Use uppercase symbols internally.
- Return `None` for unavailable numeric values instead of sentinel strings.
- Prefer pure helper functions for calculations that can be unit tested.
- Preserve clear warning lists when external data is partial.

## Testing

Run tests from `backend/`:

```bash
python3 -m pytest test_api.py -v
```

Many tests call the real Alpaca paper-trading API and require valid credentials. Some order tests submit and cancel paper orders. Keep quantities small and avoid live-trading credentials.

For a narrower Objective 5 check:

```bash
python3 -m pytest test_api.py -v -k "PortfolioIntelligence or risk or overview"
```

The suite also includes pure tests for `compute_risk_metrics` and `compute_overview`, which are safer to extend when changing analytics behavior.

## Adding Features

When adding a route:

1. Add request or response models in `main.py` only when validation is needed.
2. Keep route handlers thin: validate, call clients, normalize data, call pure helpers.
3. Put reusable analytics or EDGAR logic in `intelligence.py`.
4. Add a test in `test_api.py`.
5. Document the endpoint in `README.md` and `docs/USER_GUIDE.md`.

When adding analytics:

1. Make the core calculation a pure function.
2. Define how missing data appears in the response.
3. Add warnings for partial external data.
4. Test edge cases such as no positions, missing bars, zero portfolio value, and non-company instruments.

## Known Gaps

- There is no frontend implementation yet.
- Objective 4 and Objective 6 AI functionality are not implemented in the current backend.
- EDGAR caches are process-local and reset on server restart.
- Integration tests depend on network access, Alpaca account state, market hours, and SEC availability.
- CORS currently allows all origins, which is convenient for demos but should be restricted before production use.
