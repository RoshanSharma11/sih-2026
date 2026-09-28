# Decisions

These choices change the build. Treat them as locked unless we explicitly update this file.

Superseded locks are marked. Do not revive them on the live path.

## D1 — SUPERSEDED by D14

Old lock: 2 named clusters (NORTH / WEST), 5 stations after an 85% completeness filter. Completeness dropped us to 4 keepers. That catalog was a demo stand-in **before** ML delivered 151 trained stations.

**Do not** keep NORTH/WEST as the buddy boundary. Delhi still must not validate Mumbai — the ML buddy graph already enforces that.

## D2 — Catalog source is ML, not a new Meteostat crawl

**Lock:** Station list, coordinates, and buddy edges come from ML’s training export (`stations.csv` + `buddy_edges.csv`, 151 ids with per-station scalers). Backend and simulator **import** that catalog into `data/processed/`. Do not re-filter to 4/5 keepers. Do not invent stations that have no scaler.

Training range (already used by ML): 2020–2022 train, 2023 val, 2024 test.
Eval / demo replay: 2024 hours (streamer default start still `2024-07-01Z` unless a station lacks that hour).

If the CSV dump is missing, integration is blocked (see [progress.md](progress.md)).

## D3 — Simulator is clean; backend owns live injection

Unchanged.

**Lock:**

- `skyguard.data.inject` is the only place fault math lives.
- Offline eval builder calls it and writes labels.
- Simulator POSTs **clean** payloads (plus optional `sequence_id`).
- Backend `DemoController` applies the same functions to the next N ingest events **before** the ML call.
- Storm inject = **neighborhood** of a station (station + 1-hop buddies). Hardware inject = **one station**, one channel.

`cluster_id: NORTH | WEST` is no longer a storm target. Old dashboard hero “Storm on NORTH” becomes “storm around Palam” (`42181` neighborhood) after slice I3.

## D4 — SUPERSEDED by D16

Old lock: `IdentityDetector` until `MODEL_PATH`. Backend owned Tier 1 + 3 so the demo worked without weights.

Production QC is the ML engine with artifacts in `ml/ml/artifacts/`. Backend tiers are not a standby brain.

## D5 — SQLite now, schema ready for Postgres later

Unchanged.

**Lock:** SQLite file at `data/skyguard.db`. SQLAlchemy models, no raw SQL in route handlers. Do not introduce Redis, Kafka, or Docker for v1.

## D6 — Backend keeps 24h windows to feed ML

**Lock:** Backend still hydrates a 24-hour deque per station from `telemetry_logs` on boot. On ingest it sends that window (and buddy windows) into `process_aws_data`. ML also has a fallback buffer; the product path must not rely on it. Missing hours stay missing in SQLite; ML may interpolate ≤2 h **only inside the model window**.

## D7 — REST + poll, not SSE, for v1

Unchanged. JSON REST only. Dashboard poll interval target: 1 s. No websocket/SSE until someone needs it.

## D8 — Raw is immutable; imputed is overlay

Unchanged. `temp_observed` / `pres_observed` / `rhum_observed` are exactly what arrived (null allowed). Imputed columns are ML `predicted` mapped onto overlay columns. Alerts reference the observation, they do not edit it.

## D9 — Live explainability is ML `reason` + contribution, not SHAP

**Lock:** Hot path stores ML `reason` as `explainability_text` and per-channel contribution from Tier 2. No SHAP in `/ingest`. Offline SHAP remains optional later.

## D10 — Seed history before the live stream

Unchanged. `POST /stations/{id}/seed` fills windows. Simulator seeds 24 clean hours for every station in the **ingest set**, then streams. Default **1 weather-hour per 200 ms**.

## D11 — Tier 3 abstains without two usable buddies

**Lock:** ML requires `MIN_USABLE_BUDDIES = 2`. Isolates and hours with fewer than two usable neighbors skip Tier 3. Label = `UNCONFIRMED_ANOMALY` (mapped `pipeline_status=UNKNOWN`). Prefer honesty over a fake buddy check. One neighbor is not enough.

## D12 — Public field names stay SkyGuard; ML names stay inside `ml/`

