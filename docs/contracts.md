# Contracts

Do not invent field names. If you need a new field, add it here first.

All timestamps are UTC ISO-8601 with `Z` (`2024-07-01T00:00:00Z`). All floats are JSON numbers, not strings.

Public API uses SkyGuard names (`temp_c`, `pres_hpa`, `rhum_pct`). The ML engine uses `temp`, `rhum`, `pres`. Mapping happens only in the backend adapter.

## Enums

```text
Label         = CLEAN | PHYSICAL_FAULT | GENUINE_WEATHER_EVENT
                 | HARDWARE_ANOMALY | UNCONFIRMED_ANOMALY
PipelineStatus= CLEAN | GENUINE_WEATHER | HARDWARE | UNKNOWN
FaultType     = SPIKE | FREEZE | DRIFT | COMM_ERROR
                | GENUINE_WEATHER | UNKNOWN
Severity      = LOW | MEDIUM | HIGH | CRITICAL
StationStatus = HEALTHY | DEGRADED | CRITICAL
Channel       = temp_c | pres_hpa | rhum_pct
```

`PHYSICS_BREACH` and `ClusterId = NORTH | WEST` are **legacy**. Production QC does not emit them. Storm inject targets a **neighborhood**, not a cluster id.

### Label map (D18)

| `label` | `pipeline_status` | `is_anomaly` | Lowers health? |
|---|---|---|---|
| `CLEAN` | `CLEAN` | false | no |
| `PHYSICAL_FAULT` | `HARDWARE` | true | yes |
| `HARDWARE_ANOMALY` | `HARDWARE` | true | yes |
| `GENUINE_WEATHER_EVENT` | `GENUINE_WEATHER` | true | no |
| `UNCONFIRMED_ANOMALY` | `UNKNOWN` | true | yes |

ML `fault_type` `COMMUNICATION` → public `COMM_ERROR`. ML `null` fault on a non-clean label → `UNKNOWN`.

## Ingest payload (simulator → backend)

`POST /ingest`

The simulator still sends a **single hour**. The backend attaches window + buddies when it calls ML.

