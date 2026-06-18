"""
DEMO — test alle features lokaal in één run, zonder dat je losse curl-commando's hoeft te typen.

Gebruik:
    pip install -r backend/requirements.txt
    # vul .env in repo-root in (ALPACA_* + ANTHROPIC_API_KEY)
    python backend/demo.py              # alles behalve echt orders plaatsen
    python backend/demo.py --execute    # laat de agent de voorgestelde order OOK uitvoeren (paper!)

Het script gebruikt FastAPI's TestClient, dus je hoeft uvicorn niet apart te starten.
"""
import sys
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
EXECUTE = "--execute" in sys.argv


def section(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def show(resp):
    if resp.status_code != 200:
        print(f"  !! status {resp.status_code}: {resp.text[:300]}")
        return None
    return resp.json()


# ── Objective 1/2: basis (van je teammate) ────────────────────────────────────
section("OBJECTIVE 1 — Account (basis)")
acct = show(client.get("/api/account"))
if acct:
    print(f"  Cash: ${acct['cash']:.2f} | Waarde: ${acct['portfolio_value']:.2f} | "
          f"Dag W/V: ${acct['day_pnl']:.2f} ({acct['day_pnl_pct']:.2f}%)")

section("OBJECTIVE 2 — Prijzen (basis)")
prices = show(client.post("/api/prices", json={"symbols": ["AAPL", "MSFT", "SPY"]}))
if prices:
    for sym, q in prices.items():
        print(f"  {sym}: mid ${q['mid']}")

# ── Objective 5: risk metrics (wij) ───────────────────────────────────────────
section("OBJECTIVE 5 — Portfolio Intelligence (risk metrics)")
metrics = show(client.get("/api/portfolio/metrics"))
if metrics:
    print(f"  Totale waarde: ${metrics['total_value']:.0f}")
    print(f"  Cash: {metrics['cash_pct']:.0f}%  |  Posities: {metrics['positions_count']}")
    print(f"  Grootste positie: {metrics['top_holding']} ({metrics['largest_position_pct']:.0f}%)")
    print(f"  Spreidingsscore: {metrics['diversification_score']}/100")

# ── Objective 4: AI co-pilot (wij) ────────────────────────────────────────────
section("OBJECTIVE 4 — AI portfolio-review")
review = show(client.get("/api/ai/review"))
if review:
    print("  " + review["review"].replace("\n", "\n  "))

section("OBJECTIVE 4 — AI trade-ideeen")
ideas = show(client.post("/api/ai/ideas"))
if ideas:
    for i in ideas["ideas"]:
        amt = f"{i.get('qty')} aandelen" if i.get("qty") else f"${i.get('notional')}"
        print(f"  • {i['side'].upper()} {i['ticker']} ({amt}) — {i['rationale']}")

section("OBJECTIVE 4 — AI co-pilot chat")
chat = show(client.post("/api/ai/chat", json={
    "messages": [{"role": "user", "content": "Wat is mijn grootste risico op dit moment?"}]
}))
if chat:
    print("  " + chat["reply"].replace("\n", "\n  "))

# ── Objective 6: agentic agent (wij) ──────────────────────────────────────────
section("OBJECTIVE 6 — Agentic agent: VOORSTEL")
agent = show(client.post("/api/ai/agent", json={
    "instruction": "Verlaag mijn risico met maximaal 1 order.", "approve": False
}))
if agent:
    print("  " + agent["message"].replace("\n", "\n  "))
    for o in agent["proposed_orders"]:
        print(f"  → voorstel: {o['side'].upper()} {o['ticker']} — {o.get('rationale', '')}")

    if EXECUTE and agent["proposed_orders"]:
        section("OBJECTIVE 6 — Agentic agent: UITVOEREN (paper)")
        done = show(client.post("/api/ai/agent", json={
            "approve": True, "approved_orders": agent["proposed_orders"]
        }))
        if done:
            print("  " + done["message"].replace("\n", "\n  "))
            for o in done["executed_orders"]:
                print(f"  ✓ uitgevoerd: {o['side']} {o['qty']} {o['ticker']} — {o['status']}")
    elif agent["proposed_orders"]:
        print("\n  (Run met --execute om deze order echt te plaatsen — paper money.)")

print("\nKlaar. Open ook http://localhost:8000/docs voor de interactieve UI.\n")