| Concept | Public API / SQLite | ML engine |
|---|---|---|
| Temperature °C | `temp_c` | `temp` |
| Pressure hPa | `pres_hpa` | `pres` |
| Humidity % | `rhum_pct` | `rhum` |
| Imputed | `temp_imputed`, … | `predicted` / `reconstructed` |
| QC five-way | `label` | `label` |
| Map four-way | `pipeline_status` | derived |
| Health 0–100 | `health_score` | `health.index_7d * 100` |
| Health state | `status` | `health.state` |

Meteostat columns (`temp`, `pres`, `rhum`) map at fetch. ML columns map at the adapter. Do not rename files inside `ml/`.

## D13 — One-page console is shipped; next UI is multi-page

The F0–F6 Streamlit page remains until the frontend rewrite. After integration it is not the product UI.

**Shipped (F7–F11):** five-page light console (Network, Station, Alerts, Control, Guide). Still poll-only. Still contract-only.

**Next lock (D17):** multi-page dashboard, station-wise view filter, observed + predicted overlays. Still poll-only. Still contract-only.

## D14 — One catalog: ML’s 151 stations + buddy graph

**Superseded for the product catalog by D19.** Training scalers still cover 151 ids. The live map does not.

**Lock (training):** Source of truth for who was trained, and who may buddy whom inside that training graph, is ML. LSTM **refuses** a station with no train scaler (do not borrow another station’s scaler).

Named clusters (NORTH/WEST) may remain as optional UI region tags if the CSV has them. They are not used for QC.

## D15 — Station-wise filter is a view; ingest keeps neighbors

**Lock:** Operators can select stations and see **only** those stations’ stream and predicted overlay.

- **View set** — UI / `GET` query `ids=` / stream-filter `view`.
- **Ingest set** — view set **union** each selected station’s 1-hop buddies (`include_buddies=true` by default).

Never ingest a lone station and expect `GENUINE_WEATHER_EVENT`. If the user turns `include_buddies` off, Tier 3 will skip and those hours land as `UNCONFIRMED_ANOMALY`.

## D16 — Production QC is v2, in-process

**Lock:** Supersedes the earlier `ml.engine` product path. See [`v2-live-plan.md`](v2-live-plan.md).

- One product port: backend FastAPI (`scripts/run_api.py`).
- On ingest: validate → demo overlay → persist raw → assemble window + buddies → `v2.engine.process_aws_data` **in-process** (`get_engine(use_stgnn=False, timing_async=True)`) → persist overlay/alert and recompute health from stored labels → return mapped result.
- Do not HTTP-proxy to `v2.main:app` or `ml.main:app`. Do not call `ml.engine` on live ingest.
- Backend `tier1.py` / `tier2.py` / `tier3.py` / `classify.py` / `IdentityDetector` stay on disk as legacy. Live `/ingest` must not call them.
- If artifacts fail to load: persist anyway, `label=UNCONFIRMED_ANOMALY`, do not run legacy tiers.
- No train scaler → 400. Station not in the product catalog → 404.

## D17 — Frontend rewrite comes after integration

**Lock:** Do not rebuild the dashboard until slices I1–I5 work. The five-page console is that UI. The live map is the 48 in D19, not the 151 training ids.

## D18 — Label mapping (ML → existing dashboard)

Until the new UI ships, keep `pipeline_status` so F0–F6 does not go dark.

| ML `label` | `pipeline_status` | `is_anomaly` | Lowers health? |
|---|---|---|---|
| `CLEAN` | `CLEAN` | false | no |
| `PHYSICAL_FAULT` | `HARDWARE` | true | yes |
| `HARDWARE_ANOMALY` | `HARDWARE` | true | yes |
| `GENUINE_WEATHER_EVENT` | `GENUINE_WEATHER` | true | **no** |
| `UNCONFIRMED_ANOMALY` | `UNKNOWN` | true | yes |

`is_anomaly` follows ML (true for weather). Health follows ML’s `SENSOR_HEALTH_LABELS` (weather excluded).

## D19 — Live catalog is the 48

**Lock:** The product catalog is `v2-deliverable/v2/data/stations_judge48.csv` plus `buddy_edges.csv`, restricted to those 48 ids. Palam `42181` is not in it. Each station stores `aws_id`, `aws_name`, and `aws_distance_km` (the CSV `distance_km`: WMO site to the IMD AWS/ARG).

