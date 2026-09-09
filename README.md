# SkyGuard AI (SIH PS 26073)

Quality-control service for Indian Automatic Weather Stations. Input is hourly **T / P / H only**. The API tells a real storm from a broken sensor, keeps raw readings intact, and tracks 7-day sensor health.

**Handoff (2026-09-09):** docs I0 is locked. Production QC is `ml/` (151 stations + LSTM + buddy graph). **Live `/ingest` still runs the old backend tiers until slice I2.** Do not treat this README’s 4-station NORTH/WEST curl examples as the target architecture. Status and next slices: [docs/progress.md](docs/progress.md). Target contracts: [docs/contracts.md](docs/contracts.md).

This repo is the **data engine + FastAPI product shell + ML QC package + Streamlit console**. Frozen payloads: [docs/contracts.md](docs/contracts.md).

Until I1 imports ML’s catalog, the running demo catalog is still **four** stations. Buddy check on the live path is still NORTH/WEST. After I2, buddy check is the ML graph and Delhi still does not validate Mumbai.

| Cluster | IDs |
|---|---|
| NORTH | `42181` Palam, `42182` Safdarjung |
| WEST | `43003` Santacruz, `43057` Colaba |

## Setup

Python 3.10+. From the repo root:

```text
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ui]"
```

Until I2, the running API still uses the identity stub. Do not set `MODEL_PATH`. After I2, weights load from `ml/ml/artifacts/` automatically.

## Fetch ground truth

Writes `data/processed/stations.json` (committed) and one parquet per station (gitignored). Slow: 2018–2024 hourly from Meteostat.

```text
python -m skyguard.data.fetch
```

If parquet is already on disk, skip fetch. Rebuild the labeled eval set (also gitignored) with:

```text
python -m skyguard.data.evalset
```

LSTM eval set — send `scripts/simulate_corruption_eval.py`. Clean CSV in; labeled eval CSV + graph out. **Do not train on that CSV.**

```text
python scripts/simulate_corruption_eval.py --clean test_2024.csv --out ./eval_out
```

## Run the API and the clean stream

`python -m skyguard.api.main` only imports the app and exits. Use the script:

```text
python scripts/run_api.py
```

Wait for `Application startup complete`. Interactive docs: http://127.0.0.1:8000/docs

In a second terminal, seed 24 clean hours then POST every station each weather-hour (default 200 ms):

```text
python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 --start 2024-07-01T00:00:00Z
```

`--hours N` stops after N weather-hours. The streamer has **no** `--fault` flag. `409` duplicate hours are skipped, not a crash.

Tests: `pytest -q`.

## Demo inject (storm ≠ broken sensor)

While the stream is running:

```text
curl -X POST http://127.0.0.1:8000/demo/inject \
  -H 'Content-Type: application/json' \
  -d '{"target":"cluster","cluster_id":"NORTH","kind":"GENUINE_WEATHER"}'

curl -X POST http://127.0.0.1:8000/demo/inject \
  -H 'Content-Type: application/json' \
  -d '{"target":"station","station_id":"42181","kind":"SPIKE","channel":"temp_c"}'
```

- Storm must target a **cluster**. Hardware (spike / freeze / drift / comm) must target **one station**.
- `GET /demo/status` lists armed overlays. `POST /demo/reset` clears them.
- `demo_injected` on `POST /ingest` is the overlay kind. It is not ground truth for judges.

Poll `/stations` and `/alerts` at ~1 s. Expect two different `pipeline_status` values: cluster storm → `GENUINE_WEATHER`, lone spike → `HARDWARE`. The first station in a storm hour may be `UNKNOWN` until a same-hour neighbor exists.

## Dashboard

Install UI extras, then open the ops console (API + streamer should already be running):

```text
pip install -e ".[ui]"
python scripts/run_dashboard.py
```

Default: http://127.0.0.1:8501 · `SKYGUARD_API` defaults to `http://127.0.0.1:8000`.

**30-second judge script**

1. Four teal markers (clean stream).
2. **Storm on NORTH** → both Delhi markers go amber; Mumbai stays teal. Neighbors agree, not a fault. Health does not crash.
3. **Reset**, then **Break Palam temperature** → only Palam goes red; Safdarjung stays teal.
4. Point at the map: Delhi does not validate Mumbai.

The first station in a storm hour may show `UNKNOWN` until the neighbor lands (~1 s). Weather is amber, never red.

Poll shapes (frozen in [docs/contracts.md](docs/contracts.md)). No SSE. The dashboard does not invent fields.

| Method | Path | Use |
|---|---|---|
| `GET` | `/healthz` | `{ "ok": true }` |
| `GET` | `/stations` | map markers: id, name, lat/lon, `cluster_id`, `health_score`, `status` |
| `GET` | `/stations/{id}` | summary + `latest` ingest result (`pipeline_status` for marker color) |
| `GET` | `/stations/{id}/telemetry?from=&to=&limit=` | observed + imputed series. `is_anomaly` is true only for `HARDWARE` |
| `GET` | `/alerts?station_id=&limit=` | newest first — verdict sentence |
| `GET` | `/demo/status` | armed overlays |

`GENUINE_WEATHER` is an alert but it is not `is_anomaly` and it does not lower health. Raw `temp_observed` / `pres_observed` / `rhum_observed` are immutable; imputed columns are overlays.

## ML

Train only on complete windows from `data/processed/{station_id}.clean.parquet` (or drop-null rows from `{station_id}.parquet`). **Do not train on** `data/eval/labeled.parquet` — that file is labeled evaluation (10k rows, 15% injected).

To build a labeled **eval** CSV (injected faults + graph), send ML **one file**: `scripts/simulate_corruption_eval.py`. **Do not train on that CSV** — train on `*.clean.parquet`.

```text
python scripts/simulate_corruption_eval.py --clean test_2024.csv --out ./eval_out
```

Implement `Detector` against [docs/contracts.md](docs/contracts.md) § Detector (`src/skyguard/ml/protocol.py`):

- `window` shape `(N, 3)`, oldest → newest, original units, order `[temp_c, pres_hpa, rhum_pct]`, no NaNs
- MinMax scaling belongs **inside** the real detector, not in the route
- Return `Reconstruction` (`reconstructed` shape `(3,)` in original units, `mse`, `mse_vector`, `contribution_pct` summing to 100, `skipped`)

Until a `.pt` / ONNX file exists, the API uses `IdentityDetector` (copy last step, MSE 0). When weights land: put the file on disk, implement `load_detector` in `src/skyguard/ml/loader.py`, set `MODEL_PATH`, and set a real `SKYGUARD_RECON_THRESHOLD`. Ingest already calls `Detector.reconstruct` on a full 24-hour window.

## Docs

Read [docs/README.md](docs/README.md) before changing behavior. If code and contracts disagree, update `docs/contracts.md` in the same change.
