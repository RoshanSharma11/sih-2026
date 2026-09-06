# Frontend — live demo dashboard

Owner: this pair. Streamlit ops console that **polls** the frozen REST APIs and drives `/demo/inject`. It does not own detection, inject math, or training.

## Goal

A judge sees the moat in one glance: **cluster storm ≠ lone broken sensor**. Delhi does not validate Mumbai. Raw T/P/H stay on the chart; imputed is an overlay.

## Stack

- Streamlit + Plotly (D7 / D13). Custom dark console theme, not default Streamlit chrome.
- One page. No SSE, no extra API fields.
- Poll interval: **1 s** (`st.fragment(run_every=1)`).
- API base: `SKYGUARD_API` (default `http://127.0.0.1:8000`). Server-side `httpx`; CORS is not required.

Install: `pip install -e ".[ui]"` then `python scripts/run_dashboard.py`.

## Layout

```
Header          SkyGuard · live QC · API health
Hero            Storm on NORTH | Break Palam temperature | Reset
Live map        India, 4 markers, both clusters
Station rail    select station; health badge
Verdict         pipeline_status + explainability_text
Charts          T / P / H — observed solid, imputed dashed
Alerts          newest first; weather ≠ hardware styling
Advanced        freeze / drift / comm + cluster/station pickers
```

## How we read live status (no new fields)

`GET /stations` has `health_score` and 7-day `status`, not `pipeline_status`.

For each poll:

1. `GET /healthz`
2. `GET /stations`
3. `GET /stations/{id}` for every station — use `latest.pipeline_status` for marker color
4. `GET /stations/{id}/telemetry?limit=` for the **selected** station
5. `GET /alerts?station_id=&limit=` for the verdict sentence (`explainability_text` lives here; list `latest` may omit it)
6. `GET /demo/status` for armed overlay chips

If `latest` is null, the station is waiting for the streamer. Treat marker as idle, not `HARDWARE`.

## Marker encoding

| `pipeline_status` | Color | Meaning |
|---|---|---|
| `CLEAN` | teal | Trusted hour |
| `GENUINE_WEATHER` | amber / gold | Extreme, neighbors agree — **not red** |
| `HARDWARE` | red | Sensor / comms fault |
| `UNKNOWN` | slate | Abstain (D11). First station in a storm hour may stay here until the neighbor lands |

`health_score` / `status` is a **badge** only. Weather alerts do not tank health.

Click a marker or rail row to focus charts and alerts on that `station_id`.

## Hero inject

| Control | Request |
|---|---|
| Storm on NORTH | `POST /demo/inject` `{target: cluster, cluster_id: NORTH, kind: GENUINE_WEATHER}` |
| Break Palam temperature | `{target: station, station_id: "42181", kind: SPIKE, channel: temp_c}` |
| Reset | `POST /demo/reset` |

Advanced expander: `FREEZE` / `DRIFT` / `COMM_ERROR` on one station; storm on `WEST`. Honor contract rules (storm = cluster, hardware = station, channel required for spike/freeze/drift). Default `duration_hours` from the API.

The streamer stays clean. This page is the only live fault control.

## Charts

Three panels, selected station, oldest → newest after reversing the API’s newest-first-then-reversed client list (API already returns ascending).

- Observed: `temp_observed` / `pres_observed` / `rhum_observed`
- Imputed: `temp_imputed` / `pres_imputed` / `rhum_imputed` (dashed, skip nulls)
- Do not hide raw points when `is_anomaly` is true

## Verdict

Selected station, newest matching `/alerts` row:

- Status chip = `latest.pipeline_status` (or idle)
- Headline = `explainability_text`
- `confidence_score` and `severity` secondary
- `GENUINE_WEATHER` uses weather styling; hardware uses fault styling

Show UNKNOWN copy honestly: not enough same-hour neighbors yet.

## Out of scope

- Inventing `latest_pipeline_status` on `GET /stations`
- SSE / websockets
- A second inject implementation
- Training UI / SHAP
- Replacing observed series with imputed

## Judge script

API + streamer must already be running.

1. Four calm teal markers.
2. **Storm on NORTH** → both Delhi markers go amber; Mumbai stays teal; sentence: neighbors agree, not a fault. Health does not crash.
3. **Reset**, then **Break Palam** → only Palam goes red; Safdarjung stays teal; sentence: expected vs received.
4. Point at the map: Delhi does not validate Mumbai.
