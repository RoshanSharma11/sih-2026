# Catalogs

- `stations.csv` — 151 train/inference scalers live here.
- `stations_judge48.csv` — **live map**. Palam `42181` is not in this file.
- `buddy_edges.csv` — 100 km undirected edges among the 151.
- `demo_windows.json` — 24 aligned hours ending 2024-12-31T23:00:00 for `43003`, `43057`, `43002`, `43058`, `42182`. Enough for `python -m v2.demo_engine` without the 151-station raw dump.
