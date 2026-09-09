# Progress — SkyGuard (SIH PS 26073)

Last updated: 2026-09-09 (I2: live `/ingest` calls `ml.engine.process_aws_data`; 151-station lock still needs `ml/data/raw/`).

Update this file when a slice lands or a lock changes. It is the handoff note for a new chat. Contracts and decisions still live in the other `docs/` files; this file only answers “where are we?”

## Needs from you (blocked without this)

I1 catalog write is still blocked until these exist on disk (they are gitignored and were **not** in the `ml` branch pull):

| Path                           | Why                                              |
| ------------------------------ | ------------------------------------------------ |
| `ml/data/raw/stations.csv`     | 151-station catalog ML trained on                |
| `ml/data/raw/buddy_edges.csv`  | buddy graph (Tier 3)                             |
| `ml/data/raw/{station_id}.csv` | hourly T/P/H to stream (or tell us another path) |

Copy them in and say so. Do not commit the huge CSVs.

Optional, not blocking: freeze a better LSTM threshold. Artifacts still use 2023 val window-MSE **p99 ≈ 0.00605**. `model_metadata.json` says `threshold_frozen: false`. LSTM-only 2024 F1 is weak on freeze/drift; that is why Tier 1 + buddy in `ml/engine.py` are the product, not a reason to delay I3.

Nothing else needs a product decision. Language and D14–D18 are locked.

## Status

**Shipped:** slices 0–7, F0–F6, I0 docs, I1 importer, **I2 adapter**. `ml/` is in the tree. Live ingest uses **`ml.engine`** (in-process). Committed catalog is still the 4-station demo until you drop `ml/data/raw/` and run the importer.

Next: your CSV dump → `python -m skyguard.data.import_ml_catalog` → wipe `data/skyguard.db` → **I3** stream filter + neighborhood inject.

| Slice | Commit | Why |
|---|---|---|
| 0–7 | see git log | Data + backend + identity detector + demo overlay |
| F0–F6 | `5e01b23` | One-page ops console |
| I0 | (docs in tree) | ML owns QC; 151 catalog; view vs ingest filter |
| I1 | (in tree) | Import ML catalog/edges/hours; upsert `station_buddies` |
| I2 | (this change) | Adapter; live `/ingest` → `process_aws_data` |
| I3–I6 | not started | Stream filter, query APIs, tests, README |
| F7+ | not started | Multi-page UI |

## What works today (post-I2)

- Catalog importer: `python -m skyguard.data.import_ml_catalog` (needs `ml/data/raw/`; CLI lists missing files). Four-station `stations.json` still what the API boots until that import is run.
- API: `/healthz` reports `model_loaded`, `threshold`, `n_stations`, `n_isolates`. `/stations`, `/telemetry`, `/alerts`, `POST /ingest`, seed, `/demo/*`.
- Live QC: `engine/adapter.py` maps public fields ↔ ML; `pipeline.py` persists raw, calls `process_aws_data`, writes overlay/alert/health. Legacy `skyguard.engine.tier*` is not on this path.
- Detector stub: `IdentityDetector` unused on ingest. Missing artifacts → persist anyway, `UNCONFIRMED_ANOMALY`.
- Streamer: clean hours, 4 stations. Storm inject is still `cluster_id: NORTH` until I3.
- Dashboard: 4 markers, NORTH storm hero (will 400 after I3 until F7 switches to neighborhood).
- ML standalone: `ml/ml/main.py` remains eval-only. Do not point the dashboard at 8001.

## What must not be confused

| Piece                          | Role now                | Role after I3+              |
| ------------------------------ | ----------------------- | ---------------------------- |
| `src/skyguard/engine/tier*.py` | **legacy**, do not call | unused on live ingest        |
| `src/skyguard/ml/`             | IdentityDetector stub   | **legacy**                   |
| `ml/ml/engine.py`              | **production QC**       | unchanged                     |
| `ml/ml/main.py`                | standalone eval only    | unchanged                     |
| `frontend/`                    | live demo               | keep until F7; then rewrite |

## Locks that bite implementers

- Fault math only in `skyguard.data.inject`. Live faults in the API demo overlay, **before** ML.
- Raw T/P/H immutable. Imputed = ML `predicted`.
- Buddy check = ML graph, **≥2** usable neighbors. Isolates → `UNCONFIRMED_ANOMALY`.
- Public fields `temp_c` / `pres_hpa` / `rhum_pct`. ML names stay inside `ml/`.
- View set ≠ ingest set. Filter Palam in the UI still streams Palam’s buddies.
- Storm inject = neighborhood, not `cluster_id: NORTH` (I3).
- Do not invent API fields. `contracts.md` is the integration contract (updated in I0).
- Do not `git pull` ML into `src/`. `ml/` is a sibling of `frontend/`.

## How to run (today)

See the [root README](../README.md). Short form still:

```text
python scripts/run_api.py
python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 --start 2024-07-01T00:00:00Z
python scripts/run_dashboard.py
```

ML-only smoke (optional, needs `ml/data/raw` for a real window):

```text
# from repo root, PYTHONPATH including ml/
uvicorn ml.ml.main:app --port 8001
```

Do not point the dashboard at 8001 (field names differ).

Tests: `pytest -q`. UI extras: `pip install -e ".[ui]"`. ML runtime needs `torch` (see `ml/ml/requirements.txt`).

## Next

1. **You:** drop `ml/data/raw/` (`stations.csv`, `buddy_edges.csv`, hourly CSVs).
2. Run `python -m skyguard.data.import_ml_catalog` then delete `data/skyguard.db` so SQLite picks up `isolate` + `station_buddies`.
3. **I3** — stream `--stations` / `--with-buddies`; neighborhood inject.
4. **I4** — `GET /stations?ids=` + `latest`; stream-filter routes.
5. **I5** — tests; **I6** README.
6. **F7+** — multi-page UI, station-wise stream + prediction.

Do not start F7 in the same turn as I3.

## Open issues

- `ml/data/` missing in this clone.
- Real Meteostat parquet for the old 4 stations may still be absent; after I1 we prefer ML CSVs.
- LSTM threshold not frozen; freeze/drift are Tier 1 / window heuristics in ML, not the autoencoder.
- Nested path `ml/ml/` is awkward; do not flatten during I-slices unless a later cleanup slice says so.
- `docs/backend-simulator-summary.md` describes the **legacy** backend QC. Trust this file + `architecture.md` for the live path.
- Without a 24h window, ingest is `UNCONFIRMED_ANOMALY` (LSTM cannot run). Seed before streaming.
