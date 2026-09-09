# Progress — SkyGuard (SIH PS 26073)

Last updated: 2026-09-09 (I0: ML engine is production QC; docs locked).

Update this file when a slice lands or a lock changes. It is the handoff note for a new chat. Contracts and decisions still live in the other `docs/` files; this file only answers “where are we?”

## Needs from you (blocked without this)

I1 cannot start until these exist on disk (they are gitignored and were **not** in the `ml` branch pull):

| Path | Why |
|---|---|
| `ml/data/raw/stations.csv` | 151-station catalog ML trained on |
| `ml/data/raw/buddy_edges.csv` | buddy graph (Tier 3) |
| `ml/data/raw/{station_id}.csv` | hourly T/P/H to stream (or tell us another path) |

Copy them in and say so. Do not commit the huge CSVs.

Optional, not blocking: freeze a better LSTM threshold. Artifacts still use 2023 val window-MSE **p99 ≈ 0.00605**. `model_metadata.json` says `threshold_frozen: false`. LSTM-only 2024 F1 is weak on freeze/drift; that is why Tier 1 + buddy in `ml/engine.py` are the product, not a reason to delay I2.

Nothing else needs a product decision. Language and D14–D18 are locked.

## Status

**Shipped:** slices 0–7 (data + backend shell + legacy QC) and F0–F6 (one-page Streamlit). **`ml/` is in the tree** (engine, artifacts, reports). **Live ingest still uses backend tiers** until I2.

Working tree may include uncommitted eval scripts and this I0 docs set. Next code slice is **I1** (catalog import) once `data/raw` is present, then **I2** (adapter).

| Slice | Commit | Why |
|---|---|---|
| 0–7 | see git log | Data + backend + identity detector + demo overlay |
| F0–F6 | `5e01b23` | One-page ops console |
| I0 | (this docs change) | ML owns QC; 151 catalog; view vs ingest filter |
| I1–I6 | not started | Import catalog, adapter, stream filter, tests |
| F7+ | not started | Multi-page UI |

## What works today (pre-I2)

- Catalog on backend: **four** stations (NORTH/WEST). ML scalers include those four **and** 147 more.
- API: `/healthz`, `/stations`, `/telemetry`, `/alerts`, `POST /ingest`, seed, `/demo/*`. Verdicts from **legacy** `skyguard.engine.*`.
- Detector stub: `IdentityDetector`. `MODEL_PATH` unused.
- Streamer: clean hours, 4 stations.
- Dashboard: 4 markers, NORTH storm hero (will 400 after I3 until F7 switches to neighborhood).
- ML standalone: `ml/ml/engine.py` + `ml/ml/main.py` (own `/ingest` with `temp/rhum/pres` + window + buddies). Not wired to the product port.

## What must not be confused

| Piece | Role now | Role after I2 |
|---|---|---|
| `src/skyguard/engine/tier*.py` | live QC | **legacy**, do not call |
| `src/skyguard/ml/` | IdentityDetector | **legacy** |
| `ml/ml/engine.py` | unused by product | **production QC** |
| `ml/ml/main.py` | unused | standalone eval only |
| `frontend/` | live demo | keep until F7; then rewrite |

## Locks that bite implementers

- Fault math only in `skyguard.data.inject`. Live faults in the API demo overlay, **before** ML.
- Raw T/P/H immutable. Imputed = ML `predicted`.
- Buddy check = ML graph, **≥2** usable neighbors. Isolates → `UNCONFIRMED_ANOMALY`.
- Public fields `temp_c` / `pres_hpa` / `rhum_pct`. ML names stay inside `ml/`.
- View set ≠ ingest set. Filter Palam in the UI still streams Palam’s buddies.
- Storm inject = neighborhood, not `cluster_id: NORTH`.
- Do not invent API fields. `contracts.md` is the integration contract (updated in I0).
- Do not `git pull` ML into `src/`. `ml/` is a sibling of `frontend/`.

## How to run (today, pre-I1)

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

1. **You:** drop `ml/data/raw/` files.
2. **I1** — import catalog + edges + parquet.
3. **I2** — adapter; live `/ingest` calls `process_aws_data`.
4. **I3** — stream `--stations` / `--with-buddies`; neighborhood inject.
5. **I4** — `GET /stations?ids=` + `latest`; stream-filter routes.
6. **I5** — tests; **I6** README.
7. **F7+** — multi-page UI, station-wise stream + prediction.

Do not start F7 in the same turn as I2.

## Open issues

- `ml/data/` missing in this clone.
- Real Meteostat parquet for the old 4 stations may still be absent; after I1 we prefer ML CSVs.
- LSTM threshold not frozen; freeze/drift are Tier 1 / window heuristics in ML, not the autoencoder.
- Nested path `ml/ml/` is awkward; do not flatten during I-slices unless a later cleanup slice says so.
- `docs/backend-simulator-summary.md` describes the **legacy** backend QC. Trust this file + `architecture.md` for the live path.
