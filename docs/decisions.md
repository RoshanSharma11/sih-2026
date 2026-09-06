# Decisions

These choices change the build. Treat them as locked unless we explicitly update this file.

## D1 — Two clusters, five stations (not five distant metros)

Buddy check is meaningless if the five stations are Delhi, Mumbai, Chennai, Pune, and Bengaluru. A monsoon in Delhi will not appear in Chennai.

**Lock:** 2 spatial clusters, 5 stations total after the 85% completeness filter.

- Cluster `NORTH`: 3 stations in / around Delhi NCR
- Cluster `WEST`: 2 stations in Mumbai–Pune (only if both pass completeness and are ≤150 km; otherwise put all 5 in NORTH)

Buddy radius: **150 km**. Power for IDW: **2**.

## D2 — Curated seed fetch, not a full-India crawl

A 2015–2025 scan of every Indian Meteostat station is slow and mostly incomplete on `pres` / `rhum`.

**Lock:** Start from a seed inventory of ~15 known Indian stations. Keep those with ≥85% complete `temp`, `pres`, and `rhum` on the chosen range. Persist the keep-list to `data/processed/stations.json`. Do not block the backend on a national crawl.

Training range (ML, later): 2018-01-01 → 2024-06-30.
Eval / demo replay range: 2024-07-01 → 2025-12-31 (or last complete year if 2025 is thin).

## D3 — Simulator is clean; backend owns live injection

If the streamer mutates data **and** the UI has an inject button, we get two sources of truth and the eval math drifts.

**Lock:**

- `skyguard.data.inject` is the only place fault math lives.
- Offline eval builder calls it and writes labels.
- Simulator POSTs **clean** payloads (plus optional `sequence_id`).
- Backend `DemoController` applies the same functions to the next N ingest events for a station or cluster.
- Storm inject = **entire cluster**. Hardware inject = **one station**, one channel.

## D4 — Identity `Detector` until ML drops weights

We own ingest and the pipeline. We do not own training.

**Lock:** Backend depends on a `Detector` protocol. Ship `IdentityDetector`. When a `.pt` / ONNX file appears, ML replaces the implementation. `/ingest` must work end-to-end with the stub (Tier 1 + Tier 3 + demo inject still demoable).

## D5 — SQLite now, schema ready for Postgres later

**Lock:** SQLite file at `data/skyguard.db`. SQLAlchemy models, no raw SQL in route handlers. Do not introduce Redis, Kafka, or Docker for v1.

## D6 — In-memory 24h windows, hydrate from DB on startup

**Lock:** Each station has an in-memory deque of the last 24 valid hourly points. On process start, load the latest 24 rows per station from `telemetry_logs`. Missing hours stay missing; do not invent them.

## D7 — REST + poll, not SSE, for v1

Frontend can poll. SSE is extra surface area.

**Lock:** JSON REST only. Dashboard poll interval target: 1s. No websocket/SSE until someone needs it.

## D8 — Raw is immutable; imputed is overlay

**Lock:** `temp_observed` / `pres_observed` / `rhum_observed` are exactly what arrived (null allowed). Imputed columns are nullable overlays. Alerts reference the observation, they do not edit it.

## D9 — Live explainability is error contribution, not SHAP

**Lock:** Hot path computes per-channel contribution %. No SHAP in `/ingest`. If frontend wants SHAP later, it is an offline/audit job.

## D10 — Seed history before the live stream

A 24-step LSTM window cannot exist at t=0.

**Lock:** `POST /stations/{id}/seed` accepts a batch of historical hours. Simulator calls seed (last 24 clean hours) for every station, then streams the following hours at an accelerated rate (default **1 weather-hour per 200 ms**).

## D11 — Tier 3 abstains when it has no neighbor

**Lock:** If a cluster has fewer than 1 usable neighbor observation within 1 hour, do not call it hardware or weather. Status = `UNKNOWN`, confidence low/medium. Prefer honesty over a fake buddy check.

## D12 — Language and field names

Use the glossary names in code:

| Concept | Code name |
|---|---|
| Temperature °C | `temp_c` |
| Pressure hPa | `pres_hpa` |
| Humidity % | `rhum_pct` |
| Imputed values | `temp_imputed`, `pres_imputed`, `rhum_imputed` |
| Fault enum | `FaultType` |
| Station health 0–100 | `health_score` |

Meteostat columns (`temp`, `pres`, `rhum`) are mapped at the fetch boundary only.
