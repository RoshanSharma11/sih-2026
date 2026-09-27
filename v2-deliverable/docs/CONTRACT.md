# SkyGuard V2 — teammate contract

This is the **only** I/O document backend and frontend should implement against.  
ML lives in this folder. You persist raw, build windows, call ML, map names, draw the console.

| | |
|---|---|
| Problem | SIH 2026 PS 26073 · MoES / IMD · **software only** |
| Canonical call | `from v2.engine import process_aws_data` |
| Optional HTTP | `uvicorn v2.main:app --port 8001` (same JSON, not the product API) |
| Live map | **48** stations in `v2/data/stations_judge48.csv` |
| Palam `42181` | **Out of the live 48.** Do not default the map to it. |
| Demo cluster | Mumbai `43003 / 43057 / 43002 / 43058` + Safdarjung `42182` |

Worked examples (captured from this engine): [`examples/`](examples/).

---

## 0. Who does what

| You | You own | You do not own |
|---|---|---|
| **Backend** | SQLite (or equivalent); **write raw first**; build 24 h `window` + buddy `window`s; call ML; public HTTP; IMD warning chips | Weights, retraining, calling PyTorch except via `process_aws_data` |
| **Frontend** | Five labels/colors; solid raw / dashed overlay / band; health; reason; TIMING line; map of 48 | Calling ML |
| **ML (this package)** | Labels, overlay, interval, reason, health index, TIMING job | IMD JWT, schema, Streamlit layout |

V1 `ml/` is frozen. New ingest uses **this** package only.

---

## 1. How to call ML

### 1.1 In-process (canonical — use this on the product API)

From the `v2-deliverable/` root (or put it on `PYTHONPATH`):

```python
from v2.engine import process_aws_data, UnknownStationError, get_engine

engine = get_engine()          # loads weights once; CW-IDW; TIMING queued on anomalies
try:
    out = engine.process_aws_data(payload)   # same as process_aws_data(payload)
except UnknownStationError as exc:
    # product HTTP: 400
    ...
```

`payload` is a `dict` (or a Pydantic model with `.model_dump()`). Field names are **ML names**: `temp`, `rhum`, `pres` — not `temp_c`.

`process_aws_data` **never** writes the database. Backend writes raw, then calls this, then writes the ML JSON to a **separate** table/columns.

### 1.2 FastAPI (debug / if you do not embed Python)

```text
cd v2-deliverable
uvicorn v2.main:app --port 8001
```

| Method | Path | Same as |
|---|---|---|
| `POST` | `/ingest` | `process_aws_data` body §2, response §3 |
| `GET` | `/healthz` | artifacts loaded? `stgnn_on`? overlay? |
| `GET` | `/buddy-map` | 151-station graph (filter to live 48 in your API) |
| `GET` | `/stations/{station_id}/timing?ts=` | §6 TIMING poll |

Unknown `station_id` (no train scaler) → **HTTP 400**. Do not borrow another station’s scaler.

Product `/ingest` on port 8000 is **yours**. Do not make the dashboard call 8001 in production; embed `process_aws_data` in the same process that holds SQLite.

### 1.3 What this engine is configured to do on ingest

| | Product (`get_engine()` / `POST /ingest`) | `python -m v2.demo_engine` |
|---|---|---|
| Tier 3 | **CW-IDW** (`tier3.method = "cw_idw"`) | GAT (`"stgnn"`) for Mumbai 2 vs 3 |
| Overlay | Gaussian last-hour if HARDWARE / PHYSICAL | same |
| `timing` on first JSON | always `null` | always `null` |
| TIMING job | queued when `is_anomaly` | queued; demo prints poll |

Backend playback of stories 2 vs 3 **works on CW-IDW**. You do not need GAT on the product path.

---

## 2. Input JSON (exact)

Send **UTC**. `Z` is fine. Engine returns naive `YYYY-MM-DDTHH:MM:SS`; re-emit `Z` on your public API.

