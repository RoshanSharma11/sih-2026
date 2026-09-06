# Contracts

Do not invent field names. If you need a new field, add it here first.

All timestamps are UTC ISO-8601 with `Z` (`2024-07-01T00:00:00Z`). All floats are JSON numbers, not strings.

## Enums

```text
FaultType     = SPIKE | FREEZE | DRIFT | COMM_ERROR | PHYSICS_BREACH
                | GENUINE_WEATHER | UNKNOWN
Severity      = LOW | MEDIUM | HIGH | CRITICAL
StationStatus = HEALTHY | DEGRADED | CRITICAL
PipelineStatus= CLEAN | GENUINE_WEATHER | HARDWARE | UNKNOWN
Channel       = temp_c | pres_hpa | rhum_pct
ClusterId     = NORTH | WEST
```

## Ingest payload (simulator → backend)

`POST /ingest`

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
| `station_id` | string | yes | Catalog id |
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

Seed rows are **clean**, written to `telemetry_logs` with `is_anomaly=false`, and used only to fill the window. No alerts. Max 48 rows per call.

## Ingest result

```json
{
  "station_id": "42182",
  "timestamp": "2024-07-01T14:00:00Z",
  "pipeline_status": "HARDWARE",
  "fault_type": "SPIKE",
  "confidence": 0.984,
  "severity": "HIGH",
  "explainability_text": "Temperature contributed 94.1% of reconstruction error. Expected 28.4°C given pressure 1008.0 hPa and humidity 78%, but received 48.1°C.",
  "contribution_pct": {"temp_c": 94.1, "pres_hpa": 3.2, "rhum_pct": 2.7},
  "observed": {"temp_c": 48.1, "pres_hpa": 1008.0, "rhum_pct": 78.0},
  "imputed": {"temp_c": 28.4, "pres_hpa": 1008.0, "rhum_pct": 78.0},
  "mse": 0.41,
  "mse_vector": {"temp_c": 1.20, "pres_hpa": 0.01, "rhum_pct": 0.02},
  "health_score": 88.0,
  "station_status": "HEALTHY",
  "demo_injected": null
}
```

`demo_injected` is `null` or a `FaultType` / `GENUINE_WEATHER` the DemoController applied. It is never shown as ground truth to judges unless we are on an eval page.

## Demo inject

`POST /demo/inject`

```json
{
  "target": "station",
  "station_id": "42182",
  "cluster_id": null,
  "kind": "SPIKE",
  "channel": "temp_c",
  "duration_hours": 1
}
```

| Field | Rules |
|---|---|
| `target` | `station` \| `cluster` |
| `kind` | `SPIKE` \| `FREEZE` \| `DRIFT` \| `COMM_ERROR` \| `GENUINE_WEATHER` |
| `channel` | required for SPIKE/FREEZE/DRIFT; ignored for COMM_ERROR and GENUINE_WEATHER |
| `duration_hours` | default 1 (spike/comm), 12 (freeze), 48 (drift), 3 (storm) |
| Storm | `target` must be `cluster` |

`POST /demo/reset` — clear all armed overlays.

## Query APIs (frontend)

| Method | Path | Returns |
|---|---|---|
| `GET` | `/healthz` | `{"ok": true}` |
| `GET` | `/stations` | list of station summaries |
| `GET` | `/stations/{id}` | summary + latest observation |
| `GET` | `/stations/{id}/telemetry?from=&to=&limit=` | raw + imputed series |
| `GET` | `/alerts?station_id=&limit=` | newest first |
| `GET` | `/demo/status` | armed overlays |

Station summary:

```json
{
  "station_id": "42182",
  "name": "Delhi Palam",
  "latitude": 28.57,
  "longitude": 77.12,
  "elevation_m": 216.0,
  "cluster_id": "NORTH",
  "health_score": 88.0,
  "status": "HEALTHY"
}
```

## Detector interface (ML boundary)

```python
from typing import Protocol
import numpy as np

class Reconstruction:
    reconstructed: np.ndarray   # shape (3,) latest step, original units
    mse: float                  # mean of mse_vector
    mse_vector: np.ndarray      # shape (3,) order [temp_c, pres_hpa, rhum_pct]
    contribution_pct: np.ndarray  # shape (3,), sums to 100 (0 if mse==0)
    skipped: bool               # True if window too short / contains NaN

class Detector(Protocol):
    def reconstruct(self, window: np.ndarray) -> Reconstruction:
        """window: shape (N, 3), oldest→newest, original units, no NaNs."""
```

`IdentityDetector.reconstruct` sets `reconstructed = window[-1]`, `mse = 0`, `contribution_pct = [0,0,0]`.

Window contract: backend MinMax-scales **inside the real detector**, not in the route. The stub does no scaling. Order is always `[temp_c, pres_hpa, rhum_pct]`.

## Database

```sql
CREATE TABLE stations (
  station_id   VARCHAR(20) PRIMARY KEY,
  name         VARCHAR(100) NOT NULL,
  latitude     REAL NOT NULL,
  longitude    REAL NOT NULL,
  elevation_m  REAL,
  cluster_id   VARCHAR(20) NOT NULL,
  health_score REAL NOT NULL DEFAULT 100.0,
  status       VARCHAR(20) NOT NULL DEFAULT 'HEALTHY'
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
  pipeline_status VARCHAR(20) NOT NULL DEFAULT 'CLEAN',
  mse             REAL,
  UNIQUE (station_id, timestamp)
);

CREATE TABLE anomaly_alerts (
  alert_id             INTEGER PRIMARY KEY AUTOINCREMENT,
  station_id           VARCHAR(20) NOT NULL REFERENCES stations(station_id),
  timestamp            DATETIME NOT NULL,
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

Health weights (7-day window), from the blueprint:

```
health = 100 - (2*F_spike + 3*F_freeze + 5*D_drift + 10*M_missing)
```

`F_spike` / `F_freeze` = counts. `D_drift` = cumulative |buddy residual| in °C-equivalent (clamp contribution). `M_missing` = fraction of expected hours with any null (0–1). Clamp health to `[0, 100]`.

| Health | Status |
|---|---|
| `> 80` | `HEALTHY` |
| `50–80` | `DEGRADED` |
| `< 50` | `CRITICAL` |

## Inject function signatures

```python
def inject_spike(value: float, std_dev: float) -> float:
    # value + sign * U(4, 8) * std_dev

def inject_freeze(series: np.ndarray, start: int, duration: int = 12) -> np.ndarray:
    # series[start:start+duration] = series[start]

def inject_drift(series: np.ndarray, start: int, duration: int = 48, slope: float = 0.1) -> np.ndarray:
    # series[start+i] += slope * i

def inject_comm_error() -> None:
    return None

def inject_storm(temp_c: float, pres_hpa: float, rhum_pct: float) -> tuple[float, float, float]:
    # T -= U(8, 15); P -= U(10, 25); H = min(100, H + U(30, 50))
```

Live demo uses the same functions. Storm is applied to every station in the cluster for `duration_hours`. Drift/freeze persist across successive ingest calls via DemoController state.

## Error responses

| HTTP | When |
|---|---|
| 422 | Schema violation |
| 404 | Unknown `station_id` |
| 409 | Duplicate `(station_id, timestamp)` ingest |
| 400 | Storm inject targeting a single station; missing channel on SPIKE |

Duplicate timestamps: do not silently overwrite. The streamer must be deterministic.
