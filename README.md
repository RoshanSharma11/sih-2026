# SkyGuard AI (SIH PS 26073)

Quality-control service for Indian Automatic Weather Stations. Input is hourly **T / P / H only**. The API tells a real storm from a broken sensor, keeps raw readings intact, and tracks 7-day sensor health.

**Handoff (2026-09-09):** I1–I6 and **F7–F11** are shipped. Live `/ingest` calls `ml/ml/engine.py` in-process. Catalog is **151 stations**. Dashboard is the five-page light Streamlit console. Status: [docs/progress.md](docs/progress.md). Contracts: [docs/contracts.md](docs/contracts.md).

This repo is the **data engine + FastAPI product shell + ML QC package + Streamlit console**. Do not point the dashboard at the ML eval server on port 8001.

Demo neighborhood (storm hero): Palam `42181` + Safdarjung `42182` + Meerut `42139`. Buddy check uses that graph, not NORTH/WEST. Delhi does not validate Mumbai.

## Setup

Python 3.10+. From the repo root:

```text
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ui]"
pip install -r ml/ml/requirements.txt
```

Torch is required for live LSTM. Weights load from `ml/ml/artifacts/` on API boot. Do not set `MODEL_PATH`. If artifacts fail to load, ingest still persists and returns `UNCONFIRMED_ANOMALY` — it does not fall back to legacy backend tiers.

## Import the ML catalog

Do **not** recrawl Meteostat to pick stations. Copy ML `stations.csv`, `buddy_edges.csv`, and hourly `{station_id}.csv` into `ml/data/raw/` (gitignored), then:

```text
python -m skyguard.data.import_ml_catalog
```

Writes `data/processed/stations.json` (151) and `buddy_edges.json`. Hourly parquet is written for every catalog id that has a CSV. Wipe `data/skyguard.db` after a real re-import so SQLite matches the new graph.

The processed catalog is already in tree. Re-run import only when ML raw files change.

## Run the API, a filtered stream, and the dashboard

Three terminals. Prefer Palam’s neighborhood — streaming all 151 will overwhelm the live map. Default dashboard view is Palam ∪ buddies + Santacruz.

```text
python scripts/run_api.py
```

Wait for `Application startup complete`. Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) · `GET /healthz` should show `model_loaded: true`, `n_stations: 151`.

```text
python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 --start 2024-07-01T00:00:00Z --stations 42181 --with-buddies
```

Seeds 24 clean hours for the **ingest set** (view ∪ 1-hop buddies), then POSTs one weather-hour per 200 ms. `--hours N` stops after N hours. There is **no** `--fault` flag. `409` duplicates are skipped. CLI `--stations` overrides `GET /demo/stream-filter`. Seed before streaming: without a 24h window, LSTM cannot run and the hour is `UNCONFIRMED_ANOMALY`.

```text
python scripts/run_dashboard.py
```

[http://127.0.0.1:8501](http://127.0.0.1:8501) · `SKYGUARD_API` defaults to `http://127.0.0.1:8000`. Pages: Network, Station, Alerts, Control, How QC works. Light theme. Polls the product API only.

Tests: `pytest -q`. Engine integration skips when artifacts are missing; adapter unit tests still run.

## Demo inject (storm ≠ broken sensor)

While the stream is running:

```text
curl -X POST http://127.0.0.1:8000/demo/inject \
  -H 'Content-Type: application/json' \
  -d '{"target":"neighborhood","station_id":"42181","kind":"GENUINE_WEATHER"}'

curl -X POST http://127.0.0.1:8000/demo/inject \
  -H 'Content-Type: application/json' \
  -d '{"target":"station","station_id":"42181","kind":"SPIKE","channel":"temp_c"}'
```

- Storm must target a **neighborhood** (station + 1-hop buddies). Hardware (spike / freeze / drift / comm) must target **one station**.
- Legacy `target: cluster` is **400**.
- `GET /demo/status` lists armed overlays. `POST /demo/reset` clears them.
- `demo_injected` on `POST /ingest` is the overlay kind. It is not ground truth for judges.

Expect different `label`s: neighborhood storm → `GENUINE_WEATHER_EVENT` (mapped `pipeline_status=GENUINE_WEATHER`), lone Palam spike → `HARDWARE_ANOMALY` or `PHYSICAL_FAULT` (`HARDWARE`). The first station in a storm hour may be `UNCONFIRMED_ANOMALY` until two same-hour neighbors exist.

## 30-second judge script

1. Stream Palam’s neighborhood. Map markers for that view set stay teal while clean.
2. **Storm around Palam** → Palam and its buddies go amber; a Mumbai station you did not ingest stays idle. Neighbors agree. Health does not drop.
3. **Reset**, then **Break Palam temperature** → only Palam goes red; Safdarjung stays teal.
4. Point at the map: Delhi does not validate Mumbai.

The first station in a storm hour may show `UNKNOWN` / `UNCONFIRMED_ANOMALY` until the neighbor lands (~1 s). Weather is amber, never red.

Poll shapes are frozen in [docs/contracts.md](docs/contracts.md). No SSE. Do not invent fields.


| Method       | Path                                        | Use                                                               |
| ------------ | ------------------------------------------- | ----------------------------------------------------------------- |
| `GET`        | `/healthz`                                  | `ok`, `model_loaded`, `threshold`, `n_stations`, `n_isolates`     |
| `GET`        | `/stations?ids=`                            | view-set summaries with `latest`, `buddy_ids`, `isolate` (no N+1) |
| `GET`        | `/stations/{id}`                            | summary + `latest`                                                |
| `GET`        | `/stations/{id}/telemetry?from=&to=&limit=` | observed + imputed. `is_anomaly` follows D18 (true for weather)   |
| `GET`        | `/alerts?station_id=&limit=`                | newest first — verdict sentence + `label`                         |
| `GET`        | `/buddy-map`                                | ML graph for the dashboard                                        |
| `GET`        | `/demo/status`                              | armed overlays                                                    |
| `GET`/`POST` | `/demo/stream-filter`                       | view vs ingest sets                                               |


`GENUINE_WEATHER_EVENT` is an anomaly alert and **does not** lower health. Raw `temp_observed` / `pres_observed` / `rhum_observed` are immutable; imputed columns are ML `predicted` overlays.

## ML

Production QC is `ml/ml/engine.py`, called in-process from the backend adapter. Do not train unless asked. Do not HTTP-proxy to `ml.ml.main:app` in the judge demo.

Optional standalone eval (different field names — not for the dashboard):

```text
uvicorn ml.ml.main:app --port 8001
```

Offline labeled eval (do **not** train on it):

```text
python scripts/simulate_corruption_eval.py --clean test_2024.csv --out ./eval_out
```

`src/skyguard/ml/` (`IdentityDetector`) and `src/skyguard/engine/tier*.py` are **legacy**. Live ingest does not call them.

## Docs

Read [docs/README.md](docs/README.md) before changing behavior. If code and contracts disagree, update `docs/contracts.md` in the same change.