Any of `temp` / `rhum` / `pres` may be JSON `null` (comms gap). That is **not** HTTP 422.

`window` **must** be sent in demo/playback so runs are deterministic. 24 hourly rows, **oldest → newest**, last row = ingest `timestamp`. Extra rows ignored. Gaps > 2 h → `UNCONFIRMED_ANOMALY`.

`buddies` = 1-hop neighbors that **you also ingested**. Attach each buddy’s own 24 h window ending at the same hour (±1 h tolerated). `distance_km` optional; ML fills from `buddy_edges.csv`.

```json
{
  "station_id": "43003",
  "timestamp": "2024-12-31T23:00:00Z",
  "temp": 26.0,
  "rhum": 65.0,
  "pres": 1013.0,
  "window": [
    {
      "timestamp": "2024-12-31T00:00:00Z",
      "temp": 22.0,
      "rhum": 86.0,
      "pres": 1013.7
    },
    {
      "timestamp": "2024-12-31T23:00:00Z",
      "temp": 26.0,
      "rhum": 65.0,
      "pres": 1013.0
    }
  ],
  "buddies": [
    {
      "station_id": "43057",
      "distance_km": 24.35,
      "window": []
    }
  ]
}
```

Full 24-row request: [`examples/ingest_request_clean.json`](examples/ingest_request_clean.json).

### Backend pipeline (order is mandatory)

1. **Insert the raw row** (T/P/H as received, including nulls). Never update this row with overlay later.
2. Load last 24 hourly points for `station_id` ending at `timestamp` (you may interpolate ≤ 2 h gaps; ML also interpolates ≤ 2 h).
3. Load buddies from `v2/data/buddy_edges.csv` whose ids are **in your ingest set**. Attach windows.
4. Call `process_aws_data`.
5. Persist the ML JSON in **separate** columns (`predicted_*`, `label`, `imputed_interval`, `health`, …).
6. Optional: attach `imd_corroboration` **after** ML. Never as a model feature.
7. If `is_anomaly`, poll TIMING (§6) and store it on the same hour.

**Ingest the Mumbai four together** (`43003`, `43057`, `43002`, `43058`) or stories 2 vs 3 become `UNCONFIRMED` (Tier 3 needs ≥ 2 usable buddies).

Safdarjung `42182` has **0 buddies inside the live 48**. LSTM-suspicious hours there will be `UNCONFIRMED_ANOMALY`. Freeze/comms still fire as `PHYSICAL_FAULT` without neighbors.

---

## 3. Output JSON (exact)

Every `process_aws_data` / `POST /ingest` returns this shape. First response always has `"timing": null`.

### 3.1 CLEAN

[`examples/ingest_response_clean.json`](examples/ingest_response_clean.json)

```json
{
  "station_id": "43003",
  "timestamp": "2024-12-31T23:00:00",
  "observed": { "temp": 26.0, "rhum": 65.0, "pres": 1013.0 },
  "predicted": { "temp": 26.0, "rhum": 65.0, "pres": 1013.0 },
  "reconstructed": { "temp": 26.0, "rhum": 65.0, "pres": 1013.0 },
  "imputed_interval": null,
  "is_anomaly": false,
  "confidence": 0.0,
  "label": "CLEAN",
  "fault_type": null,
  "affected_variables": [],
  "reason": "Last-hour-weighted reconstruction within the frozen 2023 threshold.",
  "thermo": { "dewpoint_c": 18.899, "td_minus_t": -7.101, "passed": true },
  "tier1": { "passed": true, "violations": [] },
  "tier2": {
    "ran": true,
    "score": 0.0041164281778037545,
    "window_mse": 0.0030628456734120846,
    "threshold": 0.008487140408717099,
    "feature_contributions": { "temp": 0.6007, "rhum": 0.3375, "pres": 0.0619 }
  },
  "tier3": {
    "performed": false,
    "method": "cw_idw",
    "neighbors_agree": null,
    "reason_skip": "not_required"
  },
  "timing": null,
  "health": { "index_7d": 1.0, "state": "HEALTHY", "window_hours": 1 }
}
```

