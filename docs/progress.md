# Progress — SkyGuard (SIH PS 26073)

Last updated: 2026-09-06 (after Slice 4).

Update this file when a slice lands or a lock changes. It is the handoff note for a new chat. Contracts and decisions still live in the other `docs/` files; this file only answers “where are we?”

## Status

**Done through Slice 4.** Next work is **Slice 5 — demo control**.

Working tree should be clean on `main` after each slice. Latest commits:

| Slice | Commit | Why |
|---|---|---|
| 0 | `c684382` | Package skeleton, frozen schemas, `IdentityDetector` |
| 1a | `8d7cb71` | Locked catalog + completeness filter |
| 1b | `bbf0f44` | SQLite persist-only API |
| 2a | `0edca2c` | Shared `inject.py` + 10k eval set |
| 2b | `6ee8d7d` | 24h windows, seed, Tier 1 |
| 3 | `d16ea51` | Clean streamer |
| 4 | `7c61604` | Cluster buddy check, classifier, health |

## What works

- Catalog: **four** stations (not five). Completeness bar dropped a fifth. Buddy check still works inside each cluster.
  - NORTH: `42181` Palam, `42182` Safdarjung
  - WEST: `43003` Santacruz, `43057` Colaba
- Fetch: `python -m skyguard.data.fetch` → `data/processed/stations.json` + parquet (parquet is gitignored).
- Inject library + eval builder. Streamer does **not** take `--fault`.
- API: `/healthz`, `/stations`, `/telemetry`, `/alerts`, `POST /ingest`, `POST /stations/{id}/seed`.
- Pipeline: persist raw → Tier 1 → cluster IDW buddy → classify → 7-day health. No ML. `IdentityDetector` only.
- Storm on both stations in a cluster at the same hour → `GENUINE_WEATHER`. Lone spike vs a static neighbor → `HARDWARE` / `SPIKE`. No neighbor → `UNKNOWN` (D11). Weather alerts do not lower health.
- Streamer: seed 24h before `demo_start` (default 2024-07-01Z), then POST every station each hour, sleep `SKYGUARD_STREAM_MS` (200). `409` is skipped, not a crash.

## What is still a stub

| Slice | Files | Notes |
|---|---|---|
| 5 | `engine/demo.py`, `api/routes_demo.py` | `/demo/inject`, `/demo/reset`, `/demo/status` not wired in `main.py` |
| 6 | `engine/tier2.py` | No `Detector.reconstruct` on ingest. Imputed columns stay null. `SKYGUARD_RECON_THRESHOLD` default `inf` when added |
| 7 | root README polish, OpenAPI check | Handoff to frontend/ML |

Out of scope unless asked: Streamlit, LSTM training, SSE, Docker, auth.

## Locks that bite implementers

- Fault math only in `skyguard.data.inject`. Live faults belong in the API demo overlay, not the streamer.
- Raw T/P/H are immutable. Imputed is overlay.
- Buddy check is cluster-local, 150 km. Delhi must not validate Mumbai.
- Sequential ingest: the **first** station in a storm hour may be `UNKNOWN` until a same-hour neighbor exists; the **second** is the weather call.
- Freeze is “exactly one channel stuck for 6 hours.” Flat P+H together is not a freeze (avoids false positives on still weather).
- Do not invent API fields. Change `docs/contracts.md` in the same change if you must.

## How to run

Two terminals. `python -m skyguard.api.main` **does not** start uvicorn; it imports the app and exits.

```text
python scripts/run_api.py
# wait for Application startup complete

python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 --start 2024-07-01T00:00:00Z
```

If processed parquet is missing locally (gitignored): `python -m skyguard.data.fetch` first.

`--hours N` on the streamer stops after N weather-hours. Tests: `pytest -q`.

## Next slice (5)

1. `DemoController` in `engine/demo.py`: in-memory overlays, apply `inject.apply_live` **before** detection.
2. Routes: `POST /demo/inject`, `POST /demo/reset`, `GET /demo/status`. Mount them in `main.py`.
3. Storm must target a **cluster**. Hardware (spike/freeze/drift/comm) targets **one station**.
4. Manual: stream clean, inject storm on NORTH, inject temp spike on one NORTH station, confirm two different `pipeline_status` values.
5. `demo_injected` on the ingest result is the overlay kind, not ground truth for judges.
6. Commit Slice 5 before starting Slice 6.

## Open issues

- Real Meteostat parquet may be absent on a fresh clone; fetch is slow (2018–2024 hourly).
- A 2-minute live stream soak against real parquet was not run here; Slice 3/4 used tests + a 120-hour fixture soak.
- If the API was started before Slice 4, restart it so buddy/classify/health load.
