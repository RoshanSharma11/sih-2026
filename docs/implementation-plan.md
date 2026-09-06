# Implementation Plan — Data, Simulator, Backend

### What we are building

A Python package that (1) pulls and locks five complete Indian AWS hourly series in two spatial clusters, (2) injects labeled faults for evaluation, (3) streams clean observations into FastAPI, and (4) runs a 3-tier QC pipeline (range rules → pluggable detector → cluster buddy check) that writes raw+imputed telemetry, alerts, and a 7-day sensor health score. Live judge faults are applied in the API, not in the streamer.

### Language we agreed on

See [context.md](context.md). Short form:

- **Observation** — one station, one hour, T/P/H (null allowed)
- **Anomaly / HARDWARE** — untrusted sensor or comms, not extreme weather
- **Genuine weather** — physically consistent extreme, neighbors agree
- **Reconstruction / imputed** — overlay estimate; raw is never overwritten
- **Cluster** — ≤150 km buddy group; NORTH / WEST
- **Identity detector** — stub so the API ships without weights

### Decisions made

See [decisions.md](decisions.md). Highest impact: two clusters not five metros; clean stream + backend demo overlay; shared `inject.py`; SQLite; REST poll; seed 24h then stream.

### Assumptions

- Meteostat will yield at least three Delhi-area stations with ≥85% T/P/H. If WEST fails, all five go in NORTH.
- Frontend will poll the query APIs as specified; we will not add SSE in v1.
- ML will implement `Detector` against `contracts.md` and drop a file on `MODEL_PATH`.
- 48-hour hackathon: no auth, no Docker, no Postgres, no multi-worker uvicorn.

### How to build it

Do **contracts and package skeleton first**, then the two workstreams in parallel. Do not start Streamlit or training. **Commit after every slice and every finished feature** (`AGENTS.md`).

#### Slice 0 — shared (half day)

1. `pyproject.toml` (Python 3.10+, fastapi, uvicorn, sqlalchemy, pydantic, pandas, numpy, meteostat, pyarrow, httpx, pytest)
2. Package tree exactly as [architecture.md](architecture.md)
3. `schemas.py` copied from [contracts.md](contracts.md)
4. `ml/protocol.py` + `IdentityDetector`
5. Empty tests that import the package

#### Slice 1a — catalog and clean data

1. `catalog.py` + `fetch.py`: seed search, completeness filter, write `stations.json` + parquet
2. Script: `python -m skyguard.data.fetch`
3. Commit `stations.json` once locked; keep parquet in gitignore if large, plus a tiny fixture for tests

#### Slice 1b — API skeleton (parallel with 1a)

1. SQLAlchemy models + `create_all`
2. Upsert catalog on startup (fixture stations if parquet is not fetched yet)
3. `POST /ingest` persist-only + `GET /stations` + `GET /telemetry` + `GET /alerts` + `GET /healthz`
4. 404 unknown station, 409 duplicate hour

#### Slice 2a — inject + eval

1. `inject.py` + unit tests (especially storm correlation and freeze constancy)
2. `evalset.py` → 10k rows, 15% mix, print histogram
3. Do not wire inject into the streamer

#### Slice 2b — Tier 1 + windows + seed

1. `windows.py` deque per station, hydrate on boot
2. `POST /stations/{id}/seed`
3. `tier1.py` wired in pipeline
4. Null → `COMM_ERROR` alert

#### Slice 3 — streamer

1. Seed 24h, then POST all stations per hour, sleep 200 ms
2. Manual test: 2 minutes of clean data, no 500s

#### Slice 4 — Tier 3 + classify + health (still no ML)

1. Haversine + IDW buddy check inside cluster
2. Classifier priority list
3. Health score update
4. Tests: storm+neighbors = weather; lone spike = hardware

#### Slice 5 — demo control

1. `DemoController` + `POST /demo/inject` + `/demo/reset` + `/demo/status`
2. Manual: stream clean, inject storm on NORTH, inject temp spike on one station, confirm two different statuses

#### Slice 6 — Tier 2 hook

1. Call `Detector.reconstruct` when window is full
2. Contribution % + imputed columns
3. Threshold from env (default `inf`)
4. When ML delivers weights: set `MODEL_PATH`, add one integration test

#### Slice 7 — harden for handoff

1. OpenAPI is accurate (FastAPI default docs)
2. README at repo root: how to fetch, run API, run stream, inject
3. Give frontend the three GET shapes; give ML the parquet path and `Detector` protocol

### Parallelism

```
        Slice 0
       /        \
   1a fetch     1b API persist
       \        /
        2a inject   2b tier1+seed
            \       /
             3 streamer
                 |
             4 buddy+health
                 |
             5 demo inject
                 |
             6 detector hook
```

One person can take left (1a, 2a, 3), the other right (1b, 2b, 4, 5, 6), after Slice 0 together.

### Definition of done for this pair

- Five stations catalogued and streamable
- Labeled eval set on disk
- API implements every route in contracts
- Demo can show **storm ≠ broken sensor** with the identity detector
- ML and frontend can work against frozen contracts without asking us
