# Progress — SkyGuard (SIH PS 26073)

Last updated: 2026-09-27 (v2 live plan step 5: replay).

**Next session:** implement [`v2-live-plan.md`](v2-live-plan.md) from step 6 (TIMING proxy). Do not extend the Palam / `ml/` path. Credentials are in `.env` only.

Update this file when a slice lands or a lock changes. It is the handoff note for a new chat. Contracts and decisions still live in the other `docs/` files; this file only answers “where are we?”

## Needs from you (blocked without this)

Nothing product-blocking. `ml/data/raw/` is on disk (gitignored). Do not commit those CSVs.

Optional, not blocking: the frozen v1 threshold note in `ml/` is not the live score. Product ingest uses the v2 threshold (`0.008487`).

Nothing else needs a product decision. Language and D14–D22 are locked. D19 is the live 48. D20 is the IMD poller. D21 is warm-up: null label until 24 hours, then the real v2 label. D22 is replay on the same ingest path.

## Status

**Shipped:** slices 0–7, F0–F6, I0 docs, **I1 catalog import**, **I2 adapter**, **I3 stream filter + neighborhood inject**, **I4 query APIs**, **I5 live-path tests**, **I6 README**, **V2-1** ingest on `v2.engine`, **V2-2** live catalog is the 48, **V2-3** IMD poller, **V2-4** warm-up, **V2-5** replay. Palam `42181` is not in the product catalog. Safdarjung `42182` is an isolate inside the 48. Storm inject still uses whatever neighborhood the catalog has.

Next: v2 live plan step 6 (TIMING proxy). No further frontend slices in this step.

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
| F10 | `dc57291` | Alerts feed + Palam storm/spike Control |
| F11 | (this change) | Guide, empty/offline, light polish |
| V2-1 | `3ad694d` | Ingest calls v2 (CW-IDW, TIMING queued); persist overlay fields; health from stored labels; no scaler is 400 |
| V2-2 | `22ee5c7` | Product catalog is the judge 48, with `aws_id` and in-set buddies; `/healthz` reports v2 weights |
| V2-3 | `48b9be0` | IMD poller posts matched hours through ingest; `/healthz` records poll status |
| V2-4 | `49ad285` | Fewer than 24 hours returns the raw hour and `warming_up`; the 24th hour returns the v2 label |
| V2-5 | `0ee8d6b` | Replay `demo_windows.json` through ingest so the Mumbai stories mutate before QC and a newer live window stays put |

## What works today (post-I6)