On CLEAN / WEATHER, `predicted` **copies observed**. Hide the dashed line.

### 3.2 HARDWARE (55 °C on Santa Cruz only) — overlay ON

[`examples/ingest_response_hardware.json`](examples/ingest_response_hardware.json)

```json
{
  "label": "HARDWARE_ANOMALY",
  "fault_type": "SPIKE",
  "is_anomaly": true,
  "confidence": 1.0,
  "observed": { "temp": 55.0, "rhum": 95.0, "pres": 980.0 },
  "predicted": { "temp": 25.24, "rhum": 69.07, "pres": 1013.29 },
  "reconstructed": { "temp": 25.24, "rhum": 69.07, "pres": 1013.29 },
  "imputed_interval": {
    "temp": [24.20, 26.28],
    "rhum": [61.94, 76.20],
    "pres": [1012.70, 1013.88]
  },
  "reason": "temp observed 55.00 vs predicted 25.24. Neighbor mix 24.40 (n=3). Neighbors disagree; treated as hardware anomaly.",
  "tier3": {
    "performed": true,
    "method": "cw_idw",
    "neighbors_agree": false,
    "usable_count": 3,
    "buddy_ids": ["43057", "43002", "43058"],
    "mix": { "temp": 24.40, "rhum": 77.00, "pres": 1012.80 }
  },
  "timing": null
}
```

Solid line = 55 °C. Dashed = ~25.2 °C. Band = `imputed_interval`. Raw row in DB stays 55.

### 3.3 WEATHER (same +8 °C on Santa Cruz + Colaba + Juhu) — overlay OFF

[`examples/ingest_response_weather.json`](examples/ingest_response_weather.json)

```json
{
  "label": "GENUINE_WEATHER_EVENT",
  "fault_type": "STORM",
  "is_anomaly": true,
  "observed": { "temp": 34.0, "rhum": 65.0, "pres": 1013.0 },
  "predicted": { "temp": 34.0, "rhum": 65.0, "pres": 1013.0 },
  "imputed_interval": null,
  "tier3": {
    "performed": true,
    "method": "cw_idw",
    "neighbors_agree": true,
    "usable_count": 3
  },
  "timing": null
}
```

Amber, **not** red. `imputed_interval` is `null` — **no dashed line, no band**. Health must **not** drop because of this label (see §4).

---

## 4. Name map (ML → public API / UI)

| Public | ML |
|---|---|
| `temp_c` | `temp` |
| `rhum_pct` | `rhum` |
| `pres_hpa` | `pres` |
| `explainability_text` | `reason` |
| `imputed` | `predicted` (same object as `reconstructed`) |
| `health_score` | `health.index_7d * 100` |
| `station_status` | `health.state` |
| `pipeline_status` | from the label table below |
| `contribution_pct` | `tier2.feature_contributions` × 100 |

### Labels — do not invent more

| ML `label` | `pipeline_status` | `is_anomaly` | Lowers 7d health? | Color | Overlay |
|---|---|---|---|---|---|
| `CLEAN` | `CLEAN` | false | no | teal `#0D9488` | **none** — `predicted` = observed, interval `null` |
| `PHYSICAL_FAULT` | `HARDWARE` | true | **yes** | rose `#E11D48` | dashed + band if interval present |
| `HARDWARE_ANOMALY` | `HARDWARE` | true | **yes** | rose `#E11D48` | dashed + band |
| `GENUINE_WEATHER_EVENT` | `GENUINE_WEATHER` | true | **no** | amber `#D97706` | **none** |
| `UNCONFIRMED_ANOMALY` | `UNKNOWN` | true | **yes** | slate `#64748B` | LSTM last step if present; **no band** |