```json
{
  "station_id": "42182",
  "timestamp": "2024-07-01T14:00:00Z",
  "temp_c": 34.2,
  "pres_hpa": 1002.4,
  "rhum_pct": 71.0,
  "sequence_id": 140
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `station_id` | string | yes | Must exist in the imported ML catalog and have a scaler |
| `timestamp` | datetime | yes | Observation hour |
| `temp_c` | float \| null | yes | Null = missing channel |
| `pres_hpa` | float \| null | yes | |
| `rhum_pct` | float \| null | yes | |
| `sequence_id` | int | no | Streamer monotonic id, debug only |

Any of the three channels may be null. That is a comms/sensor gap, not a validation error.

## Seed payload

`POST /stations/{station_id}/seed`

```json
{
  "observations": [
    {
      "timestamp": "2024-06-30T15:00:00Z",
      "temp_c": 31.0,
      "pres_hpa": 1004.1,
      "rhum_pct": 68.0
    }
  ]
}
```

Seed rows are **clean**, written to `telemetry_logs` with `label=CLEAN`, `is_anomaly=false`, and used only to fill the window. No alerts. Max 48 rows per call. Duplicate timestamps are skipped so the streamer can retry safely.

Response:

```json
{"station_id": "42181", "accepted": 24, "skipped": 0}
```

## Ingest result

```json
{
  "station_id": "42182",
  "timestamp": "2024-07-01T14:00:00Z",
  "label": "HARDWARE_ANOMALY",
  "pipeline_status": "HARDWARE",
  "fault_type": "SPIKE",
  "confidence": 0.984,
  "severity": "HIGH",
  "explainability_text": "temp observed 48.10 vs predicted 28.40. Neighbors disagree; treated as hardware anomaly.",
  "affected_variables": ["temp_c"],
  "contribution_pct": {"temp_c": 94.1, "pres_hpa": 3.2, "rhum_pct": 2.7},
  "observed": {"temp_c": 48.1, "pres_hpa": 1008.0, "rhum_pct": 78.0},
  "imputed": {"temp_c": 28.4, "pres_hpa": 1008.0, "rhum_pct": 78.0},
  "mse": 0.041,
  "health_score": 88.0,
  "station_status": "HEALTHY",
  "demo_injected": null,
  "imputed_interval": {
    "temp_c": [27.1, 29.6],
    "pres_hpa": [1006.4, 1009.2],
    "rhum_pct": [74.0, 82.0]
  },
  "thermo": {"dewpoint_c": 41.2, "td_minus_t": -6.9, "passed": true},
  "tier1": {"passed": true, "violations": []},
  "tier2": {
    "ran": true,
    "score": 0.041,
    "window_mse": 0.041,
    "threshold": 0.008487,
    "feature_contributions": {"temp_c": 0.941, "rhum_pct": 0.032, "pres_hpa": 0.027}
  },
  "tier3": {
    "performed": true,
    "method": "cw_idw",
    "buddy_ids": ["42181"],
    "usable_count": 2,
    "neighbors_agree": false,
    "reason_skip": null,
    "mix": {"temp_c": 28.1, "pres_hpa": 1008.0, "rhum_pct": 76.0},
    "corr": {"42181": 0.42}
  }
}
```

`demo_injected` is `null` or a `FaultType` / `GENUINE_WEATHER` the DemoController applied. It is never shown as ground truth to judges unless we are on an eval page.

`severity` is derived (not emitted by ML): `PHYSICAL_FAULT`/`HARDWARE_ANOMALY` + high confidence → `HIGH`; weather → `LOW`; unconfirmed → `LOW`/`MEDIUM`.

`contribution_pct` is ML feature shares × 100, keys in public channel names. Order in ML is `temp, rhum, pres`.

`explainability_text` is v2 `reason`. `imputed` is v2 `predicted` (public channel names). `imputed_interval` is the 90% band, or `null` when the overlay is hidden (`CLEAN`, `GENUINE_WEATHER_EVENT`, `UNCONFIRMED_ANOMALY`). `thermo` is dew point, Td−T, and whether that check passed. `tier2.score` is the last-hour-weighted reconstruction score. `tier3.method` is `cw_idw` on the product path. `tier3.mix` is the neighbor blend (not the dashed line). `tier3.corr` maps buddy id → correlation.

`health_score` / `station_status` are recomputed from stored labels over the last 168 hours (seed rows count). `PHYSICAL_FAULT`, `HARDWARE_ANOMALY`, and `UNCONFIRMED_ANOMALY` lower the score. `GENUINE_WEATHER_EVENT` does not. The engine’s in-memory tracker is not the product score.

## Demo inject

`POST /demo/inject`

```json
{
  "target": "station",
  "station_id": "42182",
  "kind": "SPIKE",
  "channel": "temp_c",
  "duration_hours": 1
}
```

| Field | Rules |
|---|---|
| `target` | `station` \| `neighborhood` |
| `kind` | `SPIKE` \| `FREEZE` \| `DRIFT` \| `COMM_ERROR` \| `GENUINE_WEATHER` |
| `channel` | required for SPIKE/FREEZE/DRIFT; ignored for COMM_ERROR and GENUINE_WEATHER |
| `duration_hours` | default 1 (spike/comm), 12 (freeze), 48 (drift), 3 (storm) |
| Storm | `target` must be `neighborhood`; expand `station_id` via buddy graph |
| Hardware | `target` must be `station` |

Legacy body `{target: "cluster", cluster_id: "NORTH"}` is rejected with 400 after I3. Use Palam neighborhood (`42181`) for the storm hero.

`POST /demo/reset` — clear all armed overlays.

## Stream / view filter

`GET /demo/stream-filter`

`POST /demo/stream-filter`

```json
{
  "station_ids": ["42181", "43003"],
  "include_buddies": true
}
```

Response:

```json
{
  "view": ["42181", "43003"],
  "ingest": ["42181", "42182", "43003", "43057"],
  "include_buddies": true
}
```

Empty `station_ids` means all catalog stations (view = ingest = full catalog). Streamer reads this (or CLI `--stations` / `--with-buddies`) and only POSTs the ingest set. Query APIs still *can* return other stations if they have history; the dashboard should pass `ids=` for the view set.

## Query APIs (frontend)

| Method | Path | Returns |
|---|---|---|
| `GET` | `/healthz` | `{ok, model_loaded, threshold, n_stations, n_isolates, v2_artifacts}` |
| `GET` | `/stations?ids=` | list of station summaries (`ids` = view set, optional) |
| `GET` | `/stations/{id}` | summary + latest observation |
| `GET` | `/stations/{id}/telemetry?from=&to=&limit=` | raw + imputed series |
| `GET` | `/alerts?station_id=&limit=` | newest first |
| `GET` | `/demo/status` | armed overlays |
| `GET` | `/demo/stream-filter` | current view + ingest sets |
| `GET` | `/buddy-map` | `{stations, isolates, buddies}` (from ML graph) |

Station summary (list **includes** `latest` so the live map does not N+1):

```json
{
  "station_id": "42182",
  "name": "New Delhi / Safdarjung",
  "latitude": 28.5833,
  "longitude": 77.2,
  "elevation_m": 211.0,
  "aws_id": "55FDD400",
  "aws_name": "SAFDARJUNG",
  "aws_distance_km": 1.631,
  "buddy_ids": [],
  "isolate": true,
  "health_score": 88.0,
  "status": "HEALTHY",
  "latest": {
    "timestamp": "2024-07-01T14:00:00Z",
    "label": "CLEAN",
    "pipeline_status": "CLEAN",
    "observed": {"temp_c": 34.2, "pres_hpa": 1002.4, "rhum_pct": 71.0},
    "imputed": {"temp_c": 34.1, "pres_hpa": 1002.5, "rhum_pct": 70.8}
  }
}
```

`cluster_id` is omitted unless the imported CSV supplies a region tag. QC must not read it. List rows include `buddy_ids`, `isolate`, `aws_id`, `aws_name`, `aws_distance_km`, and `latest` (null until the first seeded or ingested hour).

`aws_id` matches the IMD AWS/ARG `ID`. `aws_distance_km` is the WMO-to-AWS site offset from `stations_judge48.csv` (`distance_km` there). It is not a buddy-edge length. Safdarjung has no buddies inside the live 48, so `buddy_ids` is empty and `isolate` is true.

`/healthz` `v2_artifacts` is `{lstm, overlay, stgnn}`: each flag is true when that weight file loaded. `threshold` is the v2 operating score (`0.008487`). Graph weights may be loaded while ingest still uses `cw_idw`.

Telemetry rows keep observed + imputed columns, plus `explainability_text`, `imputed_interval`, `thermo`, `tier2_score`, `tier3_method`, `tier3_mix`, and `tier3_corr`. `is_anomaly` follows D18. `label` on `telemetry_logs` stores the five-way ML label. Interval and mix use public channel names. `imputed_interval` is `null` when the band is hidden.

`GET /buddy-map` is the ML graph for the dashboard, not a QC input:

```json
{
  "stations": ["42181", "42182", "43003"],
  "isolates": ["43003"],
  "buddies": {
    "42181": ["42182", "42139"],
    "42182": ["42181", "42139"],
    "43003": ["43057"]
  }
}
```

## QC engine boundary (backend → ML)

Not a public HTTP contract. Backend calls in-process:

```python
v2.engine.process_aws_data({
    "station_id": str,
    "timestamp": datetime,  # naive or UTC; v2 coerces naive
    "temp": float | None,
    "rhum": float | None,
    "pres": float | None,
    "window": [{"timestamp", "temp", "rhum", "pres"}, ...],  # 24 rows
    "buddies": [{"station_id", "distance_km", "window": [...]}, ...],
})
```

Load `v2.engine.get_engine(use_stgnn=False, timing_async=True)`. Graph model stays off (`tier3.method = "cw_idw"`). TIMING is queued; the ingest JSON does not wait on it.

Unknown station (not in the product catalog) → 404. In the catalog but no train scaler → 400. Do not borrow another station’s scaler.

Do not send the public `/ingest` body straight into v2 (field names and missing window would break T2/T3). Do not call `ml.engine` on this path.

Legacy `Detector` protocol / `IdentityDetector` / `MODEL_PATH` are not the live path.

## Database

```sql
CREATE TABLE stations (
  station_id   VARCHAR(20) PRIMARY KEY,
  name         VARCHAR(100) NOT NULL,
  latitude     REAL NOT NULL,
  longitude    REAL NOT NULL,
  elevation_m  REAL,
  isolate      BOOLEAN NOT NULL DEFAULT 0,
  aws_id       VARCHAR(32),
  aws_name     VARCHAR(100),
  aws_distance_km REAL,
  health_score REAL NOT NULL DEFAULT 100.0,
  status       VARCHAR(20) NOT NULL DEFAULT 'HEALTHY'
);

