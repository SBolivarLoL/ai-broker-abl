# AI Broker — Features (objectives 4, 5, 6) on top of the base (1, 2, 3)

This file explains **what** we built, **how** it works, **why**, and **what it looks like**.
That also covers **objective 8 (Explainability)**.

## How it fits together

```
Lovable frontend (browser)              FastAPI backend (backend/)              External APIs
──────────────────────────              ─────────────────────────               ─────────────
fetch("http://localhost:8000/...")  ►   main.py   (obj 1,2,3 — teammate)  ►  Alpaca (account/prices/orders)
                                        ai.py     (obj 4,5,6 — us)        ►  Alpaca (data) + Claude API
```

- **One backend.** Our features are FastAPI endpoints in `backend/ai.py`, wired into
  `main.py` with `app.include_router(ai_router)`. We did not rewrite the teammate's base.
- **Keys live server-side** in `.env` (repo root, **gitignored**): `ALPACA_API_KEY`,
  `ALPACA_SECRET_KEY`, `ANTHROPIC_API_KEY`. Never in the browser, never in git.
- **Model:** `claude-sonnet-4-6` (fast + cheap enough; see `ai_prompts.py`).

## Data sources (where does the info come from?)

| What | Source |
|------|--------|
| Prices, positions, orders | **Alpaca** (already wired in `main.py`) |
| Reasoning / ideas / analysis | **Claude API** |
| (optional) current news | Claude `web_search` tool — can be enabled in `ai.py` (`/api/ai/chat`) |

You don't scrape anything yourself: Alpaca provides market+portfolio, Claude does the thinking.

## Our endpoints — what they do and what they look like

### Objective 5 — Portfolio Intelligence (risk metrics)
`GET /api/portfolio/metrics` — pure calculation on your Alpaca positions, no AI needed.
```json
{
  "total_value": 100000, "cash_pct": 100, "positions_count": 0,
  "largest_position_pct": 0, "top_holding": "—",
  "diversification_score": 100, "day_pl": 0, "day_pl_pct": 0
}
```

### Objective 4 — AI Co-pilot (advisory, NEVER places orders)
`POST /api/ai/chat` — free-form Q&A about your portfolio.
```bash
curl -X POST localhost:8000/api/ai/chat -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is my biggest risk?"}]}'
# -> { "reply": "Your portfolio is 100% cash..." }
```

`POST /api/ai/ideas` — structured trade ideas (Claude calls a tool).
```json
{ "ideas": [
  { "ticker": "SPY", "side": "buy", "notional": 30000, "rationale": "Broad market base..." }
]}
```

`GET /api/ai/review` — portfolio analysis in plain language (bridge between obj 4 and 5).

### Objective 6 — Agentic trading agent  ← "tell the AI to buy stocks"
`POST /api/ai/agent` — agentic loop with tool use. Two phases:

1. **Propose** (`approve=false`): you give a plain-English instruction; the agent fetches
   quotes (`get_quote`) and proposes orders.
```bash
curl -X POST localhost:8000/api/ai/agent -H "Content-Type: application/json" \
  -d '{"instruction":"Buy $20,000 of AAPL and $10,000 of NVDA","approve":false}'
# -> { "message":"I propose...", "proposed_orders":[ {...} ], "executed_orders":[] }
```
2. **Execute** (`approve=true`): you send the approved orders back; the agent places them via Alpaca.
```bash
curl -X POST localhost:8000/api/ai/agent -H "Content-Type: application/json" \
  -d '{"approve":true,"approved_orders":[{"ticker":"AAPL","side":"buy","notional":20000,"rationale":"..."}]}'
# -> { "message":"Placed.", "proposed_orders":[], "executed_orders":[ {...} ] }
```

This is exactly "tell the AI what you want → say yes → the AI does it". **Obj 4 advises, obj 6 executes.**
The values/ESG screening (obj 7) is intentionally **not** here — that's a separate feature.

## What it looks like for the user (Lovable frontend)

The Lovable site renders these endpoints as 4 panels:
- **Market View** (obj 2) → `/api/prices` + `/api/prices/{sym}/bars` (teammate's base).
- **AI Co-pilot** (obj 4) → chat box (`/api/ai/chat`) + "Trade ideas" button (`/api/ai/ideas`).
- **Portfolio Intelligence** (obj 5) → metric cards (`/api/portfolio/metrics`) + "Explain with AI" (`/api/ai/review`).
- **Trading Agent** (obj 6) → instruction field → list of proposed orders → green "Approve & execute" button.

In Lovable you point the fetch base URL at the backend (locally `http://localhost:8000`).

## Run it (locally)

```bash
pip install -r backend/requirements.txt
# fill in .env in the repo root (ALPACA_* + ANTHROPIC_API_KEY)
python backend/demo.py            # shows obj 1,2,4,5,6 in one run
python backend/demo.py --execute  # also lets the agent actually place a paper order
# or the clickable UI:
./run.sh                          # http://localhost:8000
open http://localhost:8000/docs   # Swagger: try every endpoint
```

> ⚠️ In a sandbox with egress restrictions Alpaca/Claude returns a network error
> ("host not in allowlist"). Locally, or in an environment with internet, it works.

## Key design choices (why)

- **AI as a separate router (`ai.py`)** → we barely touch the teammate's base (1 line in `main.py`).
- **`claude-sonnet-4-6`** instead of Opus → fast and cheap, plenty for these tasks.
- **Obj 4 never places orders; obj 6 does (after approval)** → clear split advisory vs. agentic.
- **Risk metrics in pure Python** → no AI call needed, instant and free.
- **Keys in a gitignored `.env`** → never in git, never in the browser.

## Status / to do

- [ ] Fill in `ANTHROPIC_API_KEY` in `.env`
- [ ] Regenerate the keys that were shared in chat (Alpaca + Anthropic) and put the new ones in `.env`
- [ ] Point the Lovable frontend's 4 panels at the backend
- [ ] Optional: enable the `web_search` tool in `/api/ai/chat` for live news
