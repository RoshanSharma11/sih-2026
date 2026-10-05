# SkyGuard AI — SIH PS 26073

Quality-control service for Indian Automatic Weather Stations. Input is hourly **T / P / H only**. The API separates a real storm from a broken sensor, keeps raw readings intact, and tracks 7-day sensor health. Genuine weather does not lower that health.

|                    |                                                                                  |
| ------------------ | -------------------------------------------------------------------------------- |
| **GitHub**         | [github.com/RoshanSharma11/sih-2026](https://github.com/RoshanSharma11/sih-2026) |
| **Demo video**     | [youtu.be/emdL6D2NRLQ](https://youtu.be/emdL6D2NRLQ)                             |
| **Live prototype** | [skyguard.roshansharma.net](https://www.skyguard.roshansharma.net/)              |

---

## 1. Project Information

- **Project Title:** SkyGuard AI: Real-Time Quality Control for Indian Weather Stations
- **PS ID:** 26073
- **PS Title:** AI-based quality control for Automatic Weather Station (AWS) observations (Ministry of Earth Sciences / IMD)
- **Category:** Software
- **Theme / technology bucket:** Disaster Management

## 2. Problem Statement

Automatic Weather Stations across India report temperature, pressure, and humidity every hour into forecasts, aviation, agriculture, and disaster response. The same stream decides whether a technician is sent.

A reading of 55 °C with extreme humidity and pressure, while neighbors are normal, is a hardware fault — not a heatwave. A frozen but plausible value looks like calm weather. Slow drift stays inside min/max gates. A real storm seen at one station alone looks like a multi-channel failure. Reviewers need a system that trusts, explains, and optionally corrects an hour without destroying the original observation.

## 3. Proposed Solution

SkyGuard scores every station-hour and returns one of five verdicts: trusted, physical fault, hardware anomaly, genuine weather, or unconfirmed.

- The raw hour is never overwritten.
- A corrected hour and a 90% band are attached only for physical / hardware faults.
- Shared weather keeps the observation and does not lower 7-day sensor health.
- Fewer than two usable neighbors, or fewer than 24 hours of history, yields no spatial guess.

Live product catalog: the 48 stations in `v2-deliverable/v2/data/stations_judge48.csv`. `POST /ingest` scores in-process with `v2.engine.process_aws_data`.

## 4. Key Features

- Hourly QC for temperature, pressure, and humidity only
- Weather vs hardware vs physical-fault labels with confidence and reason
- Buddy-graph spatial check (≥2 neighbors; isolates abstain)
- Immutable raw readings + imputed overlay when the instrument is at fault
- 7-day sensor health (weather never charges the score)
- Live IMD poller for the 48-station catalog
- Operator console: Network map, Station evidence, Alerts inbox, Reliability, Control (Mumbai replay)
- Demo inject / replay for hardware spike vs shared storm stories
- CSV export with WMO-style `qc_flag`
- Optional webhook pager for degraded / critical stations

## 5. Technology Stack

- **Frontend:** Streamlit, Plotly
- **Backend:** Python 3.10+, FastAPI, SQLAlchemy, SQLite
- **Machine Learning:** PyTorch (physics-informed LSTM autoencoder), NumPy, Pandas
- **QC engine:** `v2-deliverable` `v2.engine.process_aws_data` (CW-IDW buddy check; GAT off on live path)
- **Live data:** IMD OAuth + AWS hourly API
- **Deployment:** Docker / cloud (API + dashboard); live prototype at the link above

## 6. Architecture

See [docs/architecture.md](docs/architecture.md).

```text
IMD hourly poll  /  demo replay  /  inject
        |
        v
   FastAPI product API
        |
        +----> SQLite (raw + overlay + alerts + health)
        |
        v
   v2.engine (Tier 1 physical → Tier 2 LSTM → Tier 3 buddies)
        |
        v
   Label + reason + optional imputed hour
        |
        v
   Streamlit dashboard (polls product API only)
```

## 7. Repository Structure

```text
sih-2026/
├── README.md
├── SUBMISSION_GUIDE.md
├── LICENSE
├── submission/
│   ├── PRESENTATION.md
│   └── DEMO.md
├── assets/
│   └── screenshots/          # product + eval screenshots
├── docs/                    # architecture, contracts, progress, pitch
├── src/skyguard/            # product API, pipeline, data, DB
├── frontend/                # Streamlit console
├── v2-deliverable/          # production QC engine + weights
├── scripts/                 # run_api, run_dashboard, serve
├── tests/
├── data/processed/          # 48-station catalog + buddy edges
├── ml/                      # eval / training (not live ingest)
├── pyproject.toml
├── Dockerfile
└── docker-compose.yml
```

### What goes where?

| Item                                   | Location                                        |
| -------------------------------------- | ----------------------------------------------- |
| Source code                            | `src/skyguard/`, `frontend/`, `v2-deliverable/` |
| Architecture / technical documentation | `docs/`                                         |
| Project screenshots                    | `assets/screenshots/`                           |
| Final PPT / presentation               | `submission/` (and `docs/sih-judge-pitch.pdf`)  |
| Demo video link                        | `submission/DEMO.md`                            |
| Project overview                       | `README.md`                                     |

Internal engineering notes (`docs/progress.md`, `docs/contracts.md`, `AGENTS.md`) support development; judges can start from this README and `submission/`.

## 8. Final Presentation

See [submission/PRESENTATION.md](submission/PRESENTATION.md).

Final PDF in-repo: [submission/thinktank-ppt.pdf](submission/thinktank-ppt.pdf).

## 9. Demo Video

See [submission/DEMO.md](submission/DEMO.md).

- **YouTube:** [https://youtu.be/emdL6D2NRLQ](https://youtu.be/emdL6D2NRLQ)
- **Live prototype:** [https://www.skyguard.roshansharma.net/](https://www.skyguard.roshansharma.net/)

## 10. Screenshots / Prototype Photos

Product UI and eval shots live in `[assets/screenshots/](assets/screenshots/)`.

| Shot                            | File                                                                                    |
| ------------------------------- | --------------------------------------------------------------------------------------- |
| Network map                     | `[01-network-map.png](assets/screenshots/01-network-map.png)`                           |
| Station (QC / fault hour)       | `[02-station-hardware-anomaly.png](assets/screenshots/02-station-hardware-anomaly.png)` |
| Station (detail / weather path) | `[03-station-genuine-weather.png](assets/screenshots/03-station-genuine-weather.png)`   |
| Alerts inbox                    | `[04-alerts-inbox.png](assets/screenshots/04-alerts-inbox.png)`                         |
| Reliability                     | `[05-reliability.png](assets/screenshots/05-reliability.png)`                           |
| Control — Mumbai 55 °C replay   | `[06-control-replay.png](assets/screenshots/06-control-replay.png)`                     |
| Architecture page               | `[07-architecture-page.png](assets/screenshots/07-architecture-page.png)`               |
| QC eval summary                 | `[08-qc-eval-summary.png](assets/screenshots/08-qc-eval-summary.png)`                   |

Naming conventions: `[assets/screenshots/README.md](assets/screenshots/README.md)`.

## 11. Installation

```bash
git clone https://github.com/RoshanSharma11/sih-2026.git
cd sih-2026

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -e ".[dev,ui]"
pip install -r v2-deliverable/requirements.txt
```

Torch is required for the live LSTM. Weights load from `v2-deliverable/v2/artifacts/` on API boot.

Copy `.env.example` to `.env` and fill `IMD_API_KEY`, `IMD_EMAIL`, and `IMD_PASSWORD` if you want the live IMD poller. Leave them empty (or set `SKYGUARD_IMD_POLL=0`) to run offline with replay / inject only.

**Never commit** `.env`**, passwords, API keys, or tokens.**

`data/processed/stations.json` and `buddy_edges.json` are already the 48-station catalog. Re-import only when `stations_judge48.csv` changes:

```bash
python -m skyguard.data.import_ml_catalog
```

Delete `data/skyguard.db` after a re-import (gitignored; recreated on API startup).

## 12. Run

**Local (recommended) — two terminals:**

```bash
python scripts/run_api.py
```

Wait for `Application startup complete`. Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)  
`GET /healthz` should show `model_loaded: true`, `n_stations: 48` when v2 weights load.

```bash
python scripts/run_dashboard.py
```

Dashboard: [http://127.0.0.1:8501](http://127.0.0.1:8501) (`SKYGUARD_API` defaults to `http://127.0.0.1:8000`).

**Judge replay (no live stream required):**

```bash
curl -X POST http://127.0.0.1:8000/demo/replay \
  -H 'Content-Type: application/json' \
  -d '{"story":"hardware"}'

curl -X POST http://127.0.0.1:8000/demo/replay \
  -H 'Content-Type: application/json' \
  -d '{"story":"weather"}'
```

- `hardware` — Santa Cruz spike → `HARDWARE_ANOMALY`, imputed band near ~25 °C
- `weather` — shared heat across Mumbai buddies → `GENUINE_WEATHER_EVENT`, health unchanged

Tests: `pytest -q`.

Docker / remote: `Dockerfile`, `docker-compose.yml`, and `scripts/serve.sh` bind `0.0.0.0`. Prefer the two scripts above for local work.

Payload shapes: [docs/contracts.md](docs/contracts.md). Full route table and QC notes remain in the older developer sections of git history / [docs/backend.md](docs/backend.md).

## 13. Future Scope

- Expand the live catalog beyond the judge 48 as IMD coverage and scaler coverage allow
- Turn on / harden spatial graph options only where neighbor density supports it
- Stronger drift and multi-day bias detection without retraining the LSTM threshold on eval years
- Richer technician dispatch workflows (ack → resolve → field ticket) tied to health transitions
- Multi-tenant / state-scoped deployments for IMD regional centres
- Broader evaluation reports and public reliability dashboards per station

---

## Important

Before submission, keep the repository accessible to reviewers. Do **not** upload passwords, API keys, access tokens, `.env` files containing secrets, or other confidential credentials. Names of env vars live in `.env.example` only.
