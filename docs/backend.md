# Backend

Owner: backend. FastAPI + SQLite **product shell**. Production QC is `v2-deliverable` `v2.engine.process_aws_data` (in-process, GAT off). Depends on `inject.py` and the adapter, not on `IdentityDetector` or `ml.engine`.

## Process

```text
python scripts/run_api.py
```

On startup:

1. Create tables (including `station_buddies`, `telemetry_logs.label`)
2. Upsert imported `data/processed/stations.json` + `buddy_edges.json` (the live 48; stations left over from the 151 are dropped). If the catalog is missing, `/healthz` is ok and `/ingest` 503s. `/healthz` includes `v2_artifacts` (`lstm`, `overlay`, `stgnn`) and the v2 threshold `0.008487` when weights load.
3. Hydrate 24-hour windows from `telemetry_logs`
4. Call `v2.engine.get_engine(use_stgnn=False, timing_async=True)` once (CW-IDW, TIMING queued)

Do not start `uvicorn v2.main:app` or `uvicorn ml.main:app` as the product server.

## Pipeline (live)

`engine/pipeline.py` is still the only orchestrator routes call. It no longer calls `engine.tier1` / `tier2` / `tier3` / `classify`.

1. Validate + 404/409
2. Demo overlay (`demo.py` + `inject.apply_live`)
3. Persist raw
4. Adapter builds ML payload (window + buddies)
5. `process_aws_data`
6. Map result (D12 / D18) and persist overlay, alert, and health from stored labels

### Adapter — `engine/adapter.py`

| SkyGuard | v2 |
|---|---|
| `temp_c` | `temp` |
| `rhum_pct` | `rhum` |
| `pres_hpa` | `pres` |
| `explainability_text` | `reason` |
| `imputed` | `predicted` |
| `imputed_interval` | `imputed_interval` |
| window deque | `window` list of hour rows |
| `station_buddies` + neighbor deques that already have hours | `buddies` |

Persist `predicted` (imputed columns), `imputed_interval`, `thermo`, `tier2.score`, `tier3.method` / `mix` / `corr`, and `reason`. If the engine raises `UnknownStationError`, or the station has no train scaler, return 400. A station missing from the product catalog is still 404.

### Legacy modules (do not call from live ingest)

`tier1.py`, `tier2.py`, `tier3.py`, `classify.py`, `health.py`, `src/skyguard/ml/*`. IdentityDetector / NORTH live-path tests are skipped (I5). New tests assert ML labels.

### Health

Live `health_score` / `status` are recomputed from stored labels over 168 hours. Weather does not count. Do not use the v2 in-memory tracker, and do not recompute with the old spike/freeze weights.

## Demo controller — `demo.py`

Storm overlay lists every station in the **neighborhood** of `station_id` (D3). Hardware overlay is one station.

## Stream filter

In-memory view/ingest sets (D15). `POST /demo/stream-filter` expands with the buddy graph when `include_buddies` is true. Streamer process reads `GET /demo/stream-filter` each tick **or** takes CLI `--stations` (CLI wins if both set — lock: CLI overrides).

## Concurrency

One process. Lock per `station_id` around window update + the v2 call so two POSTs cannot interleave. Neighborhood storm still ingests station-by-station.

## Testing (backend)

Need loaded artifacts **or** a fixture engine. Minimum:

- Adapter maps field names and feature order (`temp, rhum, pres`)
- Null → `PHYSICAL_FAULT` / `COMM_ERROR`
- Temp 99°C → `PHYSICAL_FAULT` (ML range is −10..60)
- Lone spike vs two static neighbors → `HARDWARE_ANOMALY`
- Same storm-shaped move on a station and ≥2 neighbors → `GENUINE_WEATHER_EVENT`
- Isolate / &lt;2 buddies + LSTM flag → `UNCONFIRMED_ANOMALY`
- Duplicate timestamp → 409
- Unknown station → 404. Catalog station with no scaler → 400
- Health does not drop after a weather label
- Live ingest does not import/call `skyguard.engine.tier1.evaluate`

## What “done” looks like

- All routes in contracts respond
- SQLite has the live 48, telemetry, alerts, and buddy edges inside that set
- Clean streamer can run a filtered ingest set without 500s
- `/demo/inject` neighborhood storm vs single-station spike produce different `label`s
- Frontend can poll `/stations?ids=` and `/alerts` without undocumented fields
