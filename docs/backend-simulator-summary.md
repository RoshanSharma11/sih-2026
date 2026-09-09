# Backend and simulator — what we implemented

Readable overview of the data engine (simulator) and FastAPI QC service as they exist today. Frozen field names live in [contracts.md](contracts.md). Build order and remaining ML work live in [progress.md](progress.md).

SkyGuard’s job is to look at hourly temperature, pressure, and humidity from Indian Automatic Weather Stations and answer: **is this a real storm, or a broken sensor?** The simulator supplies clean historical hours. The backend judges each hour, stores raw plus a corrected overlay, and exposes that to the dashboard.

```
Meteostat hourly T/P/H
        │
        ▼
  fetch → catalog → parquet          (data engine)
  inject.py  ──►  eval set           (offline labels)
  streamer   ──►  POST /seed + /ingest   (clean only)
                        │
                        ▼
              FastAPI 3-tier pipeline
              DemoController (live faults)
                        │
                        ▼
              SQLite  →  GET /stations /telemetry /alerts
```

## Why two pieces

If the streamer mutated data **and** the dashboard had an inject button, we would have two sources of truth. So:

| Piece | Purpose | What it does **not** do |
|---|---|---|
| **Simulator / data engine** | Ground truth, labeled eval, accelerated clean replay | Apply live demo faults |
| **Backend** | Detect, classify, persist, serve the dashboard | Train the LSTM; invent API fields |

All fault math lives in one library: `src/skyguard/data/inject.py`. Offline eval and live demo both call it.

---

## Simulator / data engine

Owner: `src/skyguard/data/`. Output is files on disk plus a clean HTTP stream.

### 1. Catalog and fetch

**Purpose.** Lock a small, complete Indian AWS network so buddy check is physically meaningful (Delhi must not validate Mumbai).

**How.** `python -m skyguard.data.fetch` (`src/skyguard/data/fetch.py` + `catalog.py`):

1. Search Meteostat within 80 km of Delhi, Mumbai, and Pune.
2. Pull hourly `temp` / `pres` / `rhum` for 2018-01-01 → 2024-12-31 and map them immediately to `temp_c` / `pres_hpa` / `rhum_pct`.
3. Drop any station below **85% completeness** on any of the three channels. Gaps are left as nulls (real comms loss), not interpolated.
4. Assign each keeper to cluster `NORTH` or `WEST` (150 km buddy radius).
5. Write `data/processed/stations.json` (committed) and one parquet per station (gitignored), plus `{id}.clean.parquet` with null rows dropped for ML training.

**What shipped.** Four stations, not five — a fifth failed the completeness bar. Both clusters still have a neighbor, so buddy check works.

| Cluster | Station | Name |
|---|---|---|
| NORTH | `42181` | Palam |
| NORTH | `42182` | Safdarjung |
| WEST | `43003` | Santacruz |
| WEST | `43057` | Colaba |

### 2. Inject library

**Purpose.** One deterministic definition of “spike”, “freeze”, “drift”, “comms gap”, and “storm” so eval labels and the live demo cannot drift apart.

**How.** Pure functions in `inject.py` (no I/O, no FastAPI):

| Function | What it does |
|---|---|
| `inject_spike` | One channel: ± uniform(4, 8) × that channel’s std |
| `inject_freeze` | Hold the first value for N hours (default 12) |
| `inject_drift` | Add `slope * hour_index` (default slope 0.1) |
| `inject_comm_error` | Return `None` (missing packet) |
| `inject_storm` | T down 8–15 °C, P down 10–25 hPa, H up 30–50 pp (capped at 100) |
| `apply_live` | Same math, one observation at a time, for the backend overlay |

Storm mutates **all three channels together**. Hardware faults mutate **one station, one channel**.

### 3. Eval set

**Purpose.** Offline labeled dataset so ML can measure Precision / Recall / F1. Not used in the live demo.

**How.** `python -m skyguard.data.evalset` (`evalset.py`):

- Target ~10,000 hourly rows, **15%** injected, seed `26073`.
- Mix of the 15%: spike 25%, freeze 20%, drift 15%, comm 15%, genuine weather 25%.
- Storms are applied to **every station in the cluster at the same hour**.
- Keeps `temp_c_raw` / `pres_hpa_raw` / `rhum_pct_raw` next to the mutated values.
- `is_anomaly` is true only for hardware labels. `GENUINE_WEATHER` is labeled but **not** an anomaly, so a weather event is not scored as a false positive.

