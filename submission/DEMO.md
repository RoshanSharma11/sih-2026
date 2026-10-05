# Demo — SkyGuard AI (SIH PS 26073)

## Demo video

- **YouTube:** https://youtu.be/emdL6D2NRLQ

The jury should be able to open the link without a login.

## Live prototype

- **URL:** https://www.skyguard.roshansharma.net/

Suggested walkthrough:

1. Open **Network** — 48-station map; Mumbai + Safdarjung framing.
2. Open **Control** — Play `hardware`, then inspect Santa Cruz (`43003`) for `HARDWARE_ANOMALY` and the imputed temperature band.
3. Play `weather` — shared heat → `GENUINE_WEATHER_EVENT`, health unchanged.
4. Open **Station** — raw T/P/H vs overlay, decision trace, neighbors, TIMING.
5. Open **Alerts** / **Reliability** — inbox and completeness.

## Local replay (same stories)

With the API running locally:

```bash
curl -X POST http://127.0.0.1:8000/demo/replay \
  -H 'Content-Type: application/json' \
  -d '{"story":"hardware"}'

curl -X POST http://127.0.0.1:8000/demo/replay \
  -H 'Content-Type: application/json' \
  -d '{"story":"weather"}'
```

See the root [README.md](../README.md) for install and run steps.
