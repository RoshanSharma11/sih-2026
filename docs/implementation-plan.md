# Implementation Plan — Integration (ML QC + catalog + filter)

Historical slices 0–7 and F0–F6 are **shipped**. Do not re-run them. This file is the build order from the ML drop onward.

### What we are building

Wire the pulled `ml/` engine as **production QC**, import its 151-station catalog and buddy graph into simulator + backend, and add a station-wise **view** filter whose **ingest** set always includes 1-hop neighbors. Backend becomes persist + demo + adapter. Frontend rewrite (multi-page) starts only after that path is green.

### Language we agreed on

See [context.md](context.md). Short form:

- **Production QC** — `ml/ml/engine.py` only
- **Backend** — product shell (SQLite, demo, query, adapter)
- **View set vs ingest set** — UI filter vs streamer POSTs (view ∪ buddies)
- **Neighborhood** — station + 1-hop ML buddies (storm target)
- **Label** — five-way ML; `pipeline_status` is the four-way map (D18)

### Decisions made

See [decisions.md](decisions.md). Highest impact: D14 catalog = ML 151, D15 station filter, D16 in-process ML, D3 storm = neighborhood, D11 needs two buddies.

### Assumptions

- You will drop ML `data/raw/` (`stations.csv`, `buddy_edges.csv`, hourly CSVs) into `ml/data/raw/` (gitignored; not in the pull). **Done.** Catalog JSON is written.
- LSTM operating threshold stays val window-MSE p99 (`0.00605`) until ML freezes another value. Metadata says it is not frozen; we still ship with p99.
- One product port. No Docker, auth, SSE, SHAP on ingest.
- Current Streamlit page keeps working on a small view set via `pipeline_status` until F7.

### How to build it

**Commit after every slice** (`AGENTS.md`). Do not start the multi-page frontend before I5.

#### I0 — lock docs (this change)

1. `context.md`, `decisions.md`, `architecture.md`, `contracts.md`, `backend.md`, `data-simulator.md`, `frontend.md`, `progress.md`, this file
2. Ownership: QC → ML; backend shell; simulator catalog = ML
3. No application code

#### I1 — import ML catalog

1. Document expected files: `ml/data/raw/stations.csv`, `buddy_edges.csv`, `{station_id}.csv`
2. `skyguard.data.import_ml_catalog` → `data/processed/stations.json` + `buddy_edges.json`
3. Map hours to parquet with public column names
4. Upsert catalog + `station_buddies` on API boot
5. Tests: scaler ids ⊂ catalog (fixture covering all scalers); Palam/Safdarjung/Santacruz/Colaba present; isolates have &lt;2 buddies

**Code is in.** `data/processed/stations.json` is 151 stations (scaler ids match). `buddy_edges.json` has 388 edges / 24 isolates. Hourly parquet written for every catalog id. Wipe `data/skyguard.db` after a real import (done). Palam `42181` has two exported buddies (`42182`, `42139`).

#### I2 — adapter + live ingest uses ML

1. `engine/adapter.py`: field map, window, buddies
2. `pipeline.py`: persist → adapter → `process_aws_data` → persist overlay/alert/health
3. Stop calling `tier1` / `tier2` / `tier3` / `classify` / legacy `health.recompute`
4. `GET /healthz` includes `model_loaded`, `threshold`, `n_stations`, `n_isolates`
5. Integration test: Palam spike vs neighborhood storm using real artifacts (CPU)

**Code is in.** Live `/ingest` maps through `engine/adapter.py` and calls `DetectionEngine.process_aws_data`. Legacy backend tiers are not imported on that path. `/healthz` reports `model_loaded` / `threshold` / `n_stations` / `n_isolates`. Integration tests cover Palam spike vs a coordinated neighborhood move (skip if artifacts missing).

#### I3 — streamer filter + neighborhood inject

1. Streamer `--stations` / `--with-buddies`; also honor `GET /demo/stream-filter`
2. Seed and POST only the ingest set
3. `POST /demo/inject` `target=neighborhood`; reject `target=cluster`
4. DemoController expands via buddy graph

**Code is in.** CLI `--stations` expands 1-hop buddies (default) and overrides `GET /demo/stream-filter`. `POST /demo/inject` arms a neighborhood; `target=cluster` is 400. F0–F6 hero is Palam neighborhood.

#### I4 — query APIs for 151 + view set

1. `GET /stations?ids=`
2. `latest` on each station summary (no N+1)
3. `GET /buddy-map`
4. `POST/GET /demo/stream-filter` — **done in I3**
5. `telemetry_logs.label`; alerts store `label`
6. Drop required `cluster_id`

**Code is in.** `GET /stations?ids=` returns the view set with `latest` loaded in one query. `GET /buddy-map` exposes the ML graph. Telemetry and alerts persist `label`. `cluster_id` is optional. F0–F6 client reads `latest` from the list (no N+1).

#### I5 — replace live-path tests

1. New tests for D18 mapping, two-buddy T3, isolate → unconfirmed, health ignores weather
2. Skip or quarantine tests that require IdentityDetector + NORTH cluster as the live path
3. `pytest -q` green with artifacts present; CI without artifacts: adapter unit tests + skip engine integration

#### I6 — handoff README

1. Root README: import catalog, run API, stream filtered, inject neighborhood, open old dashboard
2. Progress: I1–I5 done; next is F7

---

## Frontend slices (after I5)

#### F7 — lock multi-page docs

`frontend.md` rewrite: pages, station filter, predicted overlay. No app code until the page list is in that file.

#### F8 — station filter + map

View-set picker, `POST /demo/stream-filter`, map from `GET /stations?ids=`, marker color from `latest.label` or `pipeline_status`.

#### F9 — stream + prediction

Selected stations only: observed + imputed/predicted T/P/H.

#### F10 — alerts, health, neighborhood inject

Verdict from `/alerts`. Hero: storm around Palam, Palam spike, reset.

#### F11 — polish / judge script

Empty/offline, 1 s poll, 151-station scalability copy.

### Parallelism

```
I0 docs
  → I1 catalog import   (needs your data/raw)
  → I2 ML adapter on ingest
       → I3 stream filter + neighborhood inject
       → I4 query APIs
            \
             I5 tests → I6 README → F7…
```

I3 and I4 can overlap after I2.

### Definition of done for integration

- Live `/ingest` verdicts come from `ml.engine`, not backend tiers
- Catalog/buddy graph match ML
- View Palam only → ingest Palam ∪ buddies; UI charts Palam only
- Neighborhood storm ≠ single-station spike
- Raw T/P/H never overwritten
- Old dashboard may look dated; it must not 500

### Definition of done for the next dashboard (later)

- Judge filters to a handful of stations and sees stream + prediction
- Map does not poll 151 detail endpoints
- Weather amber, hardware red, unconfirmed slate
