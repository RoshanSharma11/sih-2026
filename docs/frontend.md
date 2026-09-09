# Frontend

Owner: this pair. Polls the product REST APIs and drives `/demo/inject`. It does not own detection, inject math, or training.

## Goal

A judge sees: **neighborhood storm ≠ lone broken sensor**. Raw T/P/H stay on the chart; imputed/predicted is an overlay. Weather is amber, never red.

## Stack

- Streamlit + Plotly (D7). `st.navigation` multi-page. **Light** theme only.
- No SSE / websockets.
- Poll interval: **1 s** on Network, Station, Alerts (`st.fragment`). Control and Guide do not loop.
- API base: `SKYGUARD_API` (default `http://127.0.0.1:8000`).

Install: `pip install -e ".[ui]"` then `python scripts/run_dashboard.py`.

## Pages (F7 lock)

Do not invent routes or API fields. Shared session: `view_ids`, `station_id`, `include_buddies`.

```
Operations
  Network     map + KPIs + view-set picker
  Station     T/P/H overlay + verdict + contribution
  Alerts      newest-first feed, weather ≠ hardware
Demo
  Control     Palam storm / Palam spike / reset / advanced inject
Guide
  How QC works  static 3-tier + view vs ingest (no extra APIs)
```

Default **view set**: Palam `42181` + Safdarjung `42182` + `42139` + Santacruz `43003`. Do not render all 151 on the live map. `include_buddies=true` so ingest is `view ∪ 1-hop`. CLI `--stations` on the streamer still overrides this filter — caption that on Control.

### Network

- Header chips from `GET /healthz`: `ok`, `model_loaded`, `n_stations`.
- KPI strip counted from `latest.label` on the **view set** only: clean / genuine weather / hardware (`PHYSICAL_FAULT` + `HARDWARE_ANOMALY`) / unconfirmed / idle (`latest` null).
- View-set multiselect + `include_buddies`. Changing it `POST /demo/stream-filter`. Caption: ingest still includes buddies so Tier 3 can run.
- India map of `GET /stations?ids=` (view set). Marker color from `latest.label` (fallback `pipeline_status`). Click marker sets `station_id` and switches to Station.
- Optional 1-hop buddy edges for stations currently in view (`GET /buddy-map` subset). Do not draw the full 388-edge graph.
- Scalability copy: 151 trained stations; live view is a handful.

### Station

- Selected `station_id` from session (default Palam).
- Identity, health 0–100 + `status`, isolate / buddy chips from `buddy_ids`.
- Verdict: latest `GET /alerts?station_id=` `explainability_text`, `fault_type`, `confidence_score`. Idle copy if `latest` is null.
- Horizontal contribution bars: `contribution_temp` / `contribution_pres` / `contribution_rhum` (public channels T / P / H).
- Charts: observed solid, imputed/predicted dashed. Raw series never replaced.
- Telemetry: `GET /stations/{id}/telemetry?limit=` for the selected station only.

### Alerts

- `GET /alerts?limit=` (optional `station_id` to match session).
- Newest first. Amber weather vs rose hardware vs slate unconfirmed.
- Click row focuses Station.

### Control

Hero (same bodies as the old console):

- **Storm around Palam** — `{target: neighborhood, station_id: 42181, kind: GENUINE_WEATHER}`
- **Break Palam temperature** — `{target: station, station_id: 42181, kind: SPIKE, channel: temp_c}`
- **Reset overlays** — `POST /demo/reset`

Advanced: SPIKE / FREEZE / DRIFT / COMM_ERROR on one station; GENUINE_WEATHER on a neighborhood. Storm targeting a single station is 400. Armed overlays from `GET /demo/status`. View-set picker may live here or on Network; one session, one POST.

### Guide

Static: three tiers (physical rules → LSTM → IDW buddies), view set vs ingest set, neighborhood storm vs lone spike, why isolates land `UNCONFIRMED_ANOMALY`. Offline commands from the root README. No extra APIs.

## Light tokens

| Role | Value |
|---|---|
| Canvas | `#F8FAFC` |
| Card | `#FFFFFF` + soft shadow |
| Text | `#0F172A` / muted `#475569` |
| Accent / chrome | teal `#0D9488` |
| Clean | `#0D9488` |
| Genuine weather | `#D97706` |
| Hardware | `#E11D48` |
| Unconfirmed / idle | `#64748B` |
| Font | IBM Plex Sans / IBM Plex Mono |
| Plotly | white paper, light grid, observed solid, predicted dashed |

Hide Streamlit toolbar, menu, footer, deploy. Sidebar ~260px. Layout: KPI strip, then map/charts, then tables.

## Marker / verdict encoding

Prefer five-way `label`. Fall back to `pipeline_status` (D18) if `label` is missing.

| `label` | `pipeline_status` | Color | Meaning |
|---|---|---|---|
| `CLEAN` | `CLEAN` | teal | Trusted hour |
| `GENUINE_WEATHER_EVENT` | `GENUINE_WEATHER` | amber | Extreme, neighbors agree — **not red** |
| `PHYSICAL_FAULT` / `HARDWARE_ANOMALY` | `HARDWARE` | rose | Sensor / comms / physical fault |
| `UNCONFIRMED_ANOMALY` | `UNKNOWN` | slate | Unconfirmed (D11) |
| (no `latest`) | — | slate | Waiting for stream |

## How we poll

Never N+1 151 stations. Map and KPIs use list `latest` only.

1. `GET /healthz`
2. `GET /stations?ids=` for the **view set**
3. Selected station: `GET /stations/{id}/telemetry?limit=` and `GET /alerts?station_id=`
4. Alerts page: `GET /alerts?limit=`
5. Control / Network: `GET /demo/status` and `GET /demo/stream-filter`
6. `GET /buddy-map` only to draw 1-hop edges for the view set

If `latest` is null, the station is waiting for the streamer.

## Out of scope

- SSE / websockets
- A second inject implementation
- Training UI / SHAP on the hot path
- Replacing observed series with imputed
- Dark-mode toggle
- Inventing ingest-result fields (`tier1`, `mse`) on GET routes — use alerts + `latest`

## Judge script

API + streamer must already be running. Prefer Palam neighborhood ingest (`--stations 42181 --with-buddies`) unless the UI stream-filter is the only filter (no CLI override).

Default view includes Palam, its two buddies, and Santacruz so Mumbai can stay teal.

1. Open **Network**. Calm teal markers on the view set. API / model chips live.
2. **Control → Storm around Palam** → Palam and its buddies go amber; Santacruz stays teal.
3. **Reset**, then **Break Palam temperature** → only Palam goes rose; Safdarjung stays teal.
4. Open **Station** on Palam: observed series still on the chart; dashed overlay is reconstruction; verdict text is `explainability_text`; contribution bars name the channel.
5. **Guide**: buddy graph, not NORTH vs WEST, is what separates weather from hardware.
