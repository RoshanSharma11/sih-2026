# Architecture

SkyGuard is a 3-tier quality-control service in front of a small Indian AWS network. Data and backend share one Python package so injection math and payload types cannot drift.

## System

```
Meteostat (hourly T/P/H)
        │
        ▼
┌─────────────────────────────┐
│  Data engine                │
│  fetch → filter → persist   │
│  inject.py (pure functions) │
│  eval builder (labeled)     │
│  streamer (CLEAN only)      │
└─────────────┬───────────────┘
              │ POST /stations/{id}/seed
              │ POST /ingest
              ▼
┌─────────────────────────────┐
│  FastAPI                    │
│  DemoController (optional)  │
│  Tier 1  range / step / null│
│  Tier 2  Detector.reconstruct│
│  Tier 3  cluster IDW buddy  │
│  classify + health + explain│
└─────────────┬───────────────┘
              │ write
              ▼
         SQLite
              │
              │ GET /stations /telemetry /alerts
              ▼
         Streamlit dashboard (poll ~1s)
```

ESP32, if it appears, is a parallel publisher of the same `/ingest` payload. It is not in this pair’s critical path.

## Repo layout

```
sih-2026/
  docs/                     # this folder — source of truth
  data/
    raw/                    # gitignored Meteostat dumps
    processed/
      stations.json         # locked catalog + clusters
      {station_id}.parquet  # clean hourly series
    eval/
      labeled.parquet       # injected + labels
    skyguard.db             # gitignored runtime DB
  src/skyguard/
    schemas.py              # Pydantic = contracts.md
    data/
      fetch.py
      catalog.py
      inject.py             # ONLY fault math
      evalset.py
      stream.py
    api/
      main.py
      routes_ingest.py
      routes_query.py
      routes_demo.py
    engine/
      pipeline.py           # orchestrates tiers
      tier1.py
      tier2.py              # talks to Detector
      tier3.py
      classify.py
      health.py
      windows.py
      demo.py
    db/
      models.py
      session.py
    ml/
      protocol.py           # Detector ABC
      identity.py           # stub
      loader.py             # later: load .pt
  tests/
  frontend/                 # Streamlit ops console (poll only)
    app.py
    api.py
  .streamlit/config.toml
  scripts/
    fetch_stations.py
    build_evalset.py
    run_stream.py
    run_api.py
    run_dashboard.py
```

Do not put business logic in `scripts/`. Scripts only call package functions.

## Request path (`POST /ingest`)

1. Validate payload (Pydantic). Reject malformed JSON with 422.
2. If a demo overlay is armed for this station/cluster, apply `inject.py` **before** detection. Record `injected_fault` on the demo session, not on the observation, unless we are writing the eval set.
3. Persist the **raw** observation immediately (nulls allowed).
4. **Tier 1**
   - Null / missing packet → `COMM_ERROR`, skip Tier 2.
   - Hard range or step violation → `SPIKE` (or range fault), still run Tier 2/3 if values are numeric so explainability exists.
5. Append numeric points to the 24-hour window. If window length < 24, Tier 2 returns `skipped=true` and imputation is null unless Tier 1 already failed.
6. **Tier 2** — `Detector.reconstruct(window)` → `mse`, `mse_vector`, `reconstructed`, `contribution_pct`. Compare scalar MSE to `RECON_THRESHOLD` (config, default from ML later; stub uses `+inf` so it never fires).
7. **Tier 3** — only if Tier 1 flagged, or Tier 2 loss > threshold, or a storm-shaped move is large. Compare to cluster neighbors.
8. **Classify** — `FaultType` + confidence + severity + one-sentence `explainability_text`.
9. Write imputed overlay (from reconstruction) when we have a reconstruction.
10. Update 7-day `health_score` / `status` on the station.
11. Insert `anomaly_alerts` when status is not `CLEAN`.
12. Return the ingest result JSON (frontend and streamer both use this).

## Status after the pipeline

| Status | Meaning | Hardware alert? |
|---|---|---|
| `CLEAN` | Trusted observation | No |
| `GENUINE_WEATHER` | Extreme, physics + neighbors agree | No (weather notice only) |
| `HARDWARE` | Sensor/comms fault | Yes |
| `UNKNOWN` | Anomalous, cannot separate | Yes, low confidence |

`is_anomaly` on `telemetry_logs` is **true only for `HARDWARE`**. Weather events are a separate alert type so the map can show them without tanking health.

## Scaling story (for judges, not for v1)

Ingest is stateless per request except for per-station window + demo flags. SQLite → Postgres is a connection-string change. One process can handle thousands of stations at <15 ms if the detector stays on CPU. We do not pretend to have that load in the hackathon.

## Config

Environment / `.env` (no secrets required):

| Key | Default | Purpose |
|---|---|---|
| `SKYGUARD_DB` | `data/skyguard.db` | SQLite path |
| `SKYGUARD_WINDOW` | `24` | Hours in the LSTM window |
| `SKYGUARD_RECON_THRESHOLD` | `inf` | Until ML supplies a real value |
| `SKYGUARD_BUDDY_KM` | `150` | Cluster / IDW cutoff |
| `SKYGUARD_IDW_POWER` | `2` | IDW exponent |
| `SKYGUARD_STREAM_MS` | `200` | Weather-hour → wall-clock ms |
| `MODEL_PATH` | empty | If set, load real detector |

## Non-goals in this architecture

- Multi-worker ingest (window state would need a shared store)
- Training loops inside FastAPI
- Authenticating the API
- Writing SHAP values into SQLite
