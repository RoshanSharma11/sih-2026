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

## Pages

Do not invent routes or API fields. Shared session: `view_ids`, `station_id`, `include_buddies`, `alert_id` (set when Open is clicked on Alerts).

```
Operations
  Network     48 markers + KPIs
  Station     raw line, band only when distrusted, root cause
  Alerts      newest-first feed, weather ≠ hardware, acknowledge / resolve
  Reliability per-station completeness + flag history (GET /reliability)
Demo
  Control     live poll + Mumbai replay + custom inject
Guide
  How QC works  48 stations, 24-hour warm-up, Palam not on the map
  Architecture  animated hour: sources → ingest → in-process v2 → poll
```

The map plots all 48. The camera starts on Mumbai `43003`, `43057`, `43002`, `43058` plus Safdarjung `42182`. Palam `42181` is not in the live catalog. Default station is Santa Cruz `43003`.

### Network

- Header chips from `GET /healthz`: `ok`, `model_loaded`, `n_stations`.
- Intro card states the amber/rose rule and the five-color legend. KPI strip counted from `latest.label` on all 48: clean / genuine weather / hardware (`PHYSICAL_FAULT` + `HARDWARE_ANOMALY`) / unconfirmed / warming up (`warming_up`) / feed gap (`latest.feed_gap` non-empty) / waiting (`latest` null). Seven equal KPI tiles. When `/healthz.imd.feed_gap` is non-empty an indigo banner under the KPIs says which channel IMD did not send and on how many stations, and that those hours are unscored and not charged to the sensors.
- Dispatch is a full-width board above the map. **Needs a technician** is `status` `DEGRADED` / `CRITICAL` (7-day health; weather already excluded). **Watch this hour** is `latest.label` hardware while `status` is still `HEALTHY`. Warming up, waiting, weather, and unconfirmed stay off the list. One `GET /alerts?limit=` attaches the newest hardware reason, shown as one plain line (`Missing packet · temperature`, not `COMMUNICATION:temp`). Open focuses Station and pins that `alert_id` when present. The map sits left; the rail is the station list only.
- India map of `GET /stations` (no `ids`) on a light Carto basemap. Camera fits Mumbai plus Safdarjung. Marker color from `latest.label` (fallback `pipeline_status`). Warming up is its own slate, not “waiting”. A feed-gap hour is indigo (`Feed gap · humidity`), never rose. Hover shows the label, the latest raw T / P / H from `latest.observed` with its hour, and 7-day health. Safdarjung’s hover says weather versus hardware cannot be called there. Click marker or roster row sets `station_id` and switches to Station. Only the selected marker is labeled on the map.
- Buddy edges only among the five-station camera set (`GET /buddy-map` subset). Do not draw the full graph.
- Roster on the rail: Mumbai + Safdarjung first, then the rest by name. Selected row uses the teal inset, not a full-width primary button.

### Station

- Selected `station_id` from session (default Santa Cruz). The selector is the full catalog. A station opened from Alerts stays selected.
- Identity card: short name, WMO id, `aws_name` / `aws_id`, elevation, coordinates, named 1-hop buddies (or isolate).
- Warming up is first-class: `n / 24` window bar from the latest continuous run, raw T / P / H tiles (missing channels called out), no verdict, no predicted overlay. Temperature, pressure, and humidity charts still render for the hours collected so far.
- Live verdict is **this hour** from `latest.label`. Matching `GET /alerts?station_id=` row (same timestamp) supplies `explainability_text` / contribution. Do not reuse an older alert as the live verdict after the hour has gone clean.
- Open on Alerts pins `alert_id`. A replay pins that story’s end hour, even when a newer live hour exists. Station then shows that hour’s label, explainability, contribution, and a dotted marker on the chart, with a **Show live hour** control. The chart is the continuous run around that hour, so a year-long gap does not draw a line to the live point. Health stays the 7-day index.
- Reading tiles always show observed. Predicted, Δ, and the 90% band appear on a tile only when that row’s `imputed_interval` is a pair.
- Charts: observed solid always. Temperature is the lead chart; pressure and humidity sit beside it. The dashed correction is drawn for a run that contains an `imputed_interval`: it stays on the raw reading for trusted hours and uses `predicted` on the distrusted hour, so one corrected hour still reads as a line that leaves the spike. The 90% band is a fill across that hour. Raw series never replaced.
- **Verdict ribbon** under the charts: the 24 stored hours ending at the shown hour, one cell per row colored by that row's `label` (warming up is its own color, a missing hour is a dashed empty cell). The shown hour is outlined. Counts in the head (`22 clean · 1 weather · 1 hardware`).
- Root cause ("Why this hour"), in order:
  1. `explainability_text` in bold.
  2. **Decision trace** — three cards in the order QC ran them. *Physical rules*: `Passed`, or `Failed` with the rule named (missing channel from null `*_observed`, dew point from `thermo.passed`, freeze / spike from the alert `fault_type`); dew point and Td−T from `thermo`. *LSTM autoencoder*: `tier2_score` against `/healthz.threshold` as `N.N×` the operating score; `Passed` on `CLEAN`, `Flagged` otherwise, `Not run` when the score is null. *Buddy check*: `Neighbors agree` (weather), `Neighbors disagree` (hardware), `Slow bias versus neighbors` when `fault_type=DRIFT` (residual CUSUM, `tier3_drift`), `Skipped` (unconfirmed or after a hard rule), `Not run` (clean); neighbor count from `tier3_corr`, method from `tier3_method`. States are derived from `label`; the page does not read `tier1` / `tier3.performed` (not on GET routes).
  3. Channel bars from the matching alert (`contribution_*`).
  4. **Neighbor table** when `tier3_mix` is present: per channel, this sensor (`*_observed`) vs neighbor blend (`tier3_mix`), Δ, and the v2 agree band (`±3 °C / ±8 % / ±2 hPa`, display constants from `v2/config.py`) with an `inside band` / `outside band` chip. Buddies listed by name with `tier3_corr`. Caption states agreement is judged on the channels carrying the error.
  5. TIMING: `GET /stations/{id}/timing?ts=&wait_s=0` polled until `ready`; then the sentence, a 24-bar `hour_attr` chart (bars from `start_hour_in_window` onward in the overlay color, earlier bars slate), and a `channel_attr` line.
