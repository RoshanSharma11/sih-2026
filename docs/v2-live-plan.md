# Implementation plan — live IMD console on v2

Next session: start at step 5. Do not resume the Palam / `ml/` demo as the product path. Do not commit `.env`.

## What we are building

The product API keeps owning persistence and the dashboard. Each hour it stores raw temperature, humidity, and pressure, then calls `v2-deliverable`’s `process_aws_data` in-process. Live hours come from IMD AWS/ARG, matched to the 48 trained stations by `aws_id`. The map and station page show that reading immediately. A verdict, dashed correction, and band appear only after 24 real hourly values exist. A replay control still plays the Mumbai 55 °C story from `demo_windows.json` so the demo does not wait a day. The console stays the light five-page layout, with the verdict, band, physics card, and neighbor table as the thing an operator reads.

## Language

- **Live data:** Latest IMD AWS/ARG temperature, humidity, and pressure for the 48 stations in `v2-deliverable/v2/data/stations_judge48.csv`, matched by `aws_id`. Stored as raw hours. Only `temp`, `rhum`, and `pres` go into the model.
- **Latest ML:** `v2.engine.process_aws_data` (correlation-weighted neighbors, overlay band, physics card). The old `ml/` engine is off the live path.
- **Interpretable:** Raw solid line always. Dashed correction and 90% band only when the sensor is distrusted. Reason, dew point, channel bars, neighbor agreement, and TIMING say why.
- **Efficient:** One in-process model call. Dashboard polls the product API. TIMING is filled in after the hour is saved. Map is the 48, not 151.
- **Look good:** Existing light console and color language. Verdict, band, and neighbor evidence are the visual focus.

I/O details: `v2-deliverable/docs/CONTRACT.md`. Briefing: `v2-deliverable/docs/SKYGUARD_V2.md`.

## Decisions

- **Warm-up is honest.** Poll IMD, bucket to the hour, save the raw row at once, and show it. Until 24 hourly points exist, the station is warming up, not a fake fault. Then v2 scores it.
- **Replay stays.** Control can play the six Mumbai stories from `v2-deliverable/v2/data/demo_windows.json` through the same `/ingest` path. Live and replay are separate timelines.
- **IMD is not a model feature.** Wind, weather code, and forecasts do not enter `process_aws_data`. An optional warning chip on an amber hour is backend-only and comes after the verdict.
- **Palam is not the default.** It has a scaler, so the engine would score it, but it is outside the live 48. Default view is Mumbai `43003`, `43057`, `43002`, `43058`, plus Safdarjung `42182`.
- **Health comes from stored labels.** Weather does not lower the 7-day score. The engine’s in-memory tracker is not the product score.
- **GAT stays off** on product ingest. Tier 3 method on the live path is `cw_idw`.

## Assumptions

- IMD credentials are already in `.env` as `IMD_API_KEY`, `IMD_EMAIL`, `IMD_PASSWORD`. JWT URL is `IMD_TOKEN_URL`. Never copy them into docs, code, or commits. The key is bound to this machine’s public IP.
- The first authenticated `aws_data` response confirms whether `id` is a state code or a call sign, and whether `TIME` is UTC. Until that sample, timestamps are treated as UTC and re-emitted with `Z`.
- Empty IMD strings become null. Null is a missing channel, not zero.
- Stations in the 48 whose AWS row has no temperature, humidity, or pressure are shown as live-but-unscored for that hour, not dropped from the catalog.
- Safdarjung has no buddies inside the 48, so a suspicious live hour there is unconfirmed. The Mumbai four are ingested together whenever replay story 2 or 3 runs.
- Public contracts gain the v2 fields (`imputed_interval`, `thermo`, `tier3.mix`, timing, warm-up) in `docs/contracts.md` in the same change that uses them. No SSE.

## How to build it

1. **Point ingest at v2.** Load `get_engine()` from `v2-deliverable` (TIMING queued, graph model off). Adapter still maps `temp_c` / `rhum_pct` / `pres_hpa` to `temp` / `rhum` / `pres`, builds the 24-hour window and buddy windows, and writes raw before the call. Persist `predicted`, `imputed_interval`, `thermo`, `tier2.score`, `tier3.method` / `mix` / `corr`, and `reason`. Unknown scaler returns 400. Recompute 7-day health from stored labels, excluding weather.

2. **Switch the live catalog to the 48.** Import `stations_judge48.csv` plus `buddy_edges.csv` into the processed catalog, including `aws_id`, `aws_name`, and distance. Buddy payloads include only neighbors that are actually ingested. `/healthz` reports LSTM, overlay, and graph weights loaded, plus the v2 threshold `0.008487`.

3. **Add the IMD poller.** Refresh the JWT before expiry. Pull AWS snapshots for the states that cover the 48, match `ID` to `aws_id`, and map `CURR_TEMP`, `RH`, and `MSLP` onto the WMO station. Bucket to the hour. Skip a duplicate hour (409) instead of failing the loop. Post into the existing ingest path. Record last success, last error, and how many of the 48 matched, on `/healthz`.

4. **Warm-up on the API.** If a station has fewer than 24 hourly rows, return the raw latest observation and a warming-up state. Do not invent a label. Once the window is complete, return the real v2 label.

5. **Replay on the same ingest path.** Seed and stream `demo_windows.json` for the five demo ids, ending `2024-12-31T23:00:00Z`. Control arms mutations before QC: Santa Cruz only at 55 °C / 95% / 980 hPa; +8 °C on Santa Cruz, Colaba, and `43002`; 12-hour freeze; null temperature; reset. Story 2 and 3 ingest the Mumbai four together.

6. **TIMING proxy.** `GET /stations/{id}/timing?ts=` reads the v2 cache. Ingest never waits on it.

7. **Dashboard.** Network: 48 markers, default camera on Mumbai plus Safdarjung, color by label, warming-up as its own idle state, Safdarjung tooltip that weather versus hardware cannot be called there. Station: solid raw always; dashed line and band only when `imputed_interval` is present; root-cause block in order — reason, dew point and Td−T, channel bars, neighbor table, TIMING sentence polled until ready. Alerts: amber `STORM` versus rose hardware, including `THERMO` and `COMMUNICATION`. Health line: genuine weather does not count. Control: live poll status, and the replay stories instead of the Palam buttons. Guide: 48 live stations, 24-hour warm-up, Palam not on the map.

8. **Check the two paths.** One live poll with credentials present stores a raw hour and shows warming-up. Replay story 2 returns hardware with a band near 25 °C, and story 3 returns weather with no band and no health drop. Dashboard poll still uses only the product API.

## Done when

- Live poll stores a raw hour for a matched `aws_id` and the station page shows it as warming up until 24 hours exist.
- Replay story 2 is hardware with a band near 25 °C. Story 3 is weather, no band, health unchanged.
- The dashboard never calls port 8001 or `ml.engine`.