CREATE TABLE station_buddies (
  station_id   VARCHAR(20) NOT NULL REFERENCES stations(station_id),
  buddy_id     VARCHAR(20) NOT NULL REFERENCES stations(station_id),
  distance_km  REAL NOT NULL,
  PRIMARY KEY (station_id, buddy_id)
);

CREATE TABLE telemetry_logs (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  station_id      VARCHAR(20) NOT NULL REFERENCES stations(station_id),
  timestamp       DATETIME NOT NULL,
  temp_observed   REAL,
  pres_observed   REAL,
  rhum_observed   REAL,
  temp_imputed    REAL,
  pres_imputed    REAL,
  rhum_imputed    REAL,
  is_anomaly      BOOLEAN NOT NULL DEFAULT 0,
  label           VARCHAR(40) NOT NULL DEFAULT 'CLEAN',
  pipeline_status VARCHAR(20) NOT NULL DEFAULT 'CLEAN',
  mse             REAL,
  explainability_text TEXT,
  imputed_interval TEXT,
  thermo          TEXT,
  tier2_score     REAL,
  tier3_method    VARCHAR(20),
  tier3_mix       TEXT,
  tier3_corr      TEXT,
  UNIQUE (station_id, timestamp)
);

CREATE TABLE anomaly_alerts (
  alert_id             INTEGER PRIMARY KEY AUTOINCREMENT,
  station_id           VARCHAR(20) NOT NULL REFERENCES stations(station_id),
  timestamp            DATETIME NOT NULL,
  label                VARCHAR(40) NOT NULL,
  fault_type           VARCHAR(50) NOT NULL,
  confidence_score     REAL NOT NULL,
  severity             VARCHAR(20) NOT NULL,
  explainability_text  TEXT NOT NULL,
  contribution_temp    REAL,
  contribution_pres    REAL,
  contribution_rhum    REAL
);

