# Backend

Owner: backend. FastAPI + SQLite **product shell**. Production QC is `ml/ml/engine.py` (D16). Depends on `inject.py` and the ML adapter, not on `IdentityDetector`.

## Process

```text
python scripts/run_api.py
```

On startup:

1. Create tables (including `station_buddies`, `telemetry_logs.label`)
2. Upsert imported `data/processed/stations.json` + `buddy_edges.json` (if missing, `/healthz` is ok, `/ingest` 503s)
3. Hydrate 24-hour windows from `telemetry_logs`
4. Construct `ml.engine.DetectionEngine` once (loads artifacts, buddy graph, health tracker)

Do not start `uvicorn ml.main:app` as the product server.

## Pipeline (live)

`engine/pipeline.py` is still the only orchestrator routes call. It no longer calls `engine.tier1` / `tier2` / `tier3` / `classify`.

1. Validate + 404/409
2. Demo overlay (`demo.py` + `inject.apply_live`)
3. Persist raw
4. Adapter builds ML payload (window + buddies)
5. `process_aws_data`
6. Map result (D12 / D18) and persist overlay, alert, health from ML

### Adapter — `engine/adapter.py`

| SkyGuard | ML |
|---|---|
| `temp_c` | `temp` |
| `rhum_pct` | `rhum` |
| `pres_hpa` | `pres` |
| window deque | `window` list of hour rows |
| `station_buddies` + neighbor deques | `buddies` |

If the engine raises `UnknownStationError`, return 404.

### Legacy modules (do not call from live ingest)

`tier1.py`, `tier2.py`, `tier3.py`, `classify.py`, `health.py`, `src/skyguard/ml/*`. Tests that pin the old 4-station NORTH/WEST story stay until I5 replaces them. New tests assert ML labels.

### Health

Live `health_score` / `status` come from ML `health.index_7d` / `health.state`. Do not recompute with the old spike/freeze weights after ingest.

## Demo controller — `demo.py`

Storm overlay lists every station in the **neighborhood** of `station_id` (D3). Hardware overlay is one station.

## Stream filter

In-memory view/ingest sets (D15). `POST /demo/stream-filter` expands with the buddy graph when `include_buddies` is true. Streamer process reads `GET /demo/stream-filter` each tick **or** takes CLI `--stations` (CLI wins if both set — lock: CLI overrides).

## Concurrency

One process. Lock per `station_id` around window update + ML call so two POSTs cannot interleave. Neighborhood storm still ingests station-by-station.

## Testing (backend)

Need loaded artifacts **or** a fixture engine. Minimum:

- Adapter maps field names and feature order (`temp, rhum, pres`)
- Null → `PHYSICAL_FAULT` / `COMM_ERROR`
- Temp 99°C → `PHYSICAL_FAULT` (ML range is −10..60)
- Lone spike vs two static neighbors → `HARDWARE_ANOMALY`
- Same storm-shaped move on a station and ≥2 neighbors → `GENUINE_WEATHER_EVENT`
- Isolate / &lt;2 buddies + LSTM flag → `UNCONFIRMED_ANOMALY`
- Duplicate timestamp → 409
- Unknown station → 404
- Health does not drop after a weather label
- Live ingest does not import/call `skyguard.engine.tier1.evaluate`

## What “done” looks like

- All routes in contracts respond
- SQLite has 151 (or imported) stations, telemetry, alerts, buddy edges
- Clean streamer can run a filtered ingest set without 500s
- `/demo/inject` neighborhood storm vs single-station spike produce different `label`s
- Frontend can poll `/stations?ids=` and `/alerts` without undocumented fields
