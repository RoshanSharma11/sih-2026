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

**Next lock (D17):** multi-page dashboard, station-wise view filter, observed + predicted overlays. Still poll-only. Still contract-only.

## D14 — One catalog: ML’s 151 stations + buddy graph

**Lock:** Source of truth for who exists and who may buddy whom is ML. Backend upserts all exported ids. LSTM **refuses** a station with no train scaler (do not borrow another station’s scaler).

Named clusters (NORTH/WEST) may remain as optional UI region tags if the CSV has them. They are not used for QC.

## D15 — Station-wise filter is a view; ingest keeps neighbors

**Lock:** Operators can select stations and see **only** those stations’ stream and predicted overlay.

- **View set** — UI / `GET` query `ids=` / stream-filter `view`.
- **Ingest set** — view set **union** each selected station’s 1-hop buddies (`include_buddies=true` by default).

Never ingest a lone station and expect `GENUINE_WEATHER_EVENT`. If the user turns `include_buddies` off, Tier 3 will skip and those hours land as `UNCONFIRMED_ANOMALY`.

## D16 — Production QC is the ML engine, in-process

**Lock:**

- One product port: backend FastAPI (`scripts/run_api.py`).
- On ingest: validate → demo overlay → persist raw → assemble window + buddies → `ml.engine.process_aws_data` **in-process** → persist overlay/alert/health → return mapped result.
- Do not HTTP-proxy to `ml.main:app` in the judge demo (second process, two ports, CORS). `ml/ml/main.py` remains valid for standalone ML eval.
- Backend `tier1.py` / `tier2.py` / `tier3.py` / `classify.py` / `IdentityDetector` stay on disk as legacy. Live `/ingest` must not call them.
- If artifacts fail to load: persist anyway, `label=UNCONFIRMED_ANOMALY`, do not run legacy tiers.

## D17 — Frontend rewrite comes after integration

**Lock:** Do not rebuild the dashboard until slices I1–I5 work. Then multi-page UI with station filter, 151-station map (or filtered subset), predicted overlay, health, alerts, inject on neighborhoods.

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
