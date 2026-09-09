# Architecture

SkyGuard is a 3-tier quality-control service in front of an Indian AWS network. **Production QC lives in `ml/`**. Backend is the product shell (persist, demo, query). Simulator streams the same catalog ML trained on.

## System

```
ML catalog (151) + hourly series
        │
        ▼
┌─────────────────────────────┐
│  Data engine                │
│  import ML catalog           │
│  inject.py (pure functions)  │
│  eval builder (labeled)     │
│  streamer (CLEAN only)      │
│  ingest set = view ∪ buddies│
└─────────────┬───────────────┘
              │ POST /stations/{id}/seed
              │ POST /ingest
              ▼
┌─────────────────────────────┐
│  Backend FastAPI (product) │
│  DemoController (optional)  │
│  persist raw                │
│  assemble window + buddies  │
│  call ml.engine (in-process)│
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  ML QC engine                │
│  Tier 1  physical rules     │
│  Tier 2  LSTM autoencoder     │
│  Tier 3  IDW buddy graph     │
│  label + health + reason     │
└─────────────┬───────────────┘
              │ write overlay + alerts
              ▼
         SQLite
              │
              │ GET /stations /telemetry /alerts
              ▼
         Dashboard (poll ~1s)
         view set ⊆ ingest set
```

ESP32, if it appears, is a parallel publisher of the same `/ingest` payload. It is not in this pair’s critical path.

`ml/ml/main.py` is a standalone QC HTTP surface for eval. The judge demo does **not** run it as a second ingest server.

## Repo layout

```
sih-2026/
  docs/
  data/
    raw/                    # gitignored dumps
    processed/
      stations.json         # imported from ML catalog
      buddy_edges.json      # imported buddy graph
      {station_id}.parquet
    eval/
    skyguard.db
  src/skyguard/
    schemas.py
    data/                   # fetch/import, inject, stream
    api/                    # product FastAPI
    engine/
      pipeline.py           # persist + demo + ML adapter (live path)
      adapter.py            # SkyGuard payload ↔ ml.engine
      demo.py
      windows.py
      tier1.py             # LEGACY — do not call from live ingest
      tier2.py
      tier3.py
      classify.py
      health.py             # LEGACY health formula; live health from ML
    db/
    ml/                     # LEGACY Detector protocol / IdentityDetector
  ml/                       # production QC (sibling of frontend/)
    ml/
      engine.py
      physical_rules.py
      lstm_inference.py
      buddy_check.py
      root_cause.py
      catalog.py
      main.py               # standalone uvicorn, not the product port
      artifacts/           # weights, scalers, threshold
    scripts/
    test/
  frontend/                 # five-page light ops console (Network / Station / Alerts / Control / Guide)
  tests/
  scripts/
```

## Request path (`POST /ingest`)

1. Validate payload (Pydantic, public field names). Reject malformed JSON with 422. Unknown station → 404. Duplicate hour → 409.
2. If a demo overlay is armed for this station or its neighborhood, apply `inject.py` **before** QC. Record `demo_injected` on the result, not as judge ground truth.
3. Persist the **raw** observation immediately (nulls allowed).
4. Build the 24h window for this station from `WindowStore` / SQLite. Build buddy payloads from the ML graph + last 24h of each neighbor.
5. Call `ml.engine.process_aws_data` (in-process) with ML field names.
6. Map `label` → `pipeline_status`, `predicted` → imputed columns, `reason` → `explainability_text`, `health` → `health_score` / `status`.
7. Write imputed overlay when ML returned predictions. Insert `anomaly_alerts` when `label != CLEAN`.
8. Return the ingest result JSON.

Legacy backend tiers are not in this path.

## Status after QC

| ML `label` | Meaning | Map color (via `pipeline_status`) | Hardware health hit? |
|---|---|---|---|
| `CLEAN` | Trusted observation | teal | No |
| `GENUINE_WEATHER_EVENT` | Extreme, neighbors agree | amber | No |
| `PHYSICAL_FAULT` | Range / step / null | red | Yes |
| `HARDWARE_ANOMALY` | LSTM + neighbors disagree | red | Yes |
| `UNCONFIRMED_ANOMALY` | Flagged or incomplete, no buddy call | slate | Yes |

`is_anomaly` on `telemetry_logs` is true when `label != CLEAN` (includes weather). Health ignores weather.

## Station filter

```
view set  --UI / GET ?ids= / stream-filter.view-->
ingest set = view ∪ 1-hop buddies   (streamer POSTs these)
```

`GET /stations` may return 151 rows. For the map, each summary includes `latest` so the client does not N+1 poll.

## Config

| Key | Default | Purpose |
|---|---|---|
| `SKYGUARD_DB` | `data/skyguard.db` | SQLite path |
| `SKYGUARD_WINDOW` | `24` | Hours in the LSTM window |
| `SKYGUARD_STREAM_MS` | `200` | Weather-hour → wall-clock ms |
| `SKYGUARD_STATIONS` | `data/processed/stations.json` | Imported catalog |
| `SKYGUARD_BUDDY_EDGES` | `data/processed/buddy_edges.json` | Imported graph |
| `SKYGUARD_VIEW_IDS` | empty = all | Optional default view set |
| `SKYGUARD_INCLUDE_BUDDIES` | `true` | Expand view → ingest set |

LSTM threshold and scalers load from `ml/ml/artifacts/`, not from `SKYGUARD_RECON_THRESHOLD`. That env var is legacy.

## Non-goals in this architecture

- Multi-worker ingest (window state would need a shared store)
- Training loops inside FastAPI
- Authenticating the API
- Writing SHAP values into SQLite
- Running backend tiers “just in case” beside ML
- Borrowing another station’s scaler
