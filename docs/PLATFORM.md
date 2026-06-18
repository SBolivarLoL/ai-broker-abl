# AI Broker — Platform Overview

AI Broker is a paper-trading platform built around an Alpaca paper-trading account. It gives a
user a live account view, market data, the ability to place simulated orders, AI-generated
advisory commentary, and quantitative portfolio intelligence — all served from one FastAPI
backend (`backend/main.py`, `backend/ai.py`, `backend/intelligence.py`).

## What's in the platform

| Area | Objective | Endpoints | Doc |
|---|---|---|---|
| Account & positions | 1 | `GET /api/account`, `GET /api/positions` | `docs/EXPLAINABILITY.md` |
| Market data | 2 | `POST /api/prices`, `GET /api/prices/{symbol}/bars` | `docs/EXPLAINABILITY.md` |
| Order execution | 3 | `POST /api/orders`, `GET /api/orders`, `DELETE /api/orders/...` | `docs/EXPLAINABILITY.md` |
| AI co-pilot (advisory) | 4 | `GET /api/ai/commentary`, `GET /api/ai/market-news`, `GET /api/ai/portfolio-news`, `GET /api/ai/news/{symbol}`, `POST /api/ai/parse-order`, `GET /api/ai/why-moved/{symbol}` | `FEATURES.md` |
| Portfolio intelligence | 5 | `GET /api/portfolio/overview`, `GET /api/portfolio/risk`, `GET /api/intelligence/{symbol}` | `docs/EXPLAINABILITY.md` |

Interactive API docs are always available at `http://localhost:8000/docs` while the server runs.

## Explainability

> A central file describes **how every feature works and why it was added**.

That file is **[`docs/EXPLAINABILITY.md`](./EXPLAINABILITY.md)**. It is the canonical source for
the reasoning behind each feature — every other doc in the repo (this one, `README.md`,
`FEATURES.md`) links to it instead of repeating the explanation. If you only read one document to
understand *why the platform is built the way it is*, read that one.

It also states the platform's core design rule up front: **AI and analytics features are
advisory-only — only `POST /api/orders` ever executes a trade.**

## How to navigate the docs

- **New user?** Start with `docs/USER_GUIDE.md` for runnable `curl` examples of every endpoint.
- **New contributor?** Start with `docs/DEVELOPER_GUIDE.md` for repo layout and how to add a
  feature.
- **Want the reasoning behind a feature?** Go straight to `docs/EXPLAINABILITY.md`.
- **Want AI-feature request/response examples?** See `FEATURES.md`.

## Running it

```bash
cp .env.example .env        # fill in ALPACA_API_KEY, ALPACA_SECRET_KEY, ANTHROPIC_API_KEY
cd backend && python3 -m pip install -r requirements.txt && cd ..
./run.sh                    # http://localhost:8000  (docs at /docs)
```
