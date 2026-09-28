# SkyGuard AI (SIH PS 26073)

Quality-control service for Indian Automatic Weather Stations. Input is hourly **T / P / H only**. The API separates a real storm from a broken sensor, keeps raw readings intact, and tracks 7-day sensor health. Genuine weather does not lower that health.

**Live product:** the catalog is the 48 stations in `v2-deliverable/v2/data/stations_judge48.csv`. `POST /ingest` scores in-process with `v2.engine.process_aws_data`. Palam `42181` is not in the catalog. Safdarjung `42182` is an isolate inside the 48. The dashboard polls this API only.

Status: [docs/progress.md](docs/progress.md). Payloads: [docs/contracts.md](docs/contracts.md).

## Setup

Python 3.10+. From the repo root:

```text
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ui]"
pip install -r v2-deliverable/requirements.txt
```

Torch is required for the live LSTM. Weights load from `v2-deliverable/v2/artifacts/` on API boot. Do not set `MODEL_PATH`. If those artifacts fail to load, a full window is stored as `UNCONFIRMED_ANOMALY`.

Copy `.env.example` to `.env` and fill `IMD_API_KEY`, `IMD_EMAIL`, and `IMD_PASSWORD`. Never commit `.env`. The poller stays off when those three are empty or when `SKYGUARD_IMD_POLL=0`. Optional pager: `SKYGUARD_WEBHOOK_URL`.

`data/processed/stations.json` and `buddy_edges.json` are already the 48-station catalog. Re-import only when `stations_judge48.csv` changes:

```text
python -m skyguard.data.import_ml_catalog
```

Delete `data/skyguard.db` after a re-import. The database is created on API startup and is gitignored.

## Run

Two terminals.

```text
python scripts/run_api.py
```

Wait for `Application startup complete`. Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). `GET /healthz` should show `model_loaded: true`, `n_stations: 48`, and `threshold: 0.008487` when the v2 weights load. This script binds `127.0.0.1` with reload.

With credentials in `.env`, the API polls IMD hourly at :20 and stores matched hours through ingest. A station with fewer than 24 hours returns the raw hour, `warming_up`, and a null label. The 24th hour is the first v2 score.

```text
python scripts/run_dashboard.py
```

[http://127.0.0.1:8501](http://127.0.0.1:8501). `SKYGUARD_API` defaults to `http://127.0.0.1:8000`. Pages: Network, Station, Alerts, Reliability, Control, How QC works, Architecture. The map is the live 48. The camera starts on Mumbai plus Safdarjung. Default station is Santa Cruz `43003`.

Tests: `pytest -q`.

## Judge script (Mumbai replay)

No stream. Control → Play, or:

```text
curl -X POST http://127.0.0.1:8000/demo/replay \
  -H 'Content-Type: application/json' \
  -d '{"story":"hardware"}'

curl -X POST http://127.0.0.1:8000/demo/replay \
  -H 'Content-Type: application/json' \
  -d '{"story":"weather"}'
```

- `hardware` ingests the Mumbai four and sets Santa Cruz `43003` to 55 °C / 95% / 980 hPa. Expect `HARDWARE_ANOMALY` on Santa Cruz and a temperature band near 25 °C.
- `weather` adds +8 °C on Santa Cruz, Colaba `43057`, and Juhu `43002`. Expect `GENUINE_WEATHER_EVENT`, no band, and health unchanged.
- `POST /demo/reset` clears the replay arm. It does not delete stored hours.
- Stories land on `2024-12-31T23:00:00Z`. A newer live hour stays the latest hour.

Custom overlay, once a station has a window. A storm must name a neighborhood. Hardware must name one station. `target: "cluster"` is **400**.

```text
curl -X POST http://127.0.0.1:8000/demo/inject \
  -H 'Content-Type: application/json' \
  -d '{"target":"neighborhood","station_id":"43003","kind":"GENUINE_WEATHER"}'

curl -X POST http://127.0.0.1:8000/demo/inject \
  -H 'Content-Type: application/json' \
  -d '{"target":"station","station_id":"43003","kind":"SPIKE","channel":"temp_c"}'
```

## Routes

Poll shapes are frozen in [docs/contracts.md](docs/contracts.md).


| Method       | Path                                        | Use                                                                 |
| ------------ | ------------------------------------------- | ------------------------------------------------------------------- |
| `GET`        | `/healthz`                                  | `ok`, `model_loaded`, `threshold`, `n_stations`, `v2_artifacts`, `imd`, `webhook` |
| `GET`        | `/stations?ids=`                            | summaries with `latest`, `buddy_ids`, `isolate`, `aws_id`          |
| `GET`        | `/stations/{id}`                            | summary + `latest`                                                  |
| `GET`        | `/stations/{id}/telemetry?from=&to=&limit=` | observed + imputed                                                  |
| `GET`        | `/stations/{id}/timing?ts=&wait_s=`         | TIMING cache for that hour                                          |
| `GET`        | `/alerts?station_id=&state=&limit=`         | newest first — verdict, `label`, `ack_state`                        |
| `POST`       | `/alerts/{id}/ack`                          | `{state, note?, by?}` — open / acknowledged / resolved              |
| `GET`        | `/buddy-map`                                | buddy graph for the dashboard                                       |
| `GET`        | `/reliability?hours=`                       | completeness, outcome counts, flag rate                            |
| `GET`        | `/export?station_id=&from=&to=`             | QC'd CSV: raw T/P/H + WMO-style `qc_flag`                           |
| `POST`       | `/demo/replay`                              | `clean`, `hardware`, `weather`, `freeze`, `comms`                   |
| `GET`        | `/demo/status`                              | armed overlays                                                      |
| `GET`/`POST` | `/demo/stream-filter`                       | view vs ingest sets                                                 |


Raw `temp_observed` / `pres_observed` / `rhum_observed` are immutable. Imputed columns are the v2 overlay.

## QC

Production QC is `v2-deliverable` `v2.engine.process_aws_data`, called in-process. GAT stays off. `ml/ml/engine.py`, `src/skyguard/ml/`, and `src/skyguard/engine/tier*.py` are not on this path. Do not point the dashboard at port 8001.

## Docs

Read [docs/README.md](docs/README.md) before changing behavior. If code and contracts disagree, update `docs/contracts.md` in the same change.
