# AI Broker — AI features (objective 4, advisory) on top of the base (1, 2, 3)

This explains **what** we built, **how** it works, **why**, and **what it looks like**.
That also covers **objective 8 (Explainability)**.

All four features are **advisory** — they never place orders. Executing stays with the
order ticket (objective 3, your teammate's `POST /api/orders`).

## How it fits together

```
Lovable frontend (browser)              FastAPI backend (backend/)              External APIs
──────────────────────────              ─────────────────────────               ─────────────
fetch("http://localhost:8000/...")  ►   main.py   (obj 1,2,3 — teammate)  ►  Alpaca (account/prices/orders)
                                        ai.py     (obj 4 — us)            ►  Alpaca (positions/news/bars) + Claude API
```

- Our features are FastAPI endpoints in `backend/ai.py`, wired into `main.py` with one line
  (`app.include_router(ai_router)`). We don't rewrite the teammate's base.
- Keys live server-side in `.env` (repo root, **gitignored**): `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ANTHROPIC_API_KEY`.
- Model: `claude-sonnet-4-6`. Prompts live in `ai_prompts.py`.

## The four features

### 1. Portfolio commentary — `GET /api/ai/commentary`
Natural-language commentary on what you hold and how concentrated/diversified you are — like a
human advisor, **not** a table of metrics.
```json
{ "commentary": "You're holding three large-cap tech names, which means little real diversification..." }
```

### 2. News / earnings summary — live web search
Both use Claude's **live web_search** tool, grounded in fresh results (today's date injected), so they do
**not** rely on stale training data.
- `GET /api/ai/market-news` — digest of the **most important stocks today** (biggest movers, major
  headlines, Fed/market mood across large caps).
- `GET /api/ai/news/{symbol}` — recent news for **one specific ticker**.
```json
{ "summary": "US Stock Market Digest — June 18, 2026: chips rallied (INTC +9%)..., Accenture fell 11%..." }
```

### 3. Natural-language → order-intent parser — `POST /api/ai/parse-order`
Turns plain text into a structured order intent that **prefills the order ticket** (objective 3).
It **stops before executing** — your teammate's `/api/orders` does the actual placing after the user confirms.
```bash
curl -X POST localhost:8000/api/ai/parse-order -H "Content-Type: application/json" \
  -d '{"text":"buy 100 euros of Apple"}'
```
```json
{
  "order_ticket": { "symbol": "AAPL", "side": "buy", "order_type": "market", "qty": 0.34, "time_in_force": "day", "limit_price": null },
  "notional": 100, "currency": "EUR",
  "interpretation": "BUY $100 of AAPL (market)",
  "needs_clarification": false
}
```
> Note: Alpaca trades in USD, so a cash amount is treated as USD notional and converted to an
> approximate `qty` using the current price. The frontend uses `order_ticket` to fill the form.

### 4. "Why did this stock move?" — `GET /api/ai/why-moved/{symbol}`
Combines the recent price move (daily bars) with recent headlines and explains the likely drivers,
honest about uncertainty.
```json
{ "symbol": "AAPL", "move": { "change_pct": -2.1, "last_close": 288.0, "prev_close": 294.2 },
  "explanation": "The ~2% drop likely reflects..." }
```

## What it looks like for the user (Lovable frontend)

- **Portfolio panel** → "Explain my portfolio" button → `/api/ai/commentary`.
- **Per-stock view** → "Summarize news" → `/api/ai/news/{symbol}`, and "Why did it move?" → `/api/ai/why-moved/{symbol}`.
- **Order ticket** → a text box "type your order in plain English" → `/api/ai/parse-order` fills the
  symbol/side/qty fields; the user reviews and clicks the existing Buy/Sell button (obj 3) to actually place it.

## Run it (locally)

```bash
pip install -r backend/requirements.txt
# fill in .env in the repo root (ALPACA_* + ANTHROPIC_API_KEY)
python backend/demo.py            # shows all four features
./run.sh                          # http://localhost:8000  (then open /docs)
```

> ⚠️ In a sandbox with egress restrictions Alpaca/Claude returns a network error
> ("host not in allowlist"). Locally it works.

## Key design choices (why)

- **All advisory, no execution** → these are objective-4 AI helpers; placing orders stays in the
  order ticket (obj 3). Clean separation, and no overlap with the values/ESG screening (obj 7).
- **Parser outputs the teammate's order shape** → it drops straight into the existing order form.
- **News comes from live web search (Claude `web_search`); the price move comes from Alpaca bars** → always recent, no scraping needed.
- **Keys in a gitignored `.env`** → never in git, never in the browser.

## Status / to do

- [ ] Fill in `ANTHROPIC_API_KEY` in `.env`; regenerate the keys shared earlier in chat
- [ ] Wire the four buttons into the Lovable frontend
- [ ] Optional: enable Claude's `web_search` tool for "why-moved" when Alpaca news is thin
