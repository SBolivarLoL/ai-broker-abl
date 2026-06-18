"""
DEMO — try the four AI features locally in one run.

Usage:
    pip install -r backend/requirements.txt
    # fill in .env in the repo root (ALPACA_* + ANTHROPIC_API_KEY)
    python backend/demo.py

Uses FastAPI's TestClient, so you don't need to start uvicorn separately.
None of these features place orders — they are all advisory.
"""
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def section(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def show(resp):
    if resp.status_code != 200:
        print(f"  !! status {resp.status_code}: {resp.text[:300]}")
        return None
    return resp.json()


# ── 1. Portfolio commentary (natural language) ────────────────────────────────
section("1 — Portfolio commentary")
c = show(client.get("/api/ai/commentary"))
if c:
    print("  " + c["commentary"].replace("\n", "\n  "))

# ── 2. News / earnings summary per ticker ─────────────────────────────────────
section("2 — News / earnings summary (AAPL)")
n = show(client.get("/api/ai/news/AAPL"))
if n:
    print("  " + n["summary"].replace("\n", "\n  "))

# ── 3. Natural-language -> order intent parser ────────────────────────────────
section("3 — Natural-language order parser")
text = "buy 100 euros of Apple"
print(f'  Input: "{text}"')
p = show(client.post("/api/ai/parse-order", json={"text": text}))
if p:
    print(f"  Interpretation: {p['interpretation']}")
    print(f"  Order ticket (prefills teammate's order form): {p['order_ticket']}")
    if p["needs_clarification"]:
        print(f"  Needs clarification: {p['clarification']}")
    print("  (NOTE: nothing executed — this only fills the order ticket.)")

# ── 4. Why did this stock move? ───────────────────────────────────────────────
section("4 — Why did this stock move? (AAPL)")
w = show(client.get("/api/ai/why-moved/AAPL"))
if w:
    if w["move"]["change_pct"] is not None:
        print(f"  Move: {w['move']['change_pct']:+.2f}%")
    print("  " + w["explanation"].replace("\n", "\n  "))

print("\nDone. Also open http://localhost:8000/docs for the interactive UI.\n")
