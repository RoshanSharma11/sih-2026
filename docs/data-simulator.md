# Data engine and simulator

Owner: data + simulator. Output is files on disk plus a clean HTTP stream. Fault math is shared with the backend via `skyguard.data.inject`. Catalog and neighbors **match ML** (D14).

## Goal

1. Import ML’s 151-station catalog + buddy graph (not a new 4-station lock)
2. Hourly series those stations can stream (same ids ML has scalers for)
3. A labeled eval set (existing `simulate_corruption_eval.py` path is still valid)
4. A streamer that seeds windows, POSTs clean hours, and honors the **view / ingest** filter (D15)

## Source of truth

Do **not** recrawl Meteostat to pick 5 keepers.

1. Copy ML `data/raw/stations.csv` + `buddy_edges.csv` (+ per-station CSVs if that is how hours are stored) into the working tree (paths below).
2. `python -m skyguard.data.import_ml_catalog` writes `data/processed/stations.json` and `buddy_edges.json`.

```text
python -m skyguard.data.import_ml_catalog
python -m skyguard.data.import_ml_catalog --raw-dir /path/to/ml/data/raw --no-hours
```

Exits with the expected-file list if `stations.csv` is missing. Hourly `{station_id}.csv` files are optional; missing hours are skipped, not invented.
3. Hourly series: prefer ML CSVs mapped to parquet (`timestamp`, `temp_c`, `pres_hpa`, `rhum_pct`). If a station is in the catalog but has no local series, skip it in the streamer and log it — do not invent hours.

`station_id` is the string id in the scaler dict (WMO-like, e.g. `42181`, some ICAO-like `VOPB0`). Backend refuses ids without a scaler.

## Catalog files

`data/processed/stations.json`

```json
{
  "generated_at": "2026-09-09T00:00:00Z",
  "source": "ml/data/raw/stations.csv",
  "n_stations": 151,
  "stations": [
    {
      "station_id": "42181",
      "name": "New Delhi / Palam",
      "latitude": 28.5667,
      "longitude": 77.1167,
      "elevation_m": 220.0,
      "isolate": false,
      "buddy_ids": ["42182"]
    }
  ]
}
```

`data/processed/buddy_edges.json` — list of `{primary_station_id, buddy_station_id, distance_km}`. Isolates = exported stations with fewer than 2 exported buddies (ML rule).

## Persist clean series

One parquet per station: `data/processed/{station_id}.parquet`

Columns: `timestamp` (UTC), `temp_c`, `pres_hpa`, `rhum_pct`. Sorted ascending. Do not interpolate gaps in the file.

Do not inject faults into `processed/`.

## Injection library

`src/skyguard/data/inject.py` — pure functions, no I/O, no FastAPI imports. Signatures in [contracts.md](contracts.md).

Storm live apply: backend expands `station_id` to the neighborhood, then calls `inject_storm` on each.

Eval `is_anomaly`: hardware labels true; `GENUINE_WEATHER` / `STORM` false **for F1 against hardware**. Live telemetry `is_anomaly` follows D18 (weather true). Do not mix those two meanings in one column without naming it.

## ML eval script

[`scripts/simulate_corruption_eval.py`](../scripts/simulate_corruption_eval.py) and the copy under `ml/scripts/` / `ml/eval_out/`. Offline only. **Do not train on it.**

```text
python scripts/simulate_corruption_eval.py --clean test_2024.csv --out ./eval_out
```

## Streamer

`scripts/run_stream.py` / `skyguard.data.stream`

1. Load imported catalog + parquet
2. Resolve **ingest set**: CLI `--stations` (comma ids) and `--with-buddies` (default true), else `GET /demo/stream-filter`
3. Wait until `GET /healthz` is ok and `model_loaded` is true (warn and continue if false — those hours will be `UNCONFIRMED_ANOMALY`)
4. For each station in the ingest set, `POST /seed` with 24 hours **before** `demo_start`
5. Walk hours from `demo_start` onward
6. Each tick, POST `/ingest` for every ingest-set station (same timestamp), then sleep `SKYGUARD_STREAM_MS`

CLI:

```text
python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 --start 2024-07-01T00:00:00Z
python -m skyguard.data.stream --stations 42181,43003 --with-buddies
```

The streamer does **not** take `--fault`. Live faults go through `/demo/inject`.

If `/ingest` returns 409, log and skip. Do not crash the demo.

`--with-buddies` false is allowed for LSTM-only debugging; do not use it in the judge script.

## What “done” looks like for this workstream

- Imported catalog matches ML scaler ids
- Buddy edges match `ml` `build_buddy_graph`
- Streamer can run full catalog or a view∪buddies subset
- `inject.py` still unit-tested
- README in this file is enough to find the files

## Out of scope

- Training
- Plotting (frontend)
- Applying faults inside the streamer
- Recreating the 4-station NORTH/WEST lock
