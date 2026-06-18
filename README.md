# AI Broker - Paper Trading API

AI Broker is a FastAPI backend for the AI Broker Hackathon. It connects to an Alpaca paper-trading account, exposes live market data and paper order endpoints, and adds portfolio intelligence using Alpaca market data plus SEC EDGAR fundamentals.

The current repository is backend-first. The `frontend/` directory is present but empty, so the working product surface is the HTTP API served from `backend/main.py`.

## What It Does

- Shows live Alpaca paper account details, balances, P&L, and positions.
- Fetches recent bid, ask, midpoint, and daily OHLCV bars for symbols.
- Places, lists, and cancels Alpaca paper orders.
- Summarizes portfolio concentration and overweight positions.
- Computes 30-day portfolio risk metrics from daily bars.
- Pulls SEC EDGAR fundamentals and filing activity for company tickers.

## Quick Start

1. Create a `.env` file from `.env.example`.
2. Add Alpaca paper-trading API credentials.
3. Install Python dependencies:

```bash
cd backend
python3 -m pip install -r requirements.txt
```

4. Start the API from the repository root:

```bash
./run.sh
```

The server runs at `http://localhost:8000`.

## Documentation

- Platform overview: `docs/PLATFORM.md`
- Explainability (how every feature works and why it was added): `docs/EXPLAINABILITY.md`
- AI features deep dive: `FEATURES.md`
- User guide: `docs/USER_GUIDE.md`
- Developer guide: `docs/DEVELOPER_GUIDE.md`
- Original Objective 5 implementation notes: `../objective5.md`

## Useful Endpoints

- `GET /api/account`
- `GET /api/positions`
- `POST /api/prices`
- `GET /api/prices/{symbol}/bars`
- `POST /api/orders`
- `GET /api/orders`
- `DELETE /api/orders/{order_id}`
- `DELETE /api/orders`
- `GET /api/portfolio/overview`
- `GET /api/portfolio/risk`
- `GET /api/intelligence/{symbol}`

Interactive OpenAPI docs are available while the server is running at `http://localhost:8000/docs`.

## Safety Notes

This app uses Alpaca paper trading, not live brokerage trading. Keep credentials in `.env`; do not commit real API keys. The portfolio intelligence endpoints are for demo and educational use, not investment advice.