Output: `data/eval/labeled.parquet` (gitignored). Train on `*.clean.parquet` only.

### 4. Clean streamer

**Purpose.** Replay history into the API at demo speed so the dashboard looks live, without baking faults into the tape.

**How.** `python -m skyguard.data.stream` (`stream.py`):

1. Wait until `GET /healthz` returns `{ "ok": true }`.
2. For each station, `POST /stations/{id}/seed` with the 24 hours **before** `demo_start` (default `2024-07-01T00:00:00Z`). Seed fills the LSTM window; it does not raise alerts.
3. Walk shared hours from `demo_start` onward. Each tick, `POST /ingest` for every station at that timestamp, then sleep `SKYGUARD_STREAM_MS` (default 200 ms ≈ 1 weather-hour).
4. `409` duplicate hours are skipped, not a crash, and do not consume a demo overlay hour.

There is **no** `--fault` flag. Live faults go through `POST /demo/inject`.

---

## Backend

Owner: `src/skyguard/api/`, `engine/`, `db/`, `ml/`. FastAPI + SQLite + a 3-tier QC pipeline.

**Purpose.** Accept one observation, optionally mutate it if a demo overlay is armed, persist the raw reading forever, decide CLEAN / weather / hardware / unknown, write an imputed overlay and an alert, update 7-day health, and return a contract-shaped JSON the dashboard can poll.

Run: `python scripts/run_api.py` → `http://127.0.0.1:8000` (OpenAPI at `/docs`).

### Startup

On boot (`api/main.py`):

1. Create SQLite tables (`data/skyguard.db`).
2. Upsert `stations.json` into `stations`. If the catalog is missing, `/healthz` still works but `/ingest` returns 503.
3. Hydrate each station’s in-memory 24-hour window from `telemetry_logs`.
4. Load a `Detector`. With `MODEL_PATH` unset this is `IdentityDetector` (copy last step, MSE 0). A real `.pt` / ONNX loader is still a stub.

### Routes that exist

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness |
| `POST` | `/stations/{id}/seed` | Load clean history into the window (no alerts) |
| `POST` | `/ingest` | One hour through the full pipeline |
| `GET` | `/stations` | Map markers: id, name, lat/lon, cluster, health |
| `GET` | `/stations/{id}` | Summary + latest ingest result (`pipeline_status`) |
| `GET` | `/stations/{id}/telemetry` | Observed + imputed series |
| `GET` | `/alerts` | Newest-first verdict sentences |
| `POST` | `/demo/inject` | Arm a storm or hardware overlay |
| `POST` | `/demo/reset` | Clear overlays |
| `GET` | `/demo/status` | What is currently armed |

Unknown station → 404. Duplicate `(station_id, timestamp)` → 409. Routes validate with Pydantic (`schemas.py`) and call `engine.pipeline` only.

### Ingest path (how one hour is judged)

`engine/pipeline.py` is the only orchestrator.

1. **Validate** the payload. Reject unknown stations and duplicate hours.
2. **Demo overlay** (if armed for this station or its cluster): `DemoController` calls `inject.apply_live` **before** detection. The streamer still sent clean data.
3. **Persist observed T/P/H.** These columns are never overwritten. Imputed values are a separate overlay.
4. **Tier 1 — hard physics** (`tier1.py`): any null → `COMM_ERROR` and skip reconstruction. Else range (T −20…55 °C, P 850…1050 hPa, H 0…100%) and step vs the previous hour (T 10 °C, P 15 hPa, H 50 pp). Range/step failure still continues so explainability exists.
5. **Tier 2 — reconstruction** (`tier2.py`): last 24 complete hours, no nulls, shape `(24, 3)`, oldest → newest. `Detector.reconstruct` returns \(\hat{T},\hat{P},\hat{H}\), per-channel MSE, and contribution %. Compared to `SKYGUARD_RECON_THRESHOLD` (default `inf`, so the identity stub never fires). Imputation = reconstructed values in original units.
6. **Tier 3 — buddy check** (`tier3.py`): inverse-distance-weighted comparison to **same-cluster** neighbors at this hour (or last known ≤ 1 hour), 150 km, power 2. Delhi never validates Mumbai. Residual cuts: 4 °C / 4 hPa / 15%. Storm shape is T↓ P↓ H↑ together (or the reverse heat-wave). No usable neighbor → `UNKNOWN` (honest abstain).
7. **Classify** (`classify.py`): first match wins — comms, contemporaneous weather, freeze (exactly one channel stuck 6 hours), drift (buddy residual rising for 24 hours), physics breach (one channel insane, others match neighbors), spike, else CLEAN.
8. **Write** imputed overlay, alert if not CLEAN, recompute 7-day health, append the hour to the window.
9. **Return** `IngestResult`. `demo_injected` is the overlay kind, not judge ground truth.

