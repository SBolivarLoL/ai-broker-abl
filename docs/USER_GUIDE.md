# User Guide

AI Broker is a paper-trading API that lets you inspect an Alpaca account, view market data, place simulated orders, and review portfolio intelligence. It is designed for hackathon demos and product exploration.

## Before You Start

You need:

- Alpaca paper-trading API credentials.
- Python 3.10 or newer.
- The API server running locally.

Create `.env` from `.env.example` and fill in:

```bash
ALPACA_API_KEY=your_paper_api_key_here
ALPACA_SECRET_KEY=your_paper_secret_key_here
```

Start the app:

```bash
./run.sh
```

Open `http://localhost:8000/docs` for an interactive API explorer.

## Check The Account

Use this to confirm the app is connected to Alpaca:

```bash
curl http://localhost:8000/api/account
```

The response includes account status, cash, buying power, portfolio value, equity, and day P&L.

To see current holdings:

```bash
curl http://localhost:8000/api/positions
```

Positions include symbol, quantity, average entry price, current price, market value, unrealized P&L, and side.

## View Market Data

Fetch bid, ask, midpoint, and timestamp for one or more symbols:

```bash
curl -X POST http://localhost:8000/api/prices \
  -H "Content-Type: application/json" \
  -d '{"symbols":["AAPL","SPY","MSFT"]}'
```

Fetch recent daily bars for a chart:

```bash
curl "http://localhost:8000/api/prices/SPY/bars?days=5"
```

Each bar includes timestamp, open, high, low, close, and volume.

## Place Paper Orders

Place a market buy:

```bash
curl -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{"symbol":"SPY","qty":1,"side":"buy","order_type":"market"}'
```

Place a limit order:

```bash
curl -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","qty":1,"side":"buy","order_type":"limit","limit_price":1.00}'
```

List orders:

```bash
curl "http://localhost:8000/api/orders?status=all"
```

Cancel one order:

```bash
curl -X DELETE http://localhost:8000/api/orders/{order_id}
```

Cancel all open orders:

```bash
curl -X DELETE http://localhost:8000/api/orders
```

This is paper trading, but orders still modify the Alpaca paper account. Use small quantities when demoing.

## Review Portfolio Intelligence

Portfolio overview:

```bash
curl http://localhost:8000/api/portfolio/overview
```

This shows portfolio value, day P&L, position weights, largest position, and concentration warnings. A position is flagged `OVERWEIGHT` when it is more than 20% of the portfolio.

Portfolio risk:

```bash
curl http://localhost:8000/api/portfolio/risk
```

This computes 30-day metrics from Alpaca daily bars:

- `beta_vs_spy`: estimated sensitivity versus SPY.
- `sharpe_30d`: annualized Sharpe estimate from recent daily returns.
- `max_drawdown_pct`: worst peak-to-trough portfolio decline in the sample.
- `var_95_daily`: one-day 95% value-at-risk estimate as a negative percentage.
- `warnings`: symbols or data gaps that affected the calculation.

Symbol intelligence:

```bash
curl http://localhost:8000/api/intelligence/AAPL
```

For company tickers, this combines a live Alpaca price with SEC EDGAR data:

- Revenue, net income, diluted EPS, assets, liabilities, shares outstanding.
- Profit margin, debt-to-equity, and P/E ratio when inputs are available.
- Most recent 10-K and 10-Q filing dates.
- Recent Form 4 filing activity.

For known ETFs and funds such as `SPY`, the endpoint returns a note because those instruments do not have operating-company EDGAR filings.

## Demo Flow

For a short demo, run these in order:

1. `GET /api/account` to prove broker connectivity.
2. `POST /api/prices` with `AAPL`, `SPY`, and `MSFT` to show market data.
3. `POST /api/orders` with a small paper order to show trading.
4. `GET /api/portfolio/overview` to show portfolio health at a glance.
5. `GET /api/portfolio/risk` to show quantitative intelligence.
6. `GET /api/intelligence/AAPL` to show EDGAR fundamentals.

## Limitations

- The current repository does not include a user interface.
- All Alpaca calls require valid paper-trading credentials.
- Risk metrics depend on recent IEX daily bars and may return warnings when data is missing.
- EDGAR data is cached in memory for the current server session.
- The analytics are educational and should not be treated as financial advice.
