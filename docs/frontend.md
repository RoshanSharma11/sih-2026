# Frontend

Owner: this pair. Polls the product REST APIs and plays `/demo/replay`. It does not own detection, inject math, or training.

## Goal

A judge sees: **neighborhood storm ≠ lone broken sensor**. Raw T/P/H stay on the chart; imputed/predicted is an overlay. Weather is amber, never red.

## Stack

- Streamlit + Plotly (D7). `st.navigation` multi-page. **Light** theme only.
- No SSE / websockets.
- Poll interval: **1 s** on Network, Station, Alerts (`st.fragment`). Control and Guide do not loop.
- API base: `SKYGUARD_API` (default `http://127.0.0.1:8000`).

Install: `pip install -e ".[ui]"` then `python scripts/run_dashboard.py`.

## Pages (F7 lock)

Do not invent routes or API fields. Shared session: `view_ids`, `station_id`, `include_buddies`, `alert_id` (set when Open is clicked on Alerts).

```
Operations
  Network     48 markers + KPIs
  Station     raw line, band only when distrusted, root cause
  Alerts      newest-first feed, weather ≠ hardware
Demo
  Control     live poll + Mumbai replay + custom inject
Guide
  How QC works  48 stations, 24-hour warm-up, Palam not on the map
```

The map plots all 48. The camera starts on Mumbai `43003`, `43057`, `43002`, `43058` plus Safdarjung `42182`. Palam `42181` is not in the live catalog. Default station is Santa Cruz `43003`.

### Network

- Header chips from `GET /healthz`: `ok`, `model_loaded`, `n_stations`.
- KPI strip counted from `latest.label` on all 48: clean / genuine weather / hardware (`PHYSICAL_FAULT` + `HARDWARE_ANOMALY`) / unconfirmed / warming up (`warming_up`) / waiting (`latest` null).
- India map of `GET /stations` (no `ids`) on a light Carto basemap. Camera fits Mumbai plus Safdarjung. Marker color from `latest.label` (fallback `pipeline_status`). Warming up is its own slate, not “waiting”. Safdarjung’s hover says weather versus hardware cannot be called there. Click marker or roster row sets `station_id` and switches to Station. Only the selected marker is labeled on the map.
- Buddy edges only among the five-station camera set (`GET /buddy-map` subset). Do not draw the full graph.
- Roster lists the camera set first, then the rest by name.

### Station

- Selected `station_id` from session (default Santa Cruz). The selector is the full catalog. A station opened from Alerts stays selected.
- Identity card: short name, WMO id, `aws_name` / `aws_id`, elevation, coordinates, named 1-hop buddies (or isolate).
- Warming up is first-class: `n / 24` window bar from the latest continuous run, raw T / P / H tiles (missing channels called out), no verdict, no predicted overlay. Temperature, pressure, and humidity charts still render for the hours collected so far.
- Live verdict is **this hour** from `latest.label`. Matching `GET /alerts?station_id=` row (same timestamp) supplies `explainability_text` / contribution. Do not reuse an older alert as the live verdict after the hour has gone clean.
- Open on Alerts pins `alert_id`. A replay pins that story’s end hour, even when a newer live hour exists. Station then shows that hour’s label, explainability, contribution, and a dotted marker on the chart, with a **Show live hour** control. The chart is the continuous run around that hour, so a year-long gap does not draw a line to the live point. Health stays the 7-day index.
- Reading tiles always show observed. Predicted, Δ, and the 90% band appear on a tile only when that row’s `imputed_interval` is a pair.
- Charts: observed solid always. Temperature is the lead chart; pressure and humidity sit beside it. Dashed correction and the 90% band only when that row’s `imputed_interval` is a pair. Raw series never replaced.
- Root cause, in order: `explainability_text`, dew point and Td−T from `thermo`, channel bars from the matching alert, named neighbors from `tier3_corr` / `tier3_mix` / `tier3_method`, then `GET /stations/{id}/timing?ts=&wait_s=0` polled until `ready`.
- Health meter: 7-day sensor flag rate. Genuine weather does not count.
- Telemetry: `GET /stations/{id}/telemetry?limit=` for the selected station only.

### Alerts

- QC inbox. Clean hours never appear. Intro states the three kinds before the feed.
- `GET /alerts?limit=` (optional `station_id` when “Only {station}” is on). Counts and filters are client-side: all / hardware / weather / unconfirmed.
- Newest first. Each card is a human label, station name, time, fault in plain language (`Spike`, `Missing packet`, …), confidence, reason, and a weather/unconfirmed health note. Amber weather (`GENUINE_WEATHER` and `STORM`) vs rose hardware (`PHYSICAL_FAULT`, `HARDWARE_ANOMALY`, `THERMO`, `COMMUNICATION`, `COMM_ERROR`) vs slate unconfirmed.
- **Inspect this hour** pins that `alert_id` and focuses Station on that hour (not the live CLEAN hour).

