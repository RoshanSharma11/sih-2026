# Context — PS 26073 / SkyGuard AI

## Problem

Automatic Weather Stations (AWS) stream temperature, pressure, and humidity. Readings go bad because of sensor faults, comms drops, calibration drift, and corruption. Simple min/max rules cannot tell a real storm from a broken sensor, and they miss slow drift.

We must detect faults in real time from **only** T, P, H; name the fault; score confidence; explain the decision; estimate a corrected value without destroying the raw reading; and track sensor health for maintenance.

Official example: one station reports 55°C + wild H/P while neighbors are normal → hardware anomaly, not a heatwave.

## What we are building (this pair)

A **data engine**, a **backend QC service**, and the **live demo dashboard**:

- Historical Indian AWS ground truth (Meteostat hourly T/P/H)
- Synthetic fault + storm injector with labels (for training and judging)
- Accelerated clean streamer into the API
- FastAPI 3-tier detector: range rules → LSTM reconstruction → spatial buddy check
- Persist raw + imputed + alerts + health
- Demo control so the UI can inject a storm or a broken sensor live
- Streamlit console: map + series + alerts + inject (poll only)

## What we are not building

- Training the LSTM (we only define the `Detector` interface and ship an identity stub)
- Full SHAP/LIME on the hot path
- On-device neural nets on ESP32
- Overwriting raw meteorological values
- A national-scale station ingest in v1 (5 stations, 2 spatial clusters)

## Glossary

Confirm these meanings. Every API field and function name should match this language.

**Observation** — One station, one timestamp, three raw values: `temp_c`, `pres_hpa`, `rhum_pct`. May contain nulls (comms loss).

**Payload** — JSON body the simulator POSTs to `/ingest`. An observation plus `station_id` and `timestamp`.

**Window** — Last `N=24` hourly observations for one station, shape `(24, 3)`, ordered oldest → newest. Used only by Tier 2.

**Anomaly** — A reading the pipeline does not trust as a faithful sensor measurement. Not the same as “extreme weather.”

**Genuine weather event** — Extreme but physically consistent T/P/H, confirmed by neighbors. Alert is recorded as weather, **not** as a hardware fault.

**Hardware anomaly** — Sensor or comms fault: spike, freeze, drift, missing packet, or single-channel physics breach.

**Reconstruction** — Model output \(\hat{T}, \hat{P}, \hat{H}\) for the latest step (or full window). Also the **imputed / corrected estimate**. Stored separately from raw.

**Reconstruction loss** — Per-channel MSE on scaled features, plus a scalar mean. Live explainability is each channel’s share of total squared error.

**Buddy check** — Inverse-distance-weighted comparison of this station’s latest values to neighbors **in the same cluster** at the same hour (or last known ≤1 hour).

**Cluster** — A set of stations within ~150 km. Buddy check never uses a station in another cluster (Delhi must not validate Mumbai).

**Health score** — Station-level 0–100 index over a 7-day rolling window. Not the same as per-reading confidence.

**Confidence** — 0–1 score on a single alert.

**Severity** — `LOW | MEDIUM | HIGH | CRITICAL` on a single alert.

**Fault type** — Closed enum: `SPIKE`, `FREEZE`, `DRIFT`, `COMM_ERROR`, `PHYSICS_BREACH`, `GENUINE_WEATHER`, `UNKNOWN`.

**Clean stream** — Simulator output with no injected faults. Demo faults are applied inside the backend.

**Eval set** — Offline labeled dataset produced by the same inject functions. Used for Precision / Recall / F1, not for the live demo.

**Identity detector** — Stub `Detector` that returns \(\hat{x} = x\) (loss 0) so backend work is not blocked on ML.
