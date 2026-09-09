# Context — PS 26073 / SkyGuard AI

## Problem

Automatic Weather Stations (AWS) stream temperature, pressure, and humidity. Readings go bad because of sensor faults, comms drops, calibration drift, and corruption. Simple min/max rules cannot tell a real storm from a broken sensor, and they miss slow drift.

We must detect faults in real time from **only** T, P, H; name the fault; score confidence; explain the decision; estimate a corrected value without destroying the raw reading; and track sensor health for maintenance.

Official example: one station reports 55°C + wild H/P while neighbors are normal → hardware anomaly, not a heatwave.

Grand challenge: a self-aware, self-healing weather network that stays trustworthy under all conditions.

## What we are building

Three packages in one repo, one live ingest path:

- **Simulator / data engine** — clean historical Indian AWS hours, inject library, labeled eval, accelerated streamer. Catalog and buddy graph match ML (151 stations), not the old 4-station demo lock.
- **Backend (product shell)** — FastAPI + SQLite. Persist raw, apply demo overlays, assemble 24h windows + buddy windows, call ML, store imputed/alerts/health, serve query APIs. It does **not** run its own QC tiers in production.
- **ML QC engine** (`ml/`) — production 3-tier detector: physical rules → LSTM autoencoder → IDW buddy check. Trained weights and per-station scalers live here.
- **Frontend (next)** — multi-page dashboard after integration. Station-wise filter for stream + prediction. The current one-page Streamlit console (F0–F6) stays until that rewrite.

## What we are not building (this pass)

- Retraining the LSTM
- SHAP/LIME on the `/ingest` hot path
- On-device nets on ESP32
- Overwriting raw meteorological values
- Two ingest servers in the judge demo (ML’s FastAPI stays for standalone eval; the product port is the backend)

## Glossary

Confirm these meanings. Every API field and function name should match this language.

**Observation** — One station, one timestamp, three raw values. Public API: `temp_c`, `pres_hpa`, `rhum_pct` (null allowed). ML engine internally uses `temp`, `rhum`, `pres`. The adapter maps at the engine boundary.

**Payload** — JSON body the simulator POSTs to the backend `POST /ingest`. An observation plus `station_id` and `timestamp`. The backend, not the simulator, attaches the 24h window and buddy windows when it calls ML.

**Window** — Last `N=24` hourly observations for one station, oldest → newest. Required for LSTM. Gaps ≤2 hours may be interpolated **inside ML only**; raw rows in SQLite stay untouched.

**Production QC** — `ml/ml/engine.py` only: Tier 1 physical rules → LSTM → buddy check → `label` + health. Backend `engine/tier1.py`, `tier2.py`, `tier3.py`, `classify.py` are **legacy** and must not run on live ingest.

**Backend / product shell** — Persist, demo inject, seed, query APIs, window/buddy assembly, mapping ML output onto contracts.

**Anomaly** — ML `is_anomaly=true` when `label != CLEAN`. Includes genuine weather (unusual, but not a sensor fault). Health still ignores weather.

**Genuine weather event** — LSTM flagged unusual behavior and neighbors agree on IDW. Label `GENUINE_WEATHER_EVENT`. Alert is recorded. Does **not** lower sensor health.

**Hardware anomaly** — Sensor or comms fault after spatial disagreement, or a hard physical-rule fail (`PHYSICAL_FAULT`).

**Unconfirmed anomaly** — LSTM flagged (or window missing) and Tier 3 did not run (isolate, &lt;2 usable buddies, or LSTM not run). Honesty over a fake buddy call.

**Reconstruction / imputed / predicted** — Model output \(\hat{T}, \hat{P}, \hat{H}\) for the latest step. Overlay only. Raw is never overwritten.

**Buddy check** — Inverse-distance-weighted comparison to neighbors on the **ML buddy graph** (not NORTH/WEST clusters). Needs **≥2** usable contemporaneous neighbors. Isolates skip Tier 3.

**Neighborhood** — A station plus its 1-hop buddy-graph neighbors. Storm demo inject targets a neighborhood, not a named metro cluster.

**View set** — Stations the UI (or stream filter) is focused on. Charts, alerts, and predicted overlays for these ids only.

**Ingest set** — Stations the streamer actually POSTs. Must be `view set ∪ 1-hop buddies` so Tier 3 can still run. Filtering the UI to one station must not drop its neighbors from ingest.

**Health** — ML 7-day index in `[0, 1]` (`HEALTHY` ≥ 0.90, `DEGRADED` ≥ 0.70, else `CRITICAL`). Public API `health_score` = index × 100. Weather does not lower it.

**Confidence** — 0–1 score on a single decision, from ML (physical fail = 1.0, clean = 0.0, else MSE/threshold).

**Fault type** — Closed enum on the product API: `SPIKE`, `FREEZE`, `DRIFT`, `COMM_ERROR`, `GENUINE_WEATHER`, `UNKNOWN`. ML `COMMUNICATION` maps to `COMM_ERROR`. `PHYSICS_BREACH` is legacy and is not emitted by production QC.

**Label** — ML five-way: `CLEAN`, `PHYSICAL_FAULT`, `GENUINE_WEATHER_EVENT`, `HARDWARE_ANOMALY`, `UNCONFIRMED_ANOMALY`. Source of truth for QC. `pipeline_status` is a four-way map for the existing dashboard.

**Clean stream** — Simulator output with no injected faults. Demo faults are applied inside the backend **before** the ML call.

**Eval set** — Offline labeled dataset. Do not train on it.

**Identity detector** — Legacy stub. Unused on the live path once the ML engine loads. If artifacts are missing, ingest still persists and returns `UNCONFIRMED_ANOMALY`; it must not silently fall back to backend tiers.
