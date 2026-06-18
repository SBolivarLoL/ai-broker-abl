# Explainability

This is the **central file** for explainability across AI Broker. For every feature in the
platform it answers two questions: **how does it work**, and **why was it built**. This file is
the canonical source — other docs (`README.md`, `FEATURES.md`, `USER_GUIDE.md`,
`DEVELOPER_GUIDE.md`) link back here instead of duplicating the reasoning.

Each entry below maps to a hackathon objective and a concrete file/endpoint, so the implementation
can always be traced back to its explanation.

## 1. Account & positions — Objective 1

**Endpoints:** `GET /api/account`, `GET /api/positions` (`backend/main.py`)

**How:** Calls the Alpaca paper-trading SDK directly and normalizes the SDK objects into plain
JSON (cash, buying power, equity, day P&L, and per-position qty/avg price/market value/unrealized
P&L).

**Why:** Every other feature needs a ground-truth view of the account. This is the foundation the
rest of the platform reads from, and it doubles as the simplest way to prove the broker
connection works during a demo.

## 2. Market data — Objective 2

**Endpoints:** `POST /api/prices`, `GET /api/prices/{symbol}/bars` (`backend/main.py`)

**How:** Fetches live bid/ask/midpoint quotes and daily OHLCV bars from Alpaca's market data API
for one or more symbols.

**Why:** Pricing is required before a user can decide to trade, before risk metrics can be
computed (objective 5), and before the AI can explain a price move (objective 4). Built first
because nearly every later feature depends on it.

## 3. Order execution — Objective 3

**Endpoints:** `POST /api/orders`, `GET /api/orders`, `DELETE /api/orders/{order_id}`,
`DELETE /api/orders` (`backend/main.py`)

**How:** Validates the order body with Pydantic, then places/lists/cancels orders through the
Alpaca paper-trading API. Market and limit orders are supported.

**Why:** This is the only place in the platform that actually moves money (paper money). Every
AI/advisory feature is deliberately kept **upstream** of this boundary — they can suggest or
prefill an order, but only this endpoint executes it. That separation is the platform's core
safety design.

## 4. AI co-pilot (advisory) — Objective 4

**Endpoints:** `GET /api/ai/commentary`, `GET /api/ai/market-news`, `GET /api/ai/portfolio-news`,
`GET /api/ai/news/{symbol}`, `POST /api/ai/parse-order`, `GET /api/ai/why-moved/{symbol}`
(`backend/ai.py`, prompts in `backend/ai_prompts.py`)

**How:**
- **Portfolio commentary** asks Claude (model `claude-sonnet-4-6`) to narrate concentration/
  diversification in plain language instead of a metrics table.
- **News & earnings summaries** use Claude's live `web_search` tool with today's date injected, so
  answers reflect current events instead of stale training data.
- **Order-intent parser** turns a plain-English instruction ("buy 100 euros of Apple") into the
  same structured order shape `POST /api/orders` expects, including a USD-notional conversion
  when the user names a cash amount.
- **"Why did this stock move?"** combines Alpaca's daily bars (the actual price move) with recent
  headlines (via web search) and asks Claude to explain the likely drivers, with explicit
  uncertainty language.

**Why:** These are advisory-only by design — see objective 3. They exist to make the platform
feel like a human advisor (commentary, news context, move explanations) and to lower the
friction of placing an order (natural-language parsing) without ever taking the decision out of
the user's hands. Full detail and example payloads: `FEATURES.md`.

## 5. Portfolio intelligence — Objective 5

**Endpoints:** `GET /api/portfolio/overview`, `GET /api/portfolio/risk`,
`GET /api/intelligence/{symbol}` (`backend/main.py`, logic in `backend/intelligence.py`)

**How:**
- `compute_overview` is a pure function over account + positions: it computes position weights,
  the largest position, and flags any position over 20% of the portfolio as `OVERWEIGHT`.
- `compute_risk_metrics` is a pure function over 30 days of daily bars: it aligns returns by date
  to estimate `beta_vs_spy`, an annualized Sharpe ratio, max drawdown, and 1-day 95% VaR, with
  warnings when data is missing.
- `get_company_facts` / `get_recent_filings` pull SEC EDGAR fundamentals (revenue, margins,
  debt-to-equity, P/E, recent 10-K/10-Q/Form 4 activity) for a given ticker, combined with the
  live Alpaca price.

**Why:** Concentration and risk are easy to miss when staring at a position list. These
calculations are kept as pure, testable functions (no network calls inside them) precisely so the
numbers behind any explanation can be unit-tested and trusted — quantitative grounding for what
the AI co-pilot (objective 4) narrates in plain language.

## Design principles behind all of it

- **Advisory vs. execution is a hard boundary.** Only `POST /api/orders` (objective 3) executes.
  Everything else, including all AI features, stops one step before that and hands a suggestion
  or prefilled form back to the user.
- **Pure functions for anything numeric.** Risk and overview calculations take plain data in and
  return plain data out, so they can be tested without hitting Alpaca or SEC, and so their
  reasoning is inspectable line-by-line.
- **Live data over stale training data.** News and price-move explanations are grounded in
  Alpaca bars and Claude's live web search, never the model's static training data.
- **Secrets server-side only.** Alpaca and Anthropic keys live in a gitignored `.env` and are
  never sent to the browser.

## Where to look next

- `README.md` — what the platform does and how to run it.
- `FEATURES.md` — deep dive on the four AI features with example requests/responses.
- `docs/USER_GUIDE.md` — how to use every endpoint as an operator.
- `docs/DEVELOPER_GUIDE.md` — repository layout and how to add a new feature.