- **Take it with you**: `st.download_button` for the shown run as CSV (raw columns first; predicted / band columns filled only on rows with `imputed_interval`) and a plain-text technician note (verdict, raw T/P/H, suggested correction and band, reason, neighbor deltas, 7-day health, an action line — weather says *do not dispatch*; drift says *inspect calibration*). Both built client-side from telemetry + alert rows. A third `st.link_button` opens `GET /export?station_id=&from=` (30 days, WMO-style `qc_flag`) in the browser; Network has the same link for the whole network over 7 days. Links are not polled.
- Health meter: 7-day sensor flag rate. Genuine weather does not count.
- Telemetry: `GET /stations/{id}/telemetry?limit=` for the selected station only.

### Alerts

- QC inbox. Clean hours never appear. Intro states the three kinds before the feed.
- `GET /alerts?limit=&state=` (optional `station_id` when “Only {station}” is on). Kind filters are client-side: all / hardware / weather / unconfirmed. The operator-state radio (Open, default / Acknowledged / Resolved / Everything) is the `state` query. "Your name for the log" is sent as `by`.
- Each card has **Inspect this hour**, then the actions for its state: open → Acknowledge / Resolve; acknowledged → Resolve / Reopen; resolved → Reopen (`POST /alerts/{id}/ack`). Acknowledged and resolved cards show a chip with who and when; resolved cards are dimmed. Dispatch rows on Network show `acknowledged` in the meta line and get an **Acknowledge** button while the newest hardware alert is open.
- **Exceptions per hour**: a stacked bar chart of the feed bucketed by hour (rose hardware / amber weather / slate unconfirmed). A wide amber bar is a shared weather hour; a lone rose bar is one sensor. Hidden when the feed is empty.
- Newest first. Each card is a human label, station name, time, fault in plain language (`Spike`, `Missing packet`, …), confidence, reason, and a weather/unconfirmed health note. Amber weather (`GENUINE_WEATHER` and `STORM`) vs rose hardware (`PHYSICAL_FAULT`, `HARDWARE_ANOMALY`, `THERMO`, `COMMUNICATION`, `COMM_ERROR`) vs slate unconfirmed.
- **Inspect this hour** pins that `alert_id` and focuses Station on that hour (not the live CLEAN hour).

### Reliability

- One `GET /reliability?hours=` per render (24 h / 3 d / 7 d / 30 d radio, default 7 d). Not a 1-second fragment; it reruns on the radio.
- Intro states the difference: health is trust in the sensor, completeness is whether the station reports. Five KPIs from `network`: mean completeness, stations ≥ 90 % complete, degraded or critical, isolates (`n_isolates / n_stations`, the < 2-buddy count), feed-gap hours.
- **Hours by outcome**: one horizontal stacked bar per station (clean teal, weather amber, hardware rose, unconfirmed slate, warming `#94A3B8`, feed gap indigo), worst completeness at the top, a dotted line at the full window.
- **Every station**: `st.dataframe` with `ProgressColumn` for completeness and flag rate, plus stored / scored / hardware / weather / unconfirmed / feed gap / buddies / 7-day health / status / last hour. A select-box plus **Open on Station** focuses that station.

### Control

- Live poll from `GET /healthz` `imd`: `matched`, `last_success`, `last_error`, shown as a status strip (ok / failed / waiting).
- Replay is select-then-observe. Choose `clean`, `hardware`, `weather`, `freeze`, or `comms`; the preview states the mutation, who is ingested, what label to look for, and whether health should move. **Play** posts `POST /demo/replay`. The scored hour replaces that preview in the same card: Santa Cruz first, then **Inspect Santa Cruz on Station** in the Play slot, then the other stations. Session still focuses Santa Cruz and pins that story’s end hour. Inspect opens the chart. Switching to another story shows that story’s preview again.
- Custom event builder posts `POST /demo/inject` only (no local `inject.py`). Choose catalog `station_id`, `kind` (`SPIKE` / `FREEZE` / `DRIFT` / `COMM_ERROR` / `GENUINE_WEATHER`), `channel` when required, and `duration_hours`. Weather forces `target=neighborhood` and expands 1-hop buddies. Hardware stays `target=station`. The overlay waits for the next ingested hour. Armed rows come from `GET /demo/status`.
- **Reset overlays** — `POST /demo/reset`. Replay itself clears its arm.

