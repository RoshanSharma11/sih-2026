# Progress — SkyGuard (SIH PS 26073)

Last updated: 2026-09-06 (after Slice 7).

Update this file when a slice lands or a lock changes. It is the handoff note for a new chat. Contracts and decisions still live in the other `docs/` files; this file only answers “where are we?”

## Status

**Done through Slice 7.** Data + backend handoff is complete. Remaining work is owned by ML (`MODEL_PATH`) and frontend (Streamlit).

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
| 5 | `cf19e83` | Live demo overlays on ingest |
| 6 | `81b5937` | Detector hook + imputed overlay |
| 7 | `de9ed33` | Root README + OpenAPI locked to contracts |

## What works

- Catalog: **four** stations (not five). Completeness bar dropped a fifth. Buddy check still works inside each cluster.
  - NORTH: `42181` Palam, `42182` Safdarjung
  - WEST: `43003` Santacruz, `43057` Colaba
- Fetch: `python -m skyguard.data.fetch` → `data/processed/stations.json` + parquet (parquet is gitignored).
- Inject library + eval builder. Streamer does **not** take `--fault`.
- API: `/healthz`, `/stations`, `/telemetry`, `/alerts`, `POST /ingest`, `POST /stations/{id}/seed`, `POST /demo/inject`, `POST /demo/reset`, `GET /demo/status`. OpenAPI at `/docs` matches `docs/contracts.md`.
- Pipeline: persist raw → Tier 1 → `Detector.reconstruct` (full 24h, no nulls) → cluster IDW buddy → classify → 7-day health.
- Detector is `IdentityDetector` until `MODEL_PATH` is set. `SKYGUARD_RECON_THRESHOLD` defaults to `inf`, so the stub never fires. Imputed columns are the reconstruction overlay; observed T/P/H are never overwritten.
- Demo overlays apply `inject.apply_live` **before** detection. Storm targets a cluster; hardware targets one station. `demo_injected` is the overlay kind, not judge ground truth.
- Storm on both stations in a cluster at the same hour → `GENUINE_WEATHER`. Lone spike vs a static neighbor → `HARDWARE`. No neighbor → `UNKNOWN` (D11). Weather alerts do not lower health.
- Streamer: seed 24h before `demo_start` (default 2024-07-01Z), then POST every station each hour, sleep `SKYGUARD_STREAM_MS` (200). `409` is skipped, not a crash, and does not consume overlay hours.
- Root README: fetch, run API, stream, inject, frontend GET shapes, ML parquet + `Detector` protocol.

## What is still a stub

| Owner | Files | Notes |
|---|---|---|
| ML | `ml/loader.py` | `MODEL_PATH` still raises `NotImplementedError`. When weights land: load them, set a real threshold, add one integration test |
| Frontend | Streamlit | Poll `/stations`, `/telemetry`, `/alerts`. Not this pair |

Out of scope unless asked: Streamlit, LSTM training, SSE, Docker, auth.

## Locks that bite implementers

- Fault math only in `skyguard.data.inject`. Live faults belong in the API demo overlay, not the streamer.
- Raw T/P/H are immutable. Imputed is overlay. Demo-mutated values are what ingest persists and detects; the streamer still sent clean data.
- Buddy check is cluster-local, 150 km. Delhi must not validate Mumbai.
- Sequential ingest: the **first** station in a storm hour may be `UNKNOWN` until a same-hour neighbor exists; the **second** is the weather call.
- Freeze is “exactly one channel stuck for 6 hours.” Flat P+H together is not a freeze (avoids false positives on still weather).
- Do not invent API fields. Change `docs/contracts.md` in the same change if you must.

## How to run

See the [root README](../README.md). Short form:

```text
python scripts/run_api.py
python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 --start 2024-07-01T00:00:00Z
```

If processed parquet is missing locally (gitignored): `python -m skyguard.data.fetch` first.

`--hours N` on the streamer stops after N weather-hours. Tests: `pytest -q`.

## Next

This pair has no further implementation-plan slices. If someone asks: Streamlit, LSTM training, or loading `MODEL_PATH`.

## Open issues

- Real Meteostat parquet may be absent on a fresh clone; fetch is slow (2018–2024 hourly).
- A 2-minute live stream soak against real parquet was not run here; Slice 3/4 used tests + a 120-hour fixture soak.
- No `.pt` / ONNX file yet. Leave `MODEL_PATH` unset.