### Control

- Live poll from `GET /healthz` `imd`: `matched`, `last_success`, `last_error`, shown as a status strip (ok / failed / waiting).
- Replay is select-then-observe. Choose `clean`, `hardware`, `weather`, `freeze`, or `comms`; the preview states the mutation, who is ingested, what label to look for, and whether health should move. **Play** posts `POST /demo/replay`. Results stay on Control (label, observed T/P/H, predicted / band when present, health, reason). Session still focuses Santa Cruz and pins that story’s end hour. **Inspect Santa Cruz on Station** opens the chart.
- Custom event builder posts `POST /demo/inject` only (no local `inject.py`). Choose catalog `station_id`, `kind` (`SPIKE` / `FREEZE` / `DRIFT` / `COMM_ERROR` / `GENUINE_WEATHER`), `channel` when required, and `duration_hours`. Weather forces `target=neighborhood` and expands 1-hop buddies. Hardware stays `target=station`. The overlay waits for the next ingested hour. Armed rows come from `GET /demo/status`.
- **Reset overlays** — `POST /demo/reset`. Replay itself clears its arm.

### Guide

Static: 48 live stations, 24-hour warm-up, Palam not on the map, three tiers, replay stories, weather does not lower health. The dashboard polls the product API only. No extra APIs.

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
| Unconfirmed / waiting | `#64748B` |
| Warming up | `#94A3B8` |
| Font | IBM Plex Sans / IBM Plex Mono |
| Plotly | white paper, light grid, observed solid, predicted dashed |

Hide Streamlit toolbar, menu, footer, deploy. Sidebar ~268px with custom `st.page_link` nav (do not restyle sidebar `*` to IBM Plex — that breaks Material icons). Layout: KPI strip, then map + roster / charts, then tables. Map height ~640px.

## Marker / verdict encoding

Prefer five-way `label`. Fall back to `pipeline_status` (D18) if `label` is missing.

| `label` | `pipeline_status` | Color | Meaning |
|---|---|---|---|
| `CLEAN` | `CLEAN` | teal | Trusted hour |
| `GENUINE_WEATHER_EVENT` | `GENUINE_WEATHER` | amber | Extreme, neighbors agree — **not red** |
| `PHYSICAL_FAULT` / `HARDWARE_ANOMALY` | `HARDWARE` | rose | Sensor / comms / physical fault |
| `UNCONFIRMED_ANOMALY` | `UNKNOWN` | slate | Unconfirmed (D11) |
| `warming_up` | — | `#94A3B8` | Fewer than 24 hours. Not a verdict. |
| (no `latest`) | — | slate | Waiting for a live hour or a replay |

## How we poll

Never N+1 the catalog. Map and KPIs use list `latest` only. Do not call port 8001.

1. `GET /healthz`
2. `GET /stations` for all 48
3. Selected station: `GET /stations/{id}/telemetry?limit=`, `GET /alerts?station_id=`, and `GET /stations/{id}/timing?ts=&wait_s=0`
4. Alerts page: `GET /alerts?limit=`
5. Control: `GET /healthz` for the poll line, `POST /demo/replay`, `POST /demo/reset`
6. `GET /buddy-map` only to draw edges among the camera set

If `latest` is null, the station is waiting. If `warming_up` is true, it is warming up.

## Out of scope

- SSE / websockets
- A second inject implementation
- Training UI / SHAP on the hot path
- Replacing observed series with imputed
- Dark-mode toggle
- Inventing ingest-result fields (`tier1`, `mse`) on GET routes — use alerts + `latest`

## Judge script

API must already be running. The dashboard does not start a Palam streamer and does not call port 8001.

1. Open **Network**. 48 markers. Camera frames Mumbai and Safdarjung. Warming-up stations are their own color. Safdarjung’s tooltip says weather versus hardware cannot be called there.
2. **Control → Lone 55 °C → Play**. The last-run panel shows Santa Cruz as hardware, observed 55 °C, a predicted overlay and band. **Inspect Santa Cruz on Station** opens the 2024 hour with a solid raw line, a dashed correction, and a band. The root-cause block ends with the TIMING sentence once it is ready.
3. **+8 °C across Mumbai**. Amber weather. No band. Health unchanged.
4. **Guide**: 48 live stations, 24-hour warm-up, Palam is not on the map.
