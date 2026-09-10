# SkyGuard AI

Quality-control service for Indian Automatic Weather Stations. Hourly temperature, pressure, and humidity are scored in real time so a real storm is not treated as a broken sensor.

## 1. Project Information

- **Project Title:** SkyGuard AI
- **PS ID:** SIH26073
- **PS Title:** AI/ML-Based Intelligent Anomaly Detection for Automatic Weather Stations
- **Category:** Software
- **Theme:** Disaster Management
- **Team:** Think Tank (NSUT-SIH-26)

## 2. Problem Statement

Automatic Weather Stations stream temperature (°C), pressure (hPa), and humidity (%). Those streams fail in the field — spikes, frozen sensors, slow drift, dropped packets. Simple min/max rules cannot tell a heatwave from a broken probe, and they miss calibration drift that stays inside the valid band.

Official example: one station reports 55 °C with wild humidity and pressure while neighbors are normal. That is a **hardware anomaly**, not a heatwave.

## 3. Proposed Solution

SkyGuard sits in front of the AWS network and, for every hour, answers:

1. Is this hour trustworthy?
2. If not — is it a **real weather event** or a **broken / drifting / silent sensor**?
3. How confident are we, and which channel caused the call?
4. What would the value have been (reconstruction overlay)?
5. Is this station healthy enough to stay in the operational network (7-day health)?

Raw readings are never overwritten. The model writes an overlay, a reason sentence, and a health score.

## 4. Key Features

- Live ingest of hourly T / P / H for a 151-station Indian catalog
- Three-tier QC: physical rules → LSTM autoencoder → spatial buddy check
- Neighborhood storm vs single-station hardware demo inject
- 7-day sensor health that does **not** drop for genuine weather
- Five-page ops console: Network map, Station overlays, Alerts, Control, Guide

## 5. Technology Stack

- Frontend: Streamlit, Plotly
- Backend: Python, FastAPI, SQLAlchemy, SQLite
- Machine Learning: PyTorch (LSTM autoencoder), NumPy, Pandas
- Spatial check: inverse-distance-weighted buddy graph
- Streamer: clean historical hours over HTTP

## 6. Architecture

```text
Clean AWS hours (parquet)
        |
        v
Streamer  ----POST /ingest---->  FastAPI product shell
                                      |
                                      +--> persist raw (SQLite)
                                      +--> 24h window + buddy windows
                                      |
                                      v
                                 ML QC engine
                                 (in-process)
                                      |
                    +-----------------+-----------------+
                    |                 |                 |
              Tier 1            Tier 2 LSTM         Tier 3
           physical rules       autoencoder       buddy graph
                    |                 |                 |
                    +-----------------+-----------------+
                                      |
                                      v
                         label + overlay + health
                                      |
                                      v
                         Streamlit console (poll REST)
```

Production QC is `ml/ml/engine.py`. Demo faults are applied in the API **before** the ML call. The streamer sends clean data only.

## 7. Repository Structure

```text
sih-2026/
├── README.md
├── LICENSE
├── requirements.txt
├── pyproject.toml
├── .gitignore
├── .streamlit/
│   └── config.toml
├── src/skyguard/          # FastAPI app, streamer, demo inject
├── frontend/              # Streamlit console
├── ml/ml/                 # production QC engine + trained artifacts
├── data/processed/        # station catalog + buddy graph
└── assets/                # add screenshots here before submission
```

| Item | Location |
|---|---|
| API + streamer | `src/skyguard/` |
| Dashboard | `frontend/` |
| QC model + weights | `ml/ml/` and `ml/ml/artifacts/` |
| Station catalog | `data/processed/stations.json` |
| Buddy graph | `data/processed/buddy_edges.json` |
| License | `LICENSE` (MIT) |

## 8. Final Presentation

Add the SIH PPT under `submission/` when the file size allows it. If it is too large for GitHub, put a Google Drive / OneDrive viewer link in `submission/PRESENTATION.md`.

## 9. Demo Video

Optional but recommended. Put the YouTube or Drive link in `submission/DEMO.md`.

## 10. Screenshots / Prototype Photos

Add console screenshots to `assets/screenshots/`.

## 11. Installation

Python 3.10+. From the repo root:

```bash
git clone <YOUR_REPOSITORY_URL>
cd sih-2026
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows: `.venv\Scripts\activate`.

Torch is required so the LSTM can load. Weights come from `ml/ml/artifacts/` on API startup. If artifacts fail to load, ingest still persists and returns `UNCONFIRMED_ANOMALY`.

Hourly parquet for the stations you stream must already be present under `data/processed/` (gitignored; keep a local copy for the demo).

## 12. Run

Three terminals, from the repo root, with the venv active.

**Terminal 1 — API**

```bash
python -m uvicorn skyguard.api.main:app --host 127.0.0.1 --port 8000 --reload
```

Wait for startup. Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) · `GET /healthz` should show `model_loaded: true`.

**Terminal 2 — Palam neighborhood stream**

```bash
python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 --start 2024-07-01T00:00:00Z --stations 42181 --with-buddies
```

Seeds 24 clean hours for Palam `42181` and its buddies (Safdarjung `42182`, Meerut `42139`), then POSTs one weather-hour every 200 ms.

**Terminal 3 — dashboard**

```bash
python -m streamlit run frontend/app.py
```

Console: [http://127.0.0.1:8501](http://127.0.0.1:8501)

**Demo inject** (while the stream is running):

```bash
curl -X POST http://127.0.0.1:8000/demo/inject \
  -H 'Content-Type: application/json' \
  -d '{"target":"neighborhood","station_id":"42181","kind":"GENUINE_WEATHER"}'

curl -X POST http://127.0.0.1:8000/demo/inject \
  -H 'Content-Type: application/json' \
  -d '{"target":"station","station_id":"42181","kind":"SPIKE","channel":"temp_c"}'
```

Neighborhood storm → amber (weather). Lone Palam spike → rose (hardware). `POST /demo/reset` clears overlays.

## 13. Future Scope

- Freeze a production LSTM threshold from a labeled sweep instead of the current validation percentile.
- Publish the same `/ingest` payload from field hardware (ESP32) alongside the historical streamer.
- Expand the live view beyond Palam’s neighborhood without dropping buddy ingest.
- Operator workflows for maintenance when 7-day health is `DEGRADED` or `CRITICAL`.

## Important

Before submission, make sure the repository is accessible to reviewers. Do **not** upload passwords, API keys, access tokens, `.env` files containing secrets, or other confidential credentials.