Buddy edges and ingest buddy payloads include only neighbors that are in this catalog and that already have hours. An empty neighbor window is omitted. Stations with fewer than two buddies inside the 48 are isolates (Safdarjung).

Boot replaces the SQLite catalog with this document, including dropping stations that are no longer in it.

`/healthz` reports `v2_artifacts.lstm`, `v2_artifacts.overlay`, and `v2_artifacts.stgnn` (graph weights loaded). `threshold` is the v2 operating score `0.008487`. Loading the graph weights does not turn GAT on.

## D20 — Live hours come from the IMD poller

**Lock:** The product process polls IMD. Token URL and AWS URL come from `IMD_TOKEN_URL` and `IMD_AWS_URL`. The body is `email`, `password`, and `api_key`. Snapshots use `Authorization: Bearer` and `X-API-KEY`. Refresh the token `expires_in` seconds after issue, one minute early.

`sid` is the state id. Row `ID` matches catalog `aws_id`. `CURR_TEMP`, `RH`, and `MSLP` map to `temp_c`, `rhum_pct`, and `pres_hpa`. Empty strings and JSON null are missing channels. `DATE`+`TIME` is UTC and is floored to the hour.

The poller calls `ingest_observation`. `DuplicateObservation` (HTTP 409) is skipped. One bad state does not stop the others. `/healthz.imd` stores `last_success`, `last_error`, and `matched`. Wind, weather code, and forecasts are not sent to the model.

## D21 — Warm-up is not a label

**Lock:** Until a station has 24 hourly rows, ingest stores the raw hour and returns `warming_up: true` with `label` and `pipeline_status` null. It does not call `process_aws_data` and it does not open an alert. The hour that fills the window is scored, and that response carries the real v2 label with `warming_up: false`. Null-label hours are left out of the 7-day health rate. Seed rows stay `CLEAN` and count toward the 24.

## D22 — Replay uses the same ingest path

**Lock:** `POST /demo/replay` reads `demo_windows.json` (24 hours ending `2024-12-31T23:00:00Z` for `43003`, `43057`, `43002`, `43058`, `42182`). It seeds the earlier hours as `CLEAN` and sends the scored hour through `ingest_observation`. Story mutations live in `inject.py` and are armed only for that call.

- `hardware` ingests the Mumbai four and sets Santa Cruz to 55 °C / 95% / 980 hPa.
- `weather` ingests the Mumbai four and adds 8 °C on Santa Cruz, Colaba, and Juhu `43002`. Alibag is the clean fourth window.
- `freeze` holds Santa Cruz temperature for 12 hours. `comms` nulls that temperature. `clean` streams all five with no mutation.

The arm is cleared before the response returns, so the next live hour is not rewritten. `POST /demo/reset` also clears it and does not delete rows. A second play deletes that fixture span first, then writes it again.

A station window that already contains an hour after the fixture end is put back when the story finishes. Replay rows remain at the 2024 timestamps. The two timelines do not share one 24-hour window.

## D23 — TIMING is polled, not on the ingest path

**Lock:** `GET /stations/{id}/timing?ts=` reads `v2` `get_timing`. `wait_s` defaults to 0 and is capped at 10. Ingest never calls it. The first ingest JSON has no timing field. `channel_attr` is returned with public names (`temp_c`, `rhum_pct`, `pres_hpa`). `pending` means poll again. `not_requested` means that hour was not queued. `error` hides the sentence.

## D24 — Weather needs a shared shock

**Lock:** `GENUINE_WEATHER_EVENT` is not "the LSTM flagged it and the neighbours agree". The CW-IDW blend must itself have moved: `blend_shift` ≥ `SHOCK_STEP_FRACTION` × agree band this hour, or `blend_baseline_delta` ≥ `SHOCK_BASELINE_FRACTION` × band from the buddies' previous-24 h mean, on a checked channel. Agreeing, calm neighbours make the hour `CLEAN` with a "Corroborated by neighbors" reason and no alert. `neighbor_shock` is `null` when buddy history is too short, and that keeps the old weather call. Fractions live in `v2-deliverable/v2/config.py`, were calibrated on 2023 only, and are not tuned in the UI. Disagreement (hardware) and unconfirmed paths are unchanged. No model was retrained.