**Weather is never red.** `is_anomaly` is true for weather (it is unusual). Health ignores weather. Do not mix those two in one badge.

`fault_type` when anomalous: `SPIKE` | `FREEZE` | `DRIFT` | `COMMUNICATION` | `THERMO` | `STORM` | `UNCONFIRMED`.

Health: `HEALTHY` if `index_7d ≥ 0.90`, `DEGRADED` if `≥ 0.70`, else `CRITICAL`.

---

## 5. Overlay — what to draw, where, how

Solid line is **always** `observed` (raw). You never overwrite it.

| `label` | Dashed line (`predicted`) | Band (`imputed_interval`) |
|---|---|---|
| `CLEAN` | hide (equal to solid) | hide |
| `GENUINE_WEATHER_EVENT` | hide (equal to solid) | hide |
| `HARDWARE_ANOMALY` | show corrected last hour | show `[low, high]` per channel when non-null |
| `PHYSICAL_FAULT` | show if values non-null | show if non-null |
| `UNCONFIRMED_ANOMALY` | show LSTM last step if present | **hide** (interval is `null`) |

`imputed_interval.temp` is `[p05, p95]` in °C (same for RH % and P hPa). Missing channel → that key may be absent or the predicted channel `null` (comms).

**Station chart (required)**

- X = time, three panels or three series: T, RH, P.
- Solid = `observed.*`
- Dashed = `predicted.*` **only** when the overlay table says show.
- Shaded band = `imputed_interval` **only** when that object is not `null`.
- Last hour is the ingest hour; previous hours are raw history (no overlay on old hours unless you stored per-hour ML).

**Do not** plot neighbor mix as the dashed line. Mix is for the root-cause table (`tier3.mix`).

---

## 6. TIMING — what to draw, where, how

First ingest JSON: `"timing": null`. Do not block UI on it.

**Poll**

```http
GET /stations/43003/timing?ts=2024-12-31T23:00:00Z
```

Optional `wait_s` ≤ 10.

[`examples/timing_response.json`](examples/timing_response.json)

```json
{
  "station_id": "43003",
  "timestamp": "2024-12-31T23:00:00",
  "status": "ready",
  "timing": {
    "start_hour_in_window": 22,
    "channel_attr": { "temp": 0.5012, "rhum": 0.1683, "pres": 0.3305 },
    "hour_attr": [0.0097, 0.0117, "...", 0.4978],
    "reason": "Anomaly attribution starts at hour 22 of the 24 h window (mostly temp)."
  }
}
```

| `status` | UI |
|---|---|
| `pending` | hide TIMING line; poll 1–2 s |
| `ready` | show `timing.reason` |
| `not_requested` | CLEAN hours are not queued — hide |
| `error` | hide; keep `reason` from ingest |

**Where:** root-cause page, **under** the contribution bars, not on the map.

**How:**

1. One sentence: `timing.reason` (or “Anomaly starts at hour {start_hour_in_window} of the 24 h window”).
2. Optional small bar chart: `timing.hour_attr` (length 24, hours 0 = oldest … 23 = ingest hour).
3. Optional second bars: `timing.channel_attr` (already similar to `tier2.feature_contributions`; prefer ingest contributions as the main bars, TIMING as the *when*).

Never run TIMING on the ingest hot path yourself. Never fail ingest if TIMING is pending.

---

## 7. Frontend surfaces (must-show for product coverage)

Keep the five-page console. Additive only.

### 7.1 Map / network

- Markers = live **48** ids from `stations_judge48.csv` (lat/lon in that file).
- Default camera: Mumbai four + Safdarjung. **Not Palam.**
- Marker color = latest `label` color (§4).
- Draw 1-hop edges from `/buddy-map` ∩ stations you actually ingest.
- Isolates (degree &lt; 2 in the *ingested* set): slate tooltip “not enough neighbors for weather vs hardware”.

### 7.2 Station chart

