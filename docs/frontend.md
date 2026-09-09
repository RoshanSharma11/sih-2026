# Frontend

Owner: this pair. Polls the product REST APIs and drives `/demo/inject`. It does not own detection, inject math, or training.

## Shipped: F0–F6 one-page console

Streamlit ops console for the **pre-ML-engine** demo (4 stations, NORTH/WEST storm hero). Layout, poll rules, and judge script in the sections below still describe that page.

After slices I1–I5, this page will be wrong (151 stations, neighborhood storms, `label` on ingest). **Do not extend it.** Rewrite as D17 (multi-page) in F7+.

Until the rewrite, keep F0–F6 running against mapped `pipeline_status` so a smoke demo still works on a filtered 4-station view.

## Goal (current page)

A judge sees: **neighborhood storm ≠ lone broken sensor**. Raw T/P/H stay on the chart; imputed is an overlay.

## Stack

- Streamlit + Plotly (D7). Custom dark console theme.
- One page. No SSE.
- Poll interval: **1 s**.
- API base: `SKYGUARD_API` (default `http://127.0.0.1:8000`).

Install: `pip install -e ".[ui]"` then `python scripts/run_dashboard.py`.

## Layout (F0–F6)

```
Header          SkyGuard · live QC · API health
Hero            Storm around Palam | Break Palam temperature | Reset
Live map        India, markers for the view set
Station rail    select station; health badge
Verdict         pipeline_status + explainability_text
Charts          T / P / H — observed solid, imputed dashed
Alerts          newest first; weather ≠ hardware styling
Advanced        freeze / drift / comm
```

Hero is Palam neighborhood: `target: neighborhood, station_id: 42181`. Legacy `cluster_id: NORTH` is 400.

## How we read live status

For each poll (current page):

1. `GET /healthz`
2. `GET /stations?ids=` (view set) — each row includes `latest`; do not N+1 151 stations
3. `GET /stations/{id}/telemetry?limit=` for the **selected** station
4. `GET /alerts?station_id=&limit=`
5. `GET /demo/status`

If `latest` is null, the station is waiting for the streamer.

## Marker encoding

| `pipeline_status` | Color | Meaning |
|---|---|---|
| `CLEAN` | teal | Trusted hour |
| `GENUINE_WEATHER` | amber / gold | Extreme, neighbors agree — **not red** |
| `HARDWARE` | red | Sensor / comms / physical fault |
| `UNKNOWN` | slate | Unconfirmed (D11) |

Prefer `label` when the new UI ships (five-way). Weather stays amber.

## Next frontend (F7+, after I-slices)

Multi-page site. Focus:

- **Station-wise filter** — pick view set; charts and predicted overlay only for those ids; stream-filter POST with `include_buddies=true` so QC still has neighbors
- Map of ingest or view set; click to focus
- Observed vs predicted T/P/H
- Alerts, health, neighborhood inject
- Scalability story: 151 trained stations, filtered live view

Do not invent fields. If the page needs a field, add it to [contracts.md](contracts.md) in the same change.

## Out of scope (both UIs)

- SSE / websockets
- A second inject implementation
- Training UI / SHAP on the hot path
- Replacing observed series with imputed

## Judge script (after I3)

API + streamer (Palam neighborhood ingest set) must already be running.

1. Calm teal markers on the view set.
2. **Storm around Palam** → Palam and its buddies go amber; a Mumbai station in the view stays teal if it is not a Palam buddy.
3. **Reset**, then **Break Palam** → only Palam goes red; neighbor stays teal.
4. Point at the graph: buddy edges, not NORTH vs WEST, are what separate weather from hardware.
