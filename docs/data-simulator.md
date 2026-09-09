# Data engine and simulator

Owner: data + simulator. Output is files on disk plus a clean HTTP stream. Fault math is shared with the backend via `skyguard.data.inject`.

## Goal

1. A locked catalog of 5 complete Indian stations in 2 clusters
2. Clean hourly parquet the ML person can train on
3. A labeled eval set with a known 15% anomaly mix
4. A streamer that seeds windows, then POSTs clean hours at demo speed

## Source

- Library: `meteostat`
- Variables at the fetch boundary: `temp`, `pres`, `rhum` → map immediately to `temp_c`, `pres_hpa`, `rhum_pct`
- Resolution: hourly
- Geography: India only, seed list first (decision D2)

## Seed inventory

Use Meteostat station search around these anchors. IDs below are **candidates** — the catalog script must resolve and verify them, not assume they exist.

| Anchor | Approx lat, lon | Desired cluster | How many keepers |
|---|---|---|---|
| Delhi NCR | 28.57, 77.12 | NORTH | 3 |
| Mumbai | 19.09, 72.87 | WEST | 1–2 |
| Pune | 18.58, 73.92 | WEST | 0–1 |

Search radius 80 km around each anchor. Pull hourly data. Drop a station if any of T/P/H completeness < 85% on **2018-01-01 → 2024-12-31**. Completeness = non-null count / expected hours in that range.

If WEST cannot produce 2 keepers within 150 km of each other, put all 5 keepers in NORTH (still 2+ stations so buddy check works). Write the decision into `stations.json` as `notes`.

## Catalog file

`data/processed/stations.json`

```json
{
  "generated_at": "2026-09-06T12:00:00Z",
  "stations": [
    {
      "station_id": "42182",
      "name": "Delhi Palam",
      "latitude": 28.5667,
      "longitude": 77.1167,
      "elevation_m": 216,
      "cluster_id": "NORTH",
      "completeness": {"temp_c": 0.93, "pres_hpa": 0.91, "rhum_pct": 0.90}
    }
  ]
}
```

`station_id` is the Meteostat/WMO id string. Backend boots by upserting this file into `stations`.

## Persist clean series

One parquet per station: `data/processed/{station_id}.parquet`

Columns: `timestamp` (UTC), `temp_c`, `pres_hpa`, `rhum_pct`. Sorted ascending. Do not interpolate gaps. Leave nulls — they are real comms gaps and become `COMM_ERROR` when streamed if we choose to pass them through. For **ML training export**, write a second file `data/processed/{station_id}.clean.parquet` that drops any row with a null (ML asked for complete windows).

Do not inject faults into `processed/`. Injection is a separate step.

## Injection library

`src/skyguard/data/inject.py` — pure functions, no I/O, no FastAPI imports.

Use the signatures in [contracts.md](contracts.md). Add helpers the backend demo controller needs:

```python
def apply_live(
    kind: FaultType,
    observation: Observation,
    channel: Channel | None,
    hour_index: int,
    std_dev: dict[Channel, float],
) -> Observation:
    ...
```

`hour_index` is how many hours this overlay has already been applied (0-based). Freeze holds the first observed value. Drift uses `slope * hour_index`. Storm ignores `channel` and mutates all three.

Determinism: accept an optional `rng: np.random.Generator`. Eval set builder passes a seeded generator (`seed=26073`). Live demo may be random.

## Eval set

`scripts/build_evalset.py` → `data/eval/labeled.parquet`

Target (blueprint): **10,000 hourly rows**, **15% anomalous**.

Suggested mix of the 15% (1,500 rows). Remaining 8,500 stay clean, including some real extremes if the source has them.

| Label | Share of anomalies | How |
|---|---|---|
| `SPIKE` | 25% | one channel, one hour |
| `FREEZE` | 20% | 12-hour blocks, one channel |
| `DRIFT` | 15% | 48-hour blocks, one channel |
| `COMM_ERROR` | 15% | null one or all channels |
| `GENUINE_WEATHER` | 25% | `inject_storm` on **all stations in that cluster at that hour** |

Columns:

```
station_id, timestamp, temp_c, pres_hpa, rhum_pct,
temp_c_raw, pres_hpa_raw, rhum_pct_raw,
fault_type, channel, is_anomaly
```

`is_anomaly` is true only for hardware-like labels (`SPIKE`, `FREEZE`, `DRIFT`, `COMM_ERROR`). `GENUINE_WEATHER` has `is_anomaly=false` so false-positive rate is measured correctly.

Never train the autoencoder on the eval file. Train on `*.clean.parquet` only.

## ML eval script (does not change the streamer)

Send **one file** to ML: [`scripts/simulate_corruption_eval.py`](../scripts/simulate_corruption_eval.py).

It does not import SkyGuard and does not change the live simulator. Needs pandas, numpy, matplotlib.

**This output is an eval set. Do not train on it.** Train on clean hours (`*.clean.parquet`).

```text
python scripts/simulate_corruption_eval.py --clean test_2024.csv --out ./eval_out
```

Writes `labeled_eval_seed42.csv` (original + corrupted + `fault_type`) and a PNG of the mix / traces. Notebook: `simulate_corruption(test_clean, seed=42)`.

## Streamer

`scripts/run_stream.py` / `skyguard.data.stream`

1. Load `stations.json` + processed parquet
2. Wait until `GET /healthz` is ok
3. For each station, `POST /seed` with the 24 hours **before** `demo_start`
4. Walk hours from `demo_start` onward
5. Each tick, POST `/ingest` for every station (same timestamp), then sleep `SKYGUARD_STREAM_MS`

Default `demo_start`: first timestamp in the eval/demo range that exists on all five stations.

CLI:

```text
python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 --start 2024-07-01T00:00:00Z
```

The streamer does **not** take `--fault`. Live faults go through `/demo/inject`.

If `/ingest` returns 409 (duplicate hour), log and skip. Do not crash the demo.

## What “done” looks like for this workstream

- `stations.json` with 5 stations, cluster ids, completeness stats
- Parquet on disk, inspectable in a notebook or `pandas`
- `inject.py` unit tests for all 5 injectors (storm moves T↓ P↓ H↑ together)
- `labeled.parquet` with the 15% mix and a printed class histogram
- Streamer seeds + plays clean data into a running API
- README snippet in this file is enough for ML and frontend to find the files

## Out of scope

- Training
- Plotting (frontend)
- Applying faults inside the streamer
