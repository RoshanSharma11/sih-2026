# Backend

Owner: backend. FastAPI + SQLite + 3-tier engine. Depends on `inject.py` and `Detector`, not on a trained weight file.

## Process

```text
uvicorn skyguard.api.main:app --reload --port 8000
```

On startup:

1. Create tables
2. Upsert `data/processed/stations.json` (if missing, expose `/healthz` but `/ingest` 503s with a clear error)
3. Hydrate 24-hour windows from `telemetry_logs`
4. Load `Detector` via `skyguard.ml.loader` (identity if `MODEL_PATH` empty)

## Pipeline (implementation notes)

`engine/pipeline.py` is the only orchestrator. Routes do not call tiers directly.

### Tier 1 — `tier1.py`

Config, India-first, overridable:

| Check | Fail if |
|---|---|
| Range T | `temp_c < -20` or `> 55` |
| Range P | `pres_hpa < 850` or `> 1050` |
| Range H | `rhum_pct < 0` or `> 100` |
| Step T | `abs(temp_c - prev) > 10` °C / hour |
| Step P | `abs(pres_hpa - prev) > 15` hPa / hour |
| Step H | `abs(rhum_pct - prev) > 50` pp / hour |
| Null | any of T/P/H is null → `COMM_ERROR` |

Step checks run only when the previous hour exists and both values are non-null.

Range/step failure does **not** by itself mean “skip ML”. Still reconstruct if the window is complete, so contribution % is available.

### Tier 2 — `tier2.py`

- Input: window `(n, 3)` with **no NaNs**. If the latest point has a null, skip (`skipped=true`).
- If `n < 24`, skip. Ingest still returns `CLEAN` unless Tier 1 failed.
- Threshold: `SKYGUARD_RECON_THRESHOLD`. Identity detector never exceeds it.
- Imputation = `reconstructed` in original units.

Contribution (hot-path explainability):

\[
\mathrm{Contribution}_i = \frac{(x_i-\hat{x}_i)^2}{\sum_j (x_j-\hat{x}_j)^2} \times 100
\]

If the denominator is 0, contributions are 0.

### Tier 3 — `tier3.py`

Neighbors = other stations with the same `cluster_id` and a reading at this timestamp, or last reading within 3600 s.

IDW on each channel:

\[
\hat{x} = \frac{\sum_i d_i^{-p} x_i}{\sum_i d_i^{-p}}, \quad p=2
\]

`spatial_residual` = max over channels of `|obs - idw|` after dividing by a channel scale (`temp` 1°C, `pres` 1 hPa, `rhum` 1%). Simple and judge-explainable.

Decision, given Tier 2 already “interesting” or Tier 1 failed:

| Neighbors | Residual | Result |
|---|---|---|
| 0 | — | `UNKNOWN` |
| ≥1 | residual **small** and T↓ P↓ H↑ (or the reverse heat-wave shape) | `GENUINE_WEATHER` |
| ≥1 | residual **large** | `HARDWARE` |
| ≥1 | residual small but **single channel** insane, others match neighbors | `HARDWARE` (physics breach / spike) |

Default residual cut: temp 4°C, pres 4 hPa, rhum 15% — any channel over its cut counts as “large.” Tune once we see real neighbor gaps.

Buddy check is also used **asynchronously** for drift: once per ingest, update a 24-hour rolling mean residual per station. If that residual grows monotonically for ≥7 simulated days (or ≥7*24 ingest steps in accelerated demo), classify `DRIFT` even when point MSE is moderate.

### Classifier — `classify.py`

Priority order (first match wins):

1. Any null → `COMM_ERROR`, confidence 0.99, severity `HIGH`
2. Latest 6 window values on the dominant channel have `std == 0` and duration ≥ 6 → `FREEZE`, `HIGH`
3. Dominant channel MSE > 5 × mean of the other two **or** Tier 1 step/range on one channel → `SPIKE`, `HIGH`
4. Rolling buddy residual trend (D4 in blueprint) → `DRIFT`, `MEDIUM`
5. One channel over threshold, other two under a low threshold → `PHYSICS_BREACH`, `HIGH`
6. Pipeline says weather → `GENUINE_WEATHER`, confidence from how small the buddy residual is
7. Else `UNKNOWN`, `LOW`

Dominant channel = `argmax(mse_vector)`. If Tier 2 skipped, use the Tier 1 failing channel.

Explainability sentence template:

```text
{Channel} contributed {pct:.1f}% of reconstruction error. Expected {imputed}{unit} given the other sensors, but received {observed}{unit}.
```

For weather:

```text
Cluster {cluster_id} neighbors agree (IDW residual {residual}). Treated as genuine weather, not a sensor fault.
```

### Health — `health.py`

Recompute from the last 7×24 `telemetry_logs` + `anomaly_alerts` rows after every ingest. Formula in [contracts.md](contracts.md). `GENUINE_WEATHER` does not increment spike/freeze/drift counters.

## Demo controller — `demo.py`

In-memory:

```python
@dataclass
class Overlay:
    kind: FaultType
    station_ids: list[str]
    channel: Channel | None
    remaining_hours: int
    hour_index: int
    freeze_anchor: dict[str, float] | None
```

On each matching ingest, apply `apply_live`, decrement `remaining_hours`, increment `hour_index`. Storm overlay lists every station in the cluster.

This is how the judge panel works without a second streamer.

## Concurrency

One process. Use a `asyncio.Lock` per `station_id` around window update + pipeline so two POSTs cannot interleave. Do not use a global lock (cluster storm should still ingest station-by-station).

## Testing (backend)

Minimum, no GPU:

- Tier 1: null → comms; 65°C → range fail; 12°C step → step fail; 32°C → pass
- Storm-shaped triple change + agreeing neighbor → `GENUINE_WEATHER` (even with IdentityDetector if we drive Tier 3 from magnitude + buddy)
- Single-station +40°C, neighbors static → `HARDWARE` / `SPIKE`
- Freeze 12 equal values → `FREEZE`
- Duplicate timestamp → 409
- Unknown station → 404
- Health drops after repeated spikes, not after a storm alert

**Important:** with `IdentityDetector`, Tier 2 never fires. The storm-vs-spike demo must therefore be **Tier 1 + Tier 3 complete** without ML. That is intentional (D4). When weights land, Tier 2 becomes the main “physics” signal and thresholds get a real value.

## What “done” looks like

- All routes in contracts respond
- SQLite has stations, telemetry, alerts
- Clean streamer can run for 5 minutes without 500s
- `/demo/inject` storm on NORTH and spike on one NORTH station produce different `pipeline_status`
- Frontend can poll `/stations` and `/alerts` with no extra undocumented fields
