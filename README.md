# Energy Intelligence Platform

An AI-powered smart energy management and renewable optimisation platform, built on
22,084 half-hourly meter readings from ten sites and a weather-integrated inefficiency
model.

It answers the questions a bill cannot: **which appliance is consuming the most, whether
that consumption is actually justified by the weather, what tomorrow will cost, when to
run flexible loads, and what to do about it.**

---

## The one rule this project is built around

**Every figure carries its provenance.** The API tags each value `measured`,
`predicted`, `estimated`, `simulated`, or `unavailable`, and the UI shows that tag
rather than hiding it.

| Tag | Meaning |
|---|---|
| `measured` | Read from the meter data. Energy, runtime, peak power, recorded weather. |
| `predicted` | Model output, reported with its own measured error. Expected energy, the forecast. |
| `estimated` | Derived from configured rates, not from a real bill or meter. Cost, carbon. |
| `simulated` | Modelled for demonstration, off by default, never shown as real. |
| `unavailable` | Not in this dataset. The response says so and explains why. |

Nothing is fabricated to fill a gap. There is no solar, battery, EV or tariff data in
this corpus, so those are typed integration points that report their absence — not
invented numbers.

---

## Quick start

```bash
# 1. Backend
python -m venv .venv
.venv/Scripts/activate            # Windows;  source .venv/bin/activate on Unix
pip install -r requirements.txt
cp .env.example .env              # works as-is: Open-Meteo needs no key

python -m ml.train                # train and persist the model artefacts (~10 s)
uvicorn backend.main:app --reload # http://127.0.0.1:8000  (docs at /docs)

# 2. Frontend, in a second terminal
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

The dashboard opens on a populated site with real analysis — no configuration needed.

> **Python 3.11 or 3.12 is recommended.** The stack (pandas, scikit-learn, xgboost) has
> prebuilt wheels there; 3.14 may try to build from source.

Run the tests with `python -m pytest tests/ -q` (110 tests) and typecheck the frontend
with `npm run typecheck`.

---

## What it does

### Measure and understand
Half-hourly readings across 10 sites become energy, cost and carbon at hourly, daily,
weekly and monthly granularity, broken down per appliance with runtime, duty cycle,
peak and mean power.

### Detect
The ported inefficiency model flags days where an appliance exceeded what it *should*
have used — separating **high consumption**, **long runtime**, **abnormal power draw**
and **short cycling** rather than lumping them together. A hot day does not trigger a
flag by itself: the heat index is an input to the expected-energy baseline, so weather
raises the expectation before anything is compared.

### Predict
A separate daily forecaster (the existing model is a classifier and cannot forecast)
competes ridge regression against a seasonal-naive baseline by walk-forward validation,
picks the winner per site, and reports **its measured error as the uncertainty band**.
If it cannot beat a flat long-run average, it says so.

### Explain
Every verdict comes with a paragraph assembled from measured values and model output —
no language model required. The LLM rephrases these; it never invents them.

### Optimise
Each appliance's measured hourly load is repriced at the cheapest feasible hours under
the configured tariff. **Critical loads are never proposed for shifting**, by
classification rather than heuristic. Partially flexible loads (an air conditioner) move
only their peak-hour portion.

### Act
A deterministic rule engine produces ranked recommendations, each with its reason,
estimated impact, saving, and a confidence that reflects the evidence behind it.

---

## Architecture

```
data/raw/*.csv
      │
      ▼
data/  ─────────  loaders → validators → transformers      (one ingestion path, cached)
      │
      ▼
ml/    ─────────  feature_engineering → baseline → model_loader → prediction
      │           (the notebook pipeline, ported and persisted to ml/artifacts/)
      ▼
backend/services/ energy · ml · weather · forecast · tariff · optimization
      │           renewable · carbon · score · replacement · recommendation
      │           context · ai
      ▼
backend/api/      FastAPI routers, every optional service degrading independently
      │
      ▼
frontend/src/     React + TypeScript + Tailwind + Recharts
```

### Layout

| Path | Contains |
|---|---|
| `data/` | Ingestion: `schema.py` (channels, flexibility, provenance), `loaders/`, `validators/`, `transformers/` |
| `ml/` | The ported pipeline: features, baseline, reliability grading, serving, `train.py` |
| `backend/` | `config.py`, `api/`, `services/`, `schemas/`, `database/`, `utils/` |
| `frontend/src/` | `pages/`, `components/`, `charts/`, `services/`, `hooks/`, `types/`, `utils/` |
| `tests/` | 110 tests over data, ML, services and the API |
| `notebooks/` | The original notebooks, kept for reference |
| `PROJECT_AUDIT.md` | **Read this first** — what the data actually contains and what it cannot support |

---

## The ML model

The existing weather-integrated notebook is **ported, not rewritten**: identical feature
maths, the same `LinearRegression` expected-energy baseline, the same star-adjusted
residual threshold, the same XGBoost hyperparameters and chronological 70/30 split.
`python -m ml.train` fits it once and writes artefacts, so serving never retrains.

```
daily features (20)  →  expected_energy ~ on_duration + duty_cycle + cycles + heat_index
                     →  residual = actual − expected
                     →  threshold = 75th pct × (2 − stars / max_stars)
                     →  XGBoost over 9 behavioural features
```

### Coverage and honesty

Four (site, appliance) pairs train. Only one validates well, and the platform says so
everywhere it matters:

| Site | Appliance | Active days | Test accuracy | ROC-AUC | Verdict |
|---|---|---|---|---|---|
| `House_4` | AC | 90 | 0.82 | 0.86 | **Validated** — the classifier leads |
| `House1_Delhi` | AC | 27 | 0.22 | 0.50 | Too few positives to validate |
| `House_1` | Geyser | 18 | 0.83 | 0.50 | Too few positives to validate |
| `House_2` | Geyser | 11 | 0.50 | 0.50 | Too few positives to validate |

Where the classifier is not trustworthy, **the expected-energy comparison decides the
verdict** and the UI states that the classifier is unreliable — the probability is still
shown, labelled, for transparency. The model registry page publishes every metric,
including the one that ranks no better than chance.

The pipeline is extended beyond the notebook's hard-coded pair list: sites without
appliance metadata train with the *unadjusted* threshold and are recorded
`star_adjusted: false`, so the difference is visible rather than papered over.

---

## Configuration

Everything that is policy rather than measurement lives in `.env` (see `.env.example`).

- **Weather** — Open-Meteo by default and needs **no key**. OpenWeather and WeatherAPI
  are supported with one. All calls are server-side; the key never reaches the browser.
- **LLM** — optional. Anthropic (`claude-opus-5`), OpenAI, or Gemini. Without a key the
  assistant answers deterministically from the same grounded context and everything else
  is unaffected.
  - **Free option:** a Gemini key from [AI Studio](https://aistudio.google.com/apikey)
    with `LLM_PROVIDER=gemini`. Leave `LLM_MODEL` empty; a model belonging to another
    provider is ignored rather than sent, so switching provider cannot 404.
  - The free tier allows about **20 requests per day per model** — verified from the
    quota metadata, not the docs, which do not state it. Daily insights are cached per
    site and date so browsing does not consume it, but the chat assistant will exhaust
    it quickly. The quota is per model, so a different Gemini model has its own
    allowance.
  - `gemini-2.5-flash` is retired for new keys and returns 404; the default is
    `gemini-3.5-flash`.
- **Tariff** — flat or time-of-use. Configuration, so every cost is an estimate.
- **Carbon** — grid emission factor, with per-country overrides.
- **Solar / battery / EV** — all off by default. Enabling them turns on interfaces and
  optimisation logic, not readings. `ALLOW_SIMULATION=true` additionally permits a
  modelled clear-sky profile, tagged `simulated` wherever it appears.

---

## The AI assistant

The user's question is **never** sent to a model on its own. The platform first
assembles a structured snapshot — consumption, appliance analysis, anomalies, weather,
forecast, tariff, renewables, optimisation, carbon, score, recommendations, and an
explicit list of what the data cannot support — and the assistant answers only from it.

That snapshot is viewable in the UI ("Show the data it sees") and at
`GET /api/assistant/context`, so any answer can be checked against the numbers it was
given.

The system prompt forbids inventing figures, requires distinguishing measured from
estimated from predicted, forbids presenting an unreliable classifier's score as a
verdict, and forbids recommending that a critical load be shed.

---

## API

`GET /docs` for the full interactive reference.

```
GET  /api/health                                  liveness + what is and isn't available
GET  /api/demo                                    the populated opening state
GET  /api/houses                                  every site
GET  /api/houses/{id}                             one site + capabilities + dates
GET  /api/houses/{id}/appliances                  appliance intelligence for a day
GET  /api/houses/{id}/consumption                 series at any granularity
GET  /api/houses/{id}/profile                     load shape by hour, with tariff
GET  /api/houses/{id}/dashboard                   everything the dashboard needs
POST /api/analyze                                 analyse one appliance-day
GET  /api/appliances/{id}/{appliance}/analysis    full appliance detail
GET  /api/appliances/{id}/{appliance}/history     measured per-day history
GET  /api/appliances/{id}/{appliance}/model       model card: metrics + limitations
POST /api/appliances/replacement                  replacement analysis
GET  /api/anomalies/{id}                          flagged days, by anomaly type
GET  /api/score/{id}                              sustainability score + its arithmetic
GET  /api/models                                  the trained-model registry
GET  /api/weather                                 live conditions (server-side)
GET  /api/weather/recorded                        the weather the model actually used
GET  /api/forecast                                forecast + measured error
GET  /api/optimization        POST /api/optimization      schedule optimisation
GET  /api/demand-response                         load against the price curve
GET  /api/tariff                                  the configured tariff
GET  /api/renewable                               solar/battery/EV status + energy flow
POST /api/optimization/ev                         EV charge window
GET  /api/recommendations                         ranked, rule-derived advice
GET  /api/preferences/{id}    PUT /api/preferences        household constraints
GET  /api/carbon              GET /api/carbon/config      carbon intelligence
GET  /api/assistant/status    POST /api/assistant         the assistant
GET  /api/assistant/insight   GET /api/assistant/context  insight + its grounding
```

Failure is contained: a dead weather provider, an unconfigured LLM or a site with too
little history degrades to an `available: false` block with a reason. The dashboard
still renders everything else.

---

## Data notes

Read `PROJECT_AUDIT.md` for the full account. The findings that shaped the build:

1. **Timestamps are day-first** (`DD-MM-YYYY`). Month-first parsing silently corrupts
   the series.
2. **Five Hyderabad sites have power but no on/off state.** Every behavioural feature is
   computed over on-state rows, so those sites are ingested and shown but excluded from
   classification — flagged, not silently scored on zeros.
3. **`Singapore_2` is an industrial site** with 13 named sub-channels including nine
   environmental chambers. Chambers are classified **critical**: interrupting one
   invalidates the test inside it, so they are never proposed for shifting.
4. **Partial days are common** — truncated first/last days and mid-series gaps. They are
   excluded from forecasting and flagged in the UI rather than averaged in.
5. **`total_energy` in the notebook is a sum of watt samples, not kWh.** It is kept as a
   model feature; billing energy is computed separately as `Σ power_W × 0.5 / 1000`.

---

## Extending it

The architecture is built so the CSV ingestion layer can be replaced without touching
anything above it:

```
Smart meter → IoT → MQTT → real-time ingestion → the same intelligence layer
```

- **Real-time**: implement a new loader behind `data/loaders/`; services are unchanged.
- **Renewables**: implement `generation_profile()` and `battery_state()` in
  `renewable_service.py` against a real inverter or BMS feed. The optimiser already
  consumes them.
- **Multi-building**: `data/schema.py` models sites and channels separately, so an
  Organization → Building → Floor → Zone → Meter hierarchy slots above the site key.
- **Industrial**: `Singapore_2` already exercises the sub-metered, critical-load path.
  Energy-per-unit-of-production needs a production feed the dataset does not contain,
  and is documented as a future extension rather than mocked.
- **PostgreSQL**: all database access funnels through `backend/database/db.py` and uses
  no SQLite-only types.

---

## Deployment

The app ships as **one container**: the React bundle is built in a Node stage and served
by the same FastAPI process that serves the API. One origin, no CORS, one thing to keep
in sync.

```bash
docker build -t energy-intelligence .
docker run --rm -p 7860:7860 energy-intelligence   # http://localhost:7860
```

`$PORT` is honoured where a platform injects one and defaults to 7860 otherwise. The
image installs `libgomp1`, which xgboost needs and `python:3.11-slim` omits, and runs as
a non-root user.

### Sizing

| | |
|---|---|
| Installed dependencies | **~434 MB** (xgboost 140, scipy 119, pandas 71, numpy 58, scikit-learn 46) |
| Measured working set at runtime | **~181 MB** (ML libraries ~150 MB, the 22,084 readings ~10 MB) |

The dependency footprint is what matters for *packaging*, and it is over the 250 MB
serverless-function limit on Vercel and similar platforms — **this needs a container
host, not a serverless function.** The working set is what matters for *sizing*, and
181 MB fits comfortably on a 512 MB instance.

### Platforms

`render.yaml` and `railway.toml` are both included; each points its health check at
`/api/health`, so a failing build never replaces a working deploy.

- **Render** — free web-service tier (512 MB, 750 instance hours a month, Dockerfile
  deploys, no card). Connect the repo at
  [dashboard.render.com/blueprints](https://dashboard.render.com/blueprints) and the
  blueprint configures the service. Free instances sleep after 15 minutes of inactivity
  and take about a minute to wake.
- **Railway** — `railway up` once a plan is active. The free trial has ended, so a plan
  is required.
- **Hugging Face Spaces** — *not* an option on the free tier: only static Spaces are
  free, and Docker Spaces require PRO.

### Ephemeral storage

The SQLite database holds only user-created state — household preferences and assistant
conversations — and lives on the container filesystem, so it resets on redeploy. Meter
readings and model artefacts are baked into the image and are unaffected. Mount a volume
at `/app`, or point `DATABASE_URL` at Postgres, to make that state durable.

---

## What this is not

It is not a dashboard that shows electricity consumption. It is a system that
understands energy behaviour, detects abnormal consumption *after allowing for the
weather*, predicts demand with a stated error, explains what it found, and recommends
what to do — while being explicit, everywhere, about which of its numbers are measured
and which are not.
