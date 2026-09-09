# Progress — SkyGuard (SIH PS 26073)

Last updated: 2026-09-09 (F10: Alerts + Control. Next is F11).

Update this file when a slice lands or a lock changes. It is the handoff note for a new chat. Contracts and decisions still live in the other `docs/` files; this file only answers “where are we?”

## Needs from you (blocked without this)

Nothing product-blocking. `ml/data/raw/` is on disk (gitignored). Do not commit those CSVs.

Optional, not blocking: freeze a better LSTM threshold. Artifacts still use 2023 val window-MSE **p99 ≈ 0.00605**. `model_metadata.json` says `threshold_frozen: false`. LSTM-only 2024 F1 is weak on freeze/drift; that is why Tier 1 + buddy in `ml/engine.py` are the product.

Nothing else needs a product decision. Language and D14–D18 are locked.

## Status

**Shipped:** slices 0–7, F0–F6, I0 docs, **I1 catalog import**, **I2 adapter**, **I3 stream filter + neighborhood inject**, **I4 query APIs**, **I5 live-path tests**, **I6 README**. Live ingest uses **`ml.engine`**. Processed catalog is **151 stations**. Palam `42181` buddies: Safdarjung `42182` + `42139`. Storm inject is Palam’s neighborhood, not NORTH.

Next: **F11** Guide page, empty/offline polish, judge script.

| Slice | Commit | Why |
|---|---|---|
| 0–7 | see git log | Data + backend + identity detector + demo overlay |
| F0–F6 | `5e01b23` | One-page ops console |
| I0 | (docs in tree) | ML owns QC; 151 catalog; view vs ingest filter |
| I1 | (this change) | Import ML catalog/edges/hours; 151-station JSON |
| I2 | `bdd0a38` | Adapter; live `/ingest` → `process_aws_data` |
| I3 | `a76db0d` | Stream ingest set; neighborhood inject; reject cluster |
| I4 | `41d936e` | `ids=` + `latest` + `/buddy-map` + telemetry/alert `label` |
| I5 | `62df838` | D18 + two-buddy T3 + isolate unconfirmed + health; quarantine IdentityDetector live path |
| I6 | (this change) | Root README: import catalog, filtered stream, neighborhood inject, old dashboard |
| F7 | `1dc9dcd` | Lock five-page light console; no app code |
| F8 | `6751edd` | st.navigation, light theme, view-set map |
| F9 | `99c0729` | Station overlay charts + verdict + contribution |
| F10 | (this change) | Alerts feed + Palam storm/spike Control |

## What works today (post-I6)

- Catalog: `data/processed/stations.json` (151) + `buddy_edges.json` (388 edges, 24 isolates). Hourly parquet for all 151 ids. Re-run with `python -m skyguard.data.import_ml_catalog`.
- API: `/healthz` reports `model_loaded`, `threshold`, `n_stations`, `n_isolates`. `GET /stations?ids=` includes `latest`, `buddy_ids`, `isolate`. `GET /buddy-map`. Telemetry and alerts store `label`. `/ingest`, seed, `/demo/*`.
- Live QC: `engine/adapter.py` maps public fields ↔ ML; `pipeline.py` persists raw, calls `process_aws_data`, writes overlay/alert/health. Legacy `skyguard.engine.tier*` is not on this path.
- Missing artifacts → persist anyway, `UNCONFIRMED_ANOMALY`. No 24h window → same.
- Streamer: `--stations 42181 --with-buddies` (default true) seeds/POSTs the ingest set. CLI overrides `GET /demo/stream-filter`. Empty filter = full catalog.
- Demo inject: `target=neighborhood` expands via the buddy graph. `target=cluster` is 400.
- Dashboard: Network, Station, **Alerts**, **Control**. Guide still F11. Hero: Storm around Palam / Break Palam temperature / Reset.
- ML standalone: `ml/ml/main.py` remains eval-only. Do not point the dashboard at 8001.
- Tests: D18 mapping is unit-tested; live ingest covers two-buddy T3, isolate/one-buddy → `UNCONFIRMED_ANOMALY`, weather does not lower health. IdentityDetector / NORTH live-path tests are skipped. Engine integration skips when artifacts are missing.

## What must not be confused

| Piece                          | Role now                | Role after I4+              |
| ------------------------------ | ----------------------- | ---------------------------- |
| `src/skyguard/engine/tier*.py` | **legacy**, do not call | unused on live ingest        |
| `src/skyguard/ml/`             | IdentityDetector stub   | **legacy**                   |
| `ml/ml/engine.py`              | **production QC**       | unchanged                     |
| `ml/ml/main.py`                | standalone eval only    | unchanged                     |
| `frontend/`                    | four live pages         | F11 Guide + polish          |

## Locks that bite implementers

- Fault math only in `skyguard.data.inject`. Live faults in the API demo overlay, **before** ML.
- Raw T/P/H immutable. Imputed = ML `predicted`.
- Buddy check = ML graph, **≥2** usable neighbors. Isolates → `UNCONFIRMED_ANOMALY`.
- Public fields `temp_c` / `pres_hpa` / `rhum_pct`. ML names stay inside `ml/`.
- View set ≠ ingest set. Filter Palam in the UI still streams Palam’s buddies.
- Storm inject = neighborhood, not `cluster_id: NORTH`. Palam neighborhood = `42181` + `42182` + `42139`.
- Do not invent API fields. `contracts.md` is the integration contract (updated in I0).
- Do not `git pull` ML into `src/`. `ml/` is a sibling of `frontend/`.

## How to run (today)

See the [root README](../README.md) (import catalog, API, filtered stream, inject, dashboard). Short form:

```text
python scripts/run_api.py
python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 --start 2024-07-01T00:00:00Z --stations 42181 --with-buddies
python scripts/run_dashboard.py
```

Streaming all 151 without a filter will overwhelm the console. Prefer Palam’s neighborhood (or `POST /demo/stream-filter`). Default F7 view is Palam∪buddies + Santacruz.

ML-only smoke (optional):

```text
# from repo root, PYTHONPATH including ml/
uvicorn ml.ml.main:app --port 8001
```

Do not point the dashboard at 8001 (field names differ).

Tests: `pytest -q`. UI extras: `pip install -e ".[ui]"`. ML runtime needs `torch` (see `ml/ml/requirements.txt`).

## Next

1. **F11** — Guide, empty/offline, 151 copy, polish.

## Open issues

- LSTM threshold not frozen; freeze/drift are Tier 1 / window heuristics in ML, not the autoencoder.
- Nested path `ml/ml/` is awkward; do not flatten during I-slices unless a later cleanup slice says so.
- `docs/backend-simulator-summary.md` describes the **legacy** backend QC. Trust this file + `architecture.md` for the live path.
- Without a 24h window, ingest is `UNCONFIRMED_ANOMALY` (LSTM cannot run). Seed before streaming.
- Streaming all 151 will overwhelm the console; use `--stations` / stream-filter.