### Status after the pipeline

| `pipeline_status` | Meaning | Hardware alert? | Lowers health? |
|---|---|---|---|
| `CLEAN` | Trusted observation | No | No |
| `GENUINE_WEATHER` | Extreme, neighbors agree | Weather notice only | **No** |
| `HARDWARE` | Sensor / comms fault | Yes (`is_anomaly=true`) | Yes |
| `UNKNOWN` | Anomalous, cannot separate | Yes, low confidence | No (not a hardware counter) |

Sequential ingest matters for the demo: the **first** station in a storm hour may be `UNKNOWN` until a same-hour neighbor exists; the **second** is the weather call.

### Demo controller

**Purpose.** Let judges press “storm on NORTH” or “break Palam temperature” while the streamer keeps sending clean hours.

**How.** In-memory overlays (`engine/demo.py`):

- Storm → `target=cluster`, every station in that cluster, default 3 hours, same RNG per overlay hour so neighbors move together.
- Hardware (spike / freeze / drift / comm) → `target=station`, one channel, durations 1 / 12 / 48 / 1 hours.
- Freeze remembers the first observed value. Drift uses `hour_index`. Each matching ingest decrements `remaining_hours`.

This is the same `inject.py` math as the eval set.

### Health

**Purpose.** Station-level maintenance score, not per-reading confidence.

After every ingest, `health.py` looks at the last 7×24 hours:

```
health = 100 - (2×spike_count + 3×freeze_count + 5×drift_count + 10×missing_fraction)
```

Clamped to `[0, 100]`. `>80` HEALTHY, `50–80` DEGRADED, `<50` CRITICAL. Genuine weather alerts do not increment the counters.

### Identity detector (until ML)

`IdentityDetector` copies the latest step and reports MSE 0. The storm-vs-spike demo is therefore **Tier 1 + Tier 3 complete without weights**. When a model file exists: implement `load_detector` in `ml/loader.py`, set `MODEL_PATH`, and set a real `SKYGUARD_RECON_THRESHOLD`. `/ingest` already calls `Detector.reconstruct` on a full window.

---

## How they work together in a demo

```text
python scripts/run_api.py
python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 --start 2024-07-01T00:00:00Z
```

Then either the dashboard inject buttons or:

```text
POST /demo/inject  { "target": "cluster", "cluster_id": "NORTH", "kind": "GENUINE_WEATHER" }
POST /demo/inject  { "target": "station", "station_id": "42181", "kind": "SPIKE", "channel": "temp_c" }
```

Expected: NORTH storm → both Delhi stations `GENUINE_WEATHER` (amber), Mumbai stays clean. Palam spike → only Palam `HARDWARE` (red), Safdarjung stays clean.

---

## File map

| Area | Path |
|---|---|
| Shared payloads | `src/skyguard/schemas.py` |
| Fetch + catalog | `src/skyguard/data/fetch.py`, `catalog.py` |
| Fault math | `src/skyguard/data/inject.py` |
| Eval builder | `src/skyguard/data/evalset.py` |
| Clean streamer | `src/skyguard/data/stream.py` |
| FastAPI app | `src/skyguard/api/main.py`, `routes_*.py` |
| Pipeline | `src/skyguard/engine/pipeline.py` |
| Tiers + classify + health | `src/skyguard/engine/tier1.py`, `tier2.py`, `tier3.py`, `classify.py`, `health.py` |
| Demo overlays | `src/skyguard/engine/demo.py` |
| SQLite | `src/skyguard/db/models.py` |
| Detector stub | `src/skyguard/ml/identity.py`, `protocol.py`, `loader.py` |
| Locked catalog | `data/processed/stations.json` |

Scripts under `scripts/` only call package functions (`run_api.py`, `run_stream.py`, `fetch_stations.py`, `build_evalset.py`).

---

## What is still a stub

| Owner | Status |
|---|---|
| LSTM `Detector` | `MODEL_PATH` still raises `NotImplementedError`. Identity stub is wired. |
| Dashboard | Implemented separately (polls these contracts). |
| ESP32 / auth / SSE / Docker | Out of scope. |

Raw observations stay immutable. Buddy check stays cluster-local. Injection math stays in `inject.py`.