§5 overlay rules. Title = IMD/Meteostat name from catalog. Subtitle = `station_id`.

### 7.3 Alerts feed

One row per anomalous hour, newest first.

| Column | Source |
|---|---|
| Color chip | §4 |
| Station | name + id |
| Time | timestamp `Z` |
| Verdict | `label` |
| Fault | `fault_type` |
| Sentence | `reason` |

Amber weather and rose hardware must be visually distinct in the same list.

### 7.4 Root cause (this is the XAI page)

Must show, in this order:

1. `reason` (full sentence).
2. Physics card: `thermo.dewpoint_c`, `thermo.td_minus_t`, `tier1.violations`.
3. Last-hour bars: `tier2.feature_contributions`.
4. Neighbor table: `tier3.buddy_ids`, `tier3.corr`, `tier3.mix`, `tier3.neighbors_agree`, `tier3.method`, `tier3.usable_count`.
5. TIMING line when `status=ready` (§6).
6. Optional IMD chip: backend-only `imd_corroboration` on amber rows. ML does not produce this.

### 7.5 Health

- Gauge or number: `health_score` 0–100.
- State chip: `HEALTHY` / `DEGRADED` / `CRITICAL`.
- Copy: “7-day sensor flag rate. Genuine weather does not count.”

---

## 8. Product HTTP (backend, not ML)

ML FastAPI on 8001 is optional. The **product** API you already have should keep:

| Method | Path | Notes |
|---|---|---|
| `POST` | `/ingest` | persist raw + ML; public names |
| `GET` | `/healthz` | include `v2_artifacts: { lstm, overlay, stgnn }` |
| `GET` | `/stations/{id}/telemetry` | observed + overlay columns; hide band if null |
| `GET` | `/stations/{id}/timing?ts=` | proxy ML cache or your DB |
| `GET` | `/buddy-map` | live-48 ∩ edges |
| `GET` | `/alerts` | newest first |
| `POST` | `/demo/inject` | arm story overlays **in your DB**, then ingest hours |

Duplicate hour → 409 (your rule). Schema fail → 422. Unknown live station you refuse to show → 404 is fine **after** you decide; ML itself returns 400 if there is no scaler.

---

## 9. Demo stories you must be able to play back

Hourly playback → one ingest per hour. Inject in **backend demo**, not by editing raw after the fact.

Use `v2/data/demo_windows.json` (24 aligned hours ending `2024-12-31T23:00:00` for the five demo ids) or `python -m v2.demo_engine` from this folder.

| # | Send | Expect |
|---|---|---|
| 1 | `43003` clean 24 h + 3 Mumbai buddies | `CLEAN`, no overlay |
| 2 | last hour `43003` → 55 °C / 95% / 980 hPa; buddies **normal** | `HARDWARE_ANOMALY`, dashed ~25 °C, band on |
| 3 | last hour **+8 °C** on `43003` **and** `43057` **and** `43002` (Juhu too) | `GENUINE_WEATHER_EVENT`, no overlay, health **not** down from this label |
| 4 | temp frozen **12 h** | `PHYSICAL_FAULT` / `FREEZE`, overlay if imputable |
| 5 | `temp: null` | `PHYSICAL_FAULT` / `COMMUNICATION` |
| 6 | repeat story 2 across many hours | `health.state` leaves `HEALTHY` |

Story 2 vs 3 is the PS example. If 2 and 3 look the same, you dropped buddies.

---

## 10. Locked rules (do not “fix” in UI)

- Raw is immutable. Overlay is a second series.
- Weather is amber, never red, and does not lower health.
- Unconfirmed = we refused to guess (not “model crashed”).
- Live set is 48, not 151. Training was 151.
- Do not call IMD from ML. Warning chips are backend-only.
- Do not retune thresholds on 2024.
- Freeze rule in engine: **12 h** one channel, or **6 h** on two channels — not 6 h on temperature alone.
- ESP32 / TFLite are out of scope (software category).
