"""
DEMO — test all features locally in one run, without typing separate curl commands.

Usage:
    pip install -r backend/requirements.txt
    # fill in .env in the repo root (ALPACA_* + ANTHROPIC_API_KEY)
    python backend/demo.py              # everything except actually placing orders
    python backend/demo.py --execute    # also let the agent EXECUTE its proposed buy (paper money!)

The script uses FastAPI's TestClient, so you don't have to start uvicorn separately.
"""
import sys
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
EXECUTE = "--execute" in sys.argv

# The agent example: a plain-English buy instruction. This is the core team idea —
# "tell the AI to buy certain stocks" -> it proposes -> you approve -> it executes.
AGENT_INSTRUCTION = "Buy $20,000 of AAPL and $10,000 of NVDA to start my portfolio."


def section(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def show(resp):
    if resp.status_code != 200:
        print(f"  !! status {resp.status_code}: {resp.text[:300]}")
        return None
    return resp.json()


# ── Objective 1/2: base (from your teammate) ──────────────────────────────────
section("OBJECTIVE 1 — Account (base)")
acct = show(client.get("/api/account"))
if acct:
    print(f"  Cash: ${acct['cash']:.2f} | Value: ${acct['portfolio_value']:.2f} | "
          f"Day P/L: ${acct['day_pnl']:.2f} ({acct['day_pnl_pct']:.2f}%)")

section("OBJECTIVE 2 — Prices (base)")
prices = show(client.post("/api/prices", json={"symbols": ["AAPL", "MSFT", "SPY"]}))
if prices:
    for sym, q in prices.items():
        print(f"  {sym}: mid ${q['mid']}")

# ── Objective 5: risk metrics (ours) ──────────────────────────────────────────
section("OBJECTIVE 5 — Portfolio Intelligence (risk metrics)")
metrics = show(client.get("/api/portfolio/metrics"))
if metrics:
    print(f"  Total value: ${metrics['total_value']:.0f}")
    print(f"  Cash: {metrics['cash_pct']:.0f}%  |  Positions: {metrics['positions_count']}")
    print(f"  Largest position: {metrics['top_holding']} ({metrics['largest_position_pct']:.0f}%)")
    print(f"  Diversification score: {metrics['diversification_score']}/100")

# ── Objective 4: AI co-pilot (ours) ───────────────────────────────────────────
section("OBJECTIVE 4 — AI portfolio review")
review = show(client.get("/api/ai/review"))
if review:
    print("  " + review["review"].replace("\n", "\n  "))

section("OBJECTIVE 4 — AI trade ideas")
ideas = show(client.post("/api/ai/ideas"))
if ideas:
    for i in ideas["ideas"]:
        amt = f"{i.get('qty')} shares" if i.get("qty") else f"${i.get('notional')}"
        print(f"  • {i['side'].upper()} {i['ticker']} ({amt}) — {i['rationale']}")

section("OBJECTIVE 4 — AI co-pilot chat")
chat = show(client.post("/api/ai/chat", json={
    "messages": [{"role": "user", "content": "What is my biggest risk right now?"}]
}))
if chat:
    print("  " + chat["reply"].replace("\n", "\n  "))

# ── Objective 6: agentic agent (ours) ─────────────────────────────────────────
section("OBJECTIVE 6 — Agentic agent: PROPOSE")
print(f'  Instruction: "{AGENT_INSTRUCTION}"')
agent = show(client.post("/api/ai/agent", json={
    "instruction": AGENT_INSTRUCTION, "approve": False
}))
if agent:
    print("  " + agent["message"].replace("\n", "\n  "))
    for o in agent["proposed_orders"]:
        amt = f"{o.get('qty')} shares" if o.get("qty") else f"${o.get('notional')}"
        print(f"  → proposal: {o['side'].upper()} {o['ticker']} ({amt}) — {o.get('rationale', '')}")

    if EXECUTE and agent["proposed_orders"]:
        section("OBJECTIVE 6 — Agentic agent: EXECUTE (paper)")
        done = show(client.post("/api/ai/agent", json={
            "approve": True, "approved_orders": agent["proposed_orders"]
        }))
        if done:
            print("  " + done["message"].replace("\n", "\n  "))
            for o in done["executed_orders"]:
                print(f"  ✓ executed: {o['side']} {o['qty']} {o['ticker']} — {o['status']}")
    elif agent["proposed_orders"]:
        print("\n  (Run with --execute to actually place these orders — paper money.)")

print("\nDone. Also open http://localhost:8000/docs for the interactive UI.\n")