CREATE INDEX idx_telemetry_station_time ON telemetry_logs (station_id, timestamp);
CREATE INDEX idx_alerts_station_time ON anomaly_alerts (station_id, timestamp);
```

Drop `cluster_id NOT NULL` on `stations` in the same migration as the catalog import.

`imputed_interval`, `thermo`, `tier3_mix`, and `tier3_corr` are JSON text. `tier3_method` is `cw_idw` on the product path.

Health is recomputed from stored `telemetry_logs.label` over the last 168 hours (7-day flag rate, weather excluded). The v2 in-memory tracker is not this score:

```
index_7d = 1 - flagged_hours / window_hours
health_score = index_7d * 100
```

| index | Status |
|---|---|
| `≥ 0.90` | `HEALTHY` |
| `≥ 0.70` | `DEGRADED` |
| `< 0.70` | `CRITICAL` |

The old `100 - (2*F_spike + …)` formula is legacy.

## Inject function signatures

Unchanged:

```python
def inject_spike(value: float, std_dev: float) -> float: ...
def inject_freeze(series: np.ndarray, start: int, duration: int = 12) -> np.ndarray: ...
def inject_drift(series: np.ndarray, start: int, duration: int = 48, slope: float = 0.1) -> np.ndarray: ...
def inject_comm_error() -> None: ...
def inject_storm(temp_c: float, pres_hpa: float, rhum_pct: float) -> tuple[float, float, float]: ...
```

Live demo uses the same functions. Storm is applied to every station in the **neighborhood** for `duration_hours`.

## Error responses

| HTTP | When |
|---|---|
| 422 | Schema violation |
| 404 | Unknown `station_id` (not in the product catalog) |
| 409 | Duplicate `(station_id, timestamp)` ingest |
| 400 | No train scaler for a catalog station; storm inject targeting a single station; missing channel on SPIKE; legacy `cluster` target |

Duplicate timestamps: do not silently overwrite. The streamer must be deterministic.