### Guide

Static: 48 live stations, 24-hour warm-up, Palam not on the map, three tiers, replay stories, weather does not lower health. The dashboard polls the product API only. No extra APIs.

### Architecture

Static explainer under Guide. No API calls. One looping hour:

- Sources: IMD poller, replay / inject, clean streamer. Beads converge into the API.
- Order inside the API: `POST /ingest` → overlay only when armed → persist raw → warm-up gate (under 24 hours skips v2) → in-process `v2.engine.process_aws_data` (graph model off, TIMING queued) → overlay, alert, 7-day health → console poll about once a second.
- Scored labels use the console colors. Weather stays amber. Warming up leaves before the model.
- View versus ingest: Santa Cruz on screen still posts Juhu, Colaba, and Alibag.

The moving dot is one hour. It loops.

Below the diagram, two charts read `v2-deliverable/v2/artifacts`: the 2023 reconstruction percentiles (`val_error_percentiles.json`) and overlay MAE against its gates (`overlay_metadata.json`). The block is omitted when those files are absent. The ingest score on the tiles is `operating_score` from that same percentiles file. Window p99 stays a separate line.

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
| Feed gap | `#6366F1` |
| Font | IBM Plex Sans / IBM Plex Mono |
| Plotly | white paper, light grid, observed solid, predicted dashed |

Hide Streamlit toolbar, menu, footer, deploy. Sidebar ~268px with custom `st.page_link` nav (do not restyle sidebar `*` to IBM Plex — that breaks Material icons). Layout: KPI strip, dispatch board, then map + roster rail / charts, then tables. Map height ~640px. Custom HTML goes through `st.html` so Markdown does not eat spaces.

## Marker / verdict encoding

Prefer five-way `label`. Fall back to `pipeline_status` (D18) if `label` is missing.

| `label` | `pipeline_status` | Color | Meaning |
|---|---|---|---|
| `CLEAN` | `CLEAN` | teal | Trusted hour |
| `GENUINE_WEATHER_EVENT` | `GENUINE_WEATHER` | amber | Extreme, neighbors agree — **not red** |
| `PHYSICAL_FAULT` / `HARDWARE_ANOMALY` | `HARDWARE` | rose | Sensor / comms / physical fault |
| `UNCONFIRMED_ANOMALY` | `UNKNOWN` | slate | Unconfirmed (D11) |
| `warming_up` | — | `#94A3B8` | Fewer than 24 hours. Not a verdict. |
| `feed_gap` non-empty | — | `#6366F1` | IMD did not send that channel network-wide. Not a verdict, not a fault. |
| (no `latest`) | — | slate | Waiting for a live hour or a replay |

## How we poll

Never N+1 the catalog. Map and KPIs use list `latest` only. Do not call port 8001.

1. `GET /healthz`
2. `GET /stations` for all 48
3. Network dispatch: one `GET /alerts?limit=` (not N+1)
4. Selected station: `GET /stations/{id}/telemetry?limit=`, `GET /alerts?station_id=`, `GET /stations/{id}/timing?ts=&wait_s=0`, and `GET /healthz` for `threshold` (the LSTM trace ratio)
5. Alerts page: `GET /alerts?limit=&state=`; buttons call `POST /alerts/{id}/ack`
6. Reliability page: `GET /reliability?hours=` once per render
6. Control: `GET /healthz` for the poll line, `POST /demo/replay`, `POST /demo/reset`
7. `GET /buddy-map` only to draw edges among the camera set

If `latest` is null, the station is waiting. If `warming_up` is true, it is warming up. If `feed_gap` is non-empty, the hour is a feed gap: the verdict card, the missing reading tile and the ribbon cell say so, "Why this hour" explains it instead of the decision trace, and Control's poll strip shows the same count from `/healthz.imd.feed_gap`. The poll strip also shows `next_poll`, how many states the last cycle called, and a rose "paused until" state while `rate_limited_until` is set. Under it a second strip reads `/healthz.webhook`: "Paging off" with the env var to set, or "Paging on · n sent · n failed · last event".

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
2. **Control → Lone 55 °C → Play**. The story card becomes the scored hour: Santa Cruz as hardware, observed 55 °C, a predicted overlay and band, with **Inspect Santa Cruz on Station** in the Play slot. Network lists Santa Cruz under **Watch this hour** (health still HEALTHY). Inspect opens the 2024 hour with a solid raw line, a dashed correction, and a band. The root-cause block ends with the TIMING sentence once it is ready.
3. **+8 °C across Mumbai**. Amber weather. No band. Health unchanged. Dispatch does not list those stations for weather.
4. **Guide**: 48 live stations, 24-hour warm-up, Palam is not on the map.
