"""Demo: call process_aws_data and print the engine JSON.

From repo root:

    python test/demo_engine.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.engine import UnknownStationError, get_engine, process_aws_data

RAW = ROOT / "data" / "raw"
DEMO_STATION = "43003"


def _naive(ts) -> datetime:
    t = pd.Timestamp(ts).to_pydatetime()
    return t.replace(tzinfo=None)


def load_window(station_id: str, n: int = 24) -> list[dict]:
    path = RAW / f"{station_id}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Need {path} for the demo window")
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df["timestamp"] = df["timestamp"].map(_naive)
    df = df.sort_values("timestamp")
    df = df[df["timestamp"] >= datetime(2024, 1, 1)]
    df = df.dropna(subset=["temp", "rhum", "pres"])
    if len(df) < n:
        raise RuntimeError(f"{station_id} has only {len(df)} complete 2024 hours")
    tail = df.tail(n)
    rows = []
    for _, row in tail.iterrows():
        rows.append(
            {
                "timestamp": _naive(row["timestamp"]),
                "temp": float(row["temp"]),
                "rhum": float(row["rhum"]),
                "pres": float(row["pres"]),
            }
        )
    return rows


def load_buddies(station_id: str, window_end: datetime, n_hours: int = 24) -> list[dict]:
    engine = get_engine()
    neighbors = engine.buddy_graph.get(str(station_id), [])[:2]
    buddies = []
    for nb in neighbors:
        bid = str(nb["station_id"])
        path = RAW / f"{bid}.csv"
        if not path.exists():
            continue
        try:
            win = load_window(bid, n_hours)
        except (FileNotFoundError, RuntimeError):
            continue
        if _naive(win[-1]["timestamp"]) != window_end:
            # Align to the same last timestamp if possible.
            df = pd.read_csv(path, parse_dates=["timestamp"])
            df["timestamp"] = df["timestamp"].map(_naive)
            df = df.dropna(subset=["temp", "rhum", "pres"]).sort_values("timestamp")
            end = df[df["timestamp"] <= window_end].tail(n_hours)
            if len(end) < n_hours:
                continue
            win = [
                {
                    "timestamp": _naive(r["timestamp"]),
                    "temp": float(r["temp"]),
                    "rhum": float(r["rhum"]),
                    "pres": float(r["pres"]),
                }
                for _, r in end.iterrows()
            ]
        buddies.append(
            {
                "station_id": bid,
                "distance_km": nb.get("distance_km"),
                "window": win,
            }
        )
    return buddies


def show(title: str, payload: dict) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    try:
        result = process_aws_data(payload)
    except UnknownStationError as exc:
        result = {"error": "UnknownStationError", "detail": str(exc)}
    print(json.dumps(result, indent=2, default=str))


def main() -> None:
    window = load_window(DEMO_STATION, 24)
    last = window[-1]
    ts = _naive(last["timestamp"])
    buddies = load_buddies(DEMO_STATION, ts)

    engine = get_engine()
    print("model_loaded:", engine.lstm.loaded)
    print("threshold:", engine.lstm.threshold)
    print("station:", DEMO_STATION, "timestamp:", ts.isoformat())
    print("buddies sent:", [b["station_id"] for b in buddies])

    show(
        "1. Live-like ingest (24h window + buddies)",
        {
            "station_id": DEMO_STATION,
            "timestamp": ts,
            "temp": last["temp"],
            "rhum": last["rhum"],
            "pres": last["pres"],
            "window": window,
            "buddies": buddies,
        },
    )

    spiked = dict(last)
    spiked["temp"] = 99.0
    win_spike = list(window)
    win_spike[-1] = {**win_spike[-1], "temp": 99.0}
    show(
        "2. Physical fault (temp=99)",
        {
            "station_id": DEMO_STATION,
            "timestamp": ts,
            "temp": 99.0,
            "rhum": last["rhum"],
            "pres": last["pres"],
            "window": win_spike,
            "buddies": buddies,
        },
    )

    show(
        "3. Unknown station (should 400)",
        {
            "station_id": "99999",
            "timestamp": ts,
            "temp": last["temp"],
            "rhum": last["rhum"],
            "pres": last["pres"],
        },
    )


if __name__ == "__main__":
    main()