- Catalog: `data/processed/stations.json` (48) + `buddy_edges.json` (edges inside that set). Each station has `aws_id`, `aws_name`, `aws_distance_km`. Re-run with `python -m skyguard.data.import_ml_catalog`. `--legacy-151` is the old training dump.
- API: `/healthz` reports `model_loaded`, `threshold` (`0.008487` when v2 weights load), `n_stations`, `n_isolates`, `v2_artifacts` (`lstm`, `overlay`, `stgnn`), and `imd` (`last_success`, `last_error`, `matched`). `GET /stations?ids=` includes `latest`, `buddy_ids`, `isolate`, `aws_id`. `GET /buddy-map`. Telemetry and alerts store `label`. `/ingest`, seed, `/demo/*`. Buddy payloads omit neighbors with no hours.
- IMD poller: JWT from `IMD_TOKEN_URL`, state snapshots `sid` on `IMD_AWS_URL`, `ID` → `aws_id`, hour bucket in UTC, duplicate hours skipped. Off when `SKYGUARD_IMD_POLL=0` or when tests pass their own database.
- Live QC: `engine/adapter.py` maps public fields ↔ v2; `pipeline.py` persists raw, calls `v2.engine.process_aws_data` (`use_stgnn=False`, `timing_async=True`), writes overlay (`predicted`, `imputed_interval`, `thermo`, `tier2.score`, `tier3.method` / `mix` / `corr`, `reason`) and recomputes 7-day health from stored labels. Weather does not count. `ml.engine` and legacy `skyguard.engine.tier*` are not on this path.
- Missing artifacts on a full window → persist anyway, `UNCONFIRMED_ANOMALY`. Fewer than 24 hourly rows → raw hour, `warming_up`, null label, no v2 call. Catalog station with no train scaler → 400. Station not in the catalog → 404.
- Replay: `POST /demo/replay` with `clean`, `hardware`, `weather`, `freeze`, or `comms`. Seeds the 2024-12-31 fixture, ingests the scored hour, and clears the arm. `hardware` and `weather` ingest the Mumbai four. A newer live window is restored after the story.
- Streamer: `--stations 42181 --with-buddies` (default true) seeds/POSTs the ingest set. CLI overrides `GET /demo/stream-filter`. Empty filter = full catalog.
- Demo inject: `target=neighborhood` expands via the buddy graph. `target=cluster` is 400.
- Dashboard: five-page light console (Network, Station, Alerts, Control, Guide). Default view Palam∪buddies + Santacruz. Hero on Control. Network map is a Carto tile view that zooms to the selected cluster; names sit in a roster. Alerts **Open** pins that hour on Station.
- ML standalone: `ml/ml/main.py` remains eval-only. Do not point the dashboard at 8001.
- Tests: D18 mapping is unit-tested; live ingest covers two-buddy T3, isolate/one-buddy → `UNCONFIRMED_ANOMALY`, weather does not lower health. IdentityDetector / NORTH live-path tests are skipped. Engine integration skips when artifacts are missing.

## What must not be confused

| Piece                          | Role now                | Role after I4+              |
| ------------------------------ | ----------------------- | ---------------------------- |
| `src/skyguard/engine/tier*.py` | **legacy**, do not call | unused on live ingest        |
| `src/skyguard/ml/`             | IdentityDetector stub   | **legacy**                   |
| `ml/ml/engine.py`              | frozen v1 QC            | not on live ingest            |
| `v2-deliverable/v2/engine.py`  | **production QC**       | CW-IDW, TIMING queued         |
| `ml/ml/main.py`                | standalone eval only    | unchanged                     |
| `frontend/`                    | live demo               | five-page light console     |

## Locks that bite implementers

- Fault math only in `skyguard.data.inject`. Live faults in the API demo overlay, **before** ML.
- Raw T/P/H immutable. Imputed = ML `predicted`.
- Buddy check = ML graph, **≥2** usable neighbors. Isolates → `UNCONFIRMED_ANOMALY`.
- Public fields `temp_c` / `pres_hpa` / `rhum_pct`. v2 names (`temp`, `rhum`, `pres`) stay inside the adapter.
- View set ≠ ingest set. Filter Palam in the UI still streams Palam’s buddies.
- Storm inject = neighborhood, not `cluster_id: NORTH`. Palam neighborhood = `42181` + `42182` + `42139`.
- Do not invent API fields. `contracts.md` is the integration contract (v2 overlay fields added in V2-1).
- Do not `git pull` ML into `src/`. `v2-deliverable/` and `ml/` stay siblings of `frontend/`.

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

[`v2-live-plan.md`](v2-live-plan.md) step 6: `GET /stations/{id}/timing?ts=` reads the v2 cache. Ingest does not wait on it.

## Open issues

- LSTM threshold not frozen; freeze/drift are Tier 1 / window heuristics in ML, not the autoencoder.
- Nested path `ml/ml/` is awkward; do not flatten during I-slices unless a later cleanup slice says so.
- `docs/backend-simulator-summary.md` describes the **legacy** backend QC. Trust this file + `architecture.md` for the live path.
- A station with fewer than 24 hourly rows is `warming_up` with a null label. Seed still fills the window with `CLEAN` rows.
- Streaming all 151 will overwhelm the console; use `--stations` / stream-filter.
