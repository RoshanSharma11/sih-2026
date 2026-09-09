# Progress — SkyGuard (SIH PS 26073)

Last updated: 2026-09-09 (I1 catalog written: 151 stations / 24 isolates / 388 buddy edges. Next is I3).

Update this file when a slice lands or a lock changes. It is the handoff note for a new chat. Contracts and decisions still live in the other `docs/` files; this file only answers “where are we?”

## Needs from you (blocked without this)

Nothing product-blocking. `ml/data/raw/` is on disk (gitignored). Do not commit those CSVs.

Optional, not blocking: freeze a better LSTM threshold. Artifacts still use 2023 val window-MSE **p99 ≈ 0.00605**. `model_metadata.json` says `threshold_frozen: false`. LSTM-only 2024 F1 is weak on freeze/drift; that is why Tier 1 + buddy in `ml/engine.py` are the product.

Nothing else needs a product decision. Language and D14–D18 are locked.

## Status

**Shipped:** slices 0–7, F0–F6, I0 docs, **I1 catalog import**, **I2 adapter**. Live ingest uses **`ml.engine`**. Processed catalog is **151 stations** (scaler ids match 1:1). Palam `42181` buddies: Safdarjung `42182` + `42139`. SQLite was wiped after import so boot picks up `isolate` + `station_buddies`.

Next: **I3** stream filter + neighborhood inject.

| Slice | Commit | Why |
|---|---|---|
| 0–7 | see git log | Data + backend + identity detector + demo overlay |
| F0–F6 | `5e01b23` | One-page ops console |
| I0 | (docs in tree) | ML owns QC; 151 catalog; view vs ingest filter |
| I1 | (this change) | Import ML catalog/edges/hours; 151-station JSON |
| I2 | `bdd0a38` | Adapter; live `/ingest` → `process_aws_data` |
| I3–I6 | not started | Stream filter, query APIs, tests, README |
| F7+ | not started | Multi-page UI |

## What works today (post-I1 catalog write)

- Catalog: `data/processed/stations.json` (151) + `buddy_edges.json` (388 edges, 24 isolates). Hourly parquet for all 151 ids. Re-run with `python -m skyguard.data.import_ml_catalog`.
- API: `/healthz` reports `model_loaded`, `threshold`, `n_stations`, `n_isolates`. `/stations`, `/telemetry`, `/alerts`, `POST /ingest`, seed, `/demo/*`.
- Live QC: `engine/adapter.py` maps public fields ↔ ML; `pipeline.py` persists raw, calls `process_aws_data`, writes overlay/alert/health. Legacy `skyguard.engine.tier*` is not on this path.
- Missing artifacts → persist anyway, `UNCONFIRMED_ANOMALY`. No 24h window → same.
- Streamer: still streams whatever is in `stations.json` (now 151) unless you pass a filter. I3 adds `--stations` / `--with-buddies`.
- Dashboard: F0–F6 one-page console. Storm hero is still `cluster_id: NORTH` (will 400 after I3 until F7 switches to Palam neighborhood).
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
- Storm inject = neighborhood, not `cluster_id: NORTH` (I3). Palam neighborhood = `42181` + `42182` + `42139`.
- Do not invent API fields. `contracts.md` is the integration contract (updated in I0).
- Do not `git pull` ML into `src/`. `ml/` is a sibling of `frontend/`.

## How to run (today)

See the [root README](../README.md). Short form:

```text
python scripts/run_api.py
python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 --start 2024-07-01T00:00:00Z
python scripts/run_dashboard.py
```

Until I3, the streamer will POST all 151 stations. That is heavy for the old dashboard; prefer waiting for `--stations 42181 --with-buddies` or only demo Palam’s neighborhood by hand.

ML-only smoke (optional):

```text
# from repo root, PYTHONPATH including ml/
uvicorn ml.ml.main:app --port 8001
```

Do not point the dashboard at 8001 (field names differ).

Tests: `pytest -q`. UI extras: `pip install -e ".[ui]"`. ML runtime needs `torch` (see `ml/ml/requirements.txt`).

## Next

1. **I3** — stream `--stations` / `--with-buddies`; neighborhood inject (reject `target=cluster`).
2. **I4** — `GET /stations?ids=` + `latest`; stream-filter routes.
3. **I5** — tests; **I6** README.
4. **F7+** — multi-page UI, station-wise stream + prediction.

Do not start F7 in the same turn as I3.

## Open issues

- LSTM threshold not frozen; freeze/drift are Tier 1 / window heuristics in ML, not the autoencoder.
- Nested path `ml/ml/` is awkward; do not flatten during I-slices unless a later cleanup slice says so.
- `docs/backend-simulator-summary.md` describes the **legacy** backend QC. Trust this file + `architecture.md` for the live path.
- Without a 24h window, ingest is `UNCONFIRMED_ANOMALY` (LSTM cannot run). Seed before streaming.
- Streaming all 151 without I3 will overwhelm the F0–F6 console.
