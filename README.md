# SkyGuard AI

Quality-control service for Indian Automatic Weather Stations (SIH PS 26073). Hourly **temperature, pressure, and humidity** are scored in-process so a real storm is not treated as a broken sensor. Raw readings are never overwritten; imputed values are overlay columns.

Production QC is `ml/ml/engine.py` (LSTM autoencoder + buddy-station graph). The FastAPI shell persists observations and serves the Streamlit console.

Demo neighborhood: Palam `42181`, Safdarjung `42182`, Meerut `42139`.

## Setup

Python 3.10+. From the repo root:

```text
python -m venv .venv
source .venv/bin/activate
pip install -e ".[ui]"
pip install -r ml/ml/requirements.txt
```

Trained weights load from `ml/ml/artifacts/` when the API starts.

## Run

Three terminals:

```text
python -m uvicorn skyguard.api.main:app --host 127.0.0.1 --port 8000 --reload
```

Wait for startup. API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

```text
python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 --start 2024-07-01T00:00:00Z --stations 42181 --with-buddies
```

Seeds 24 clean hours for Palam and its buddies, then streams one weather-hour every 200 ms. Hourly parquet must already be present under `data/processed/`.

```text
python -m streamlit run frontend/app.py
```

Console: [http://127.0.0.1:8501](http://127.0.0.1:8501)

## Demo inject

While the stream is running:

```text
curl -X POST http://127.0.0.1:8000/demo/inject \
  -H 'Content-Type: application/json' \
  -d '{"target":"neighborhood","station_id":"42181","kind":"GENUINE_WEATHER"}'

curl -X POST http://127.0.0.1:8000/demo/inject \
  -H 'Content-Type: application/json' \
  -d '{"target":"station","station_id":"42181","kind":"SPIKE","channel":"temp_c"}'
```

Storms target a neighborhood (station + 1-hop buddies). Hardware faults target one station. `POST /demo/reset` clears armed overlays.

## License

MIT License

Copyright (c) 2026 NSUT-SIH-26

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
