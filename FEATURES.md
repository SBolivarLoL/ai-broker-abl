# AI Broker — Features (objectives 4, 5, 6) bovenop de basis (1, 2, 3)

Dit bestand legt uit **wat** we hebben gebouwd, **hoe** het werkt, **waarom**, en **hoe het eruitziet**.
Daarmee dekt het meteen **objective 8 (Explainability)**.

## Hoe het in elkaar zit

```
Lovable frontend (browser)              FastAPI backend (backend/)              Externe API's
──────────────────────────              ─────────────────────────               ─────────────
fetch("http://localhost:8000/...")  ►   main.py   (obj 1,2,3 — teammate)  ►  Alpaca (account/prijzen/orders)
                                        ai.py     (obj 4,5,6 — wij)       ►  Alpaca (data) + Claude API
```

- **Eén backend.** Onze features zijn FastAPI-endpoints in `backend/ai.py`, ingehaakt in
  `main.py` met `app.include_router(ai_router)`. We hebben de basis van de teammate **niet** herschreven.
- **Keys staan server-side** in `.env` (repo-root, **gitignored**): `ALPACA_API_KEY`,
  `ALPACA_SECRET_KEY`, `ANTHROPIC_API_KEY`. Nooit in de browser, nooit in git.
- **Model:** `claude-sonnet-4-6` (snel + goedkoop genoeg; zie `ai_prompts.py`).

## Databronnen (waar komt de info vandaan?)

| Wat | Bron |
|-----|------|
| Koersen, posities, orders | **Alpaca** (al gekoppeld in `main.py`) |
| Redeneren / ideeën / analyse | **Claude API** |
| (optioneel) actueel nieuws | Claude `web_search`-tool — aan te zetten in `ai.py` (`/api/ai/chat`) |

Je hoeft zelf geen data te scrapen: Alpaca levert markt+portfolio, Claude doet het denkwerk.

## Onze endpoints — wat ze doen en hoe ze eruitzien

### Objective 5 — Portfolio Intelligence (risk metrics)
`GET /api/portfolio/metrics` — pure berekening op je Alpaca-posities, geen AI nodig.
```json
{
  "total_value": 10182.3, "cash_pct": 41.7, "positions_count": 3,
  "largest_position_pct": 26.7, "top_holding": "NVDA",
  "diversification_score": 64, "day_pl": 423.7, "day_pl_pct": 4.1
}
```

### Objective 4 — AI Co-pilot (adviserend, plaatst NOOIT orders)
`POST /api/ai/chat` — vrije vraag/antwoord over je portefeuille.
```bash
curl -X POST localhost:8000/api/ai/chat -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hoe staat mijn spreiding ervoor?"}]}'
# -> { "reply": "Je portefeuille leunt zwaar op NVDA (27%)..." }
```

`POST /api/ai/ideas` — gestructureerde trade-ideeën (Claude roept een tool aan).
```json
{ "ideas": [
  { "ticker": "GOOGL", "side": "buy", "notional": 500, "rationale": "Spreiding richting..." },
  { "ticker": "TSLA",  "side": "sell", "qty": 2,        "rationale": "Concentratie verlagen..." }
]}
```

`GET /api/ai/review` — portefeuille-analyse in gewone taal (brug tussen obj 4 en 5).
```json
{ "review": "Je portefeuille is geconcentreerd in tech. NVDA is je grootste positie..." }
```

### Objective 6 — Agentic trading agent
`POST /api/ai/agent` — agentic loop met tool-use. Twee fases:

1. **Voorstellen** (`approve=false`): de agent haalt koersen op (`get_quote`) en stelt orders voor.
```bash
curl -X POST localhost:8000/api/ai/agent -H "Content-Type: application/json" \
  -d '{"instruction":"Verlaag mijn risico","approve":false}'
# -> { "message":"Ik stel voor...", "proposed_orders":[ {...} ], "executed_orders":[] }
```
2. **Uitvoeren** (`approve=true`): jij stuurt de goedgekeurde orders terug; de agent plaatst ze via Alpaca.
```bash
curl -X POST localhost:8000/api/ai/agent -H "Content-Type: application/json" \
  -d '{"approve":true,"approved_orders":[{"ticker":"TSLA","side":"sell","qty":2,"rationale":"..."}]}'
# -> { "message":"Geplaatst.", "proposed_orders":[], "executed_orders":[ {...} ] }
```

Dit is precies "vertel de AI wat je wilt → zeg ja → de AI doet het". **Obj 4 adviseert, obj 6 voert uit.**
De waarden-/eco-screening (obj 7) zit hier bewust **niet** in — dat is een andere feature.

## Hoe het er voor de gebruiker uitziet (Lovable frontend)

De Lovable-site rendert deze endpoints als 4 panelen:
- **Market View** (obj 2) → `/api/prices` + `/api/prices/{sym}/bars` (basis van teammate).
- **AI Co-pilot** (obj 4) → chat-box (`/api/ai/chat`) + knop "Trade-ideeën" (`/api/ai/ideas`).
- **Portfolio Intelligence** (obj 5) → metric-cards (`/api/portfolio/metrics`) + knop "Leg uit met AI" (`/api/ai/review`).
- **Trading Agent** (obj 6) → instructie-veld → lijst voorgestelde orders → groene "Goedkeuren & uitvoeren"-knop.

In Lovable wijs je de fetch-base aan naar de backend-URL (lokaal `http://localhost:8000`).

## Draaien (lokaal)

```bash
pip install -r backend/requirements.txt
# .env in repo-root invullen (ALPACA_* staan er al; vul ANTHROPIC_API_KEY in)
./run.sh                      # start op http://localhost:8000
open http://localhost:8000/docs   # interactieve Swagger-UI om alles te testen
```

> ⚠️ In een sandbox met egress-restricties geeft Alpaca/Claude een netwerk-error
> ("host not in allowlist"). Lokaal of in een omgeving met internet werkt het wel.

## Belangrijke ontwerpkeuzes (waarom)

- **AI als losse router (`ai.py`)** → we raken de basis van de teammate nauwelijks aan (1 regel in `main.py`).
- **`claude-sonnet-4-6`** i.p.v. Opus → snel en goedkoop, ruim voldoende voor deze taken.
- **Obj 4 plaatst nooit orders; obj 6 wel (na goedkeuring)** → duidelijke scheiding advies vs. agentic.
- **Risk metrics in pure Python** → geen AI-call nodig, instant en gratis.
- **Keys in gitignored `.env`** → nooit in git, nooit in de browser.

## Status / nog te doen

- [ ] `ANTHROPIC_API_KEY` invullen in `.env`
- [ ] (Alpaca paper keys staan al lokaal; in de chat gedeelde keys: overweeg te regenereren)
- [ ] Lovable-frontend de 4 panelen op de backend laten wijzen
- [ ] Optioneel: `web_search`-tool aanzetten in `/api/ai/chat` voor live nieuws
