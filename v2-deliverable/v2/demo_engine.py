"""V2 demo stories. From repo root: python -m v2.demo_engine"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

try:
    import torch  # noqa: F401  Windows: before numpy
except ImportError:
    pass

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2.config import RAW_DIR
from v2.engine import UnknownStationError, get_engine, process_aws_data

DEMO = "43003"
MUMBAI_BUDDIES = ["43057", "43002", "43058"]
DEMO_FIXTURE = Path(__file__).resolve().parent / "data" / "demo_windows.json"


def _naive(ts) -> datetime:
    t = pd.Timestamp(ts).to_pydatetime()
    return t.replace(tzinfo=None)


def _rows_from_fixture(station_id: str) -> list[dict] | None:
    if not DEMO_FIXTURE.exists():
        return None
    blob = json.loads(DEMO_FIXTURE.read_text(encoding="utf-8"))
    raw = (blob.get("stations") or {}).get(str(station_id))
    if not raw:
        return None
    return [
        {
            "timestamp": _naive(row["timestamp"]),
            "temp": float(row["temp"]),
            "rhum": float(row["rhum"]),
            "pres": float(row["pres"]),
        }
        for row in raw
    ]


def load_hours(station_id: str, n: int = 24) -> list[dict]:
    fixture = _rows_from_fixture(station_id)
    if fixture is not None:
        if len(fixture) < n:
            raise RuntimeError(f"{station_id}: demo fixture has {len(fixture)} hours, need {n}")
        return fixture[-n:]
    path = RAW_DIR / f"{station_id}.csv"
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df["timestamp"] = df["timestamp"].map(_naive)
    df = df.sort_values("timestamp")
    df = df[df["timestamp"] >= datetime(2023, 6, 1)]
    df = df.dropna(subset=["temp", "rhum", "pres"])
    if len(df) < n:
        raise RuntimeError(f"{station_id}: need {n} complete hours in {path}")
    tail = df.tail(n)
    return [
        {
            "timestamp": _naive(row["timestamp"]),
            "temp": float(row["temp"]),
            "rhum": float(row["rhum"]),
            "pres": float(row["pres"]),
        }
        for _, row in tail.iterrows()
    ]


def aligned_window(station_id: str, end: datetime, n: int = 24) -> list[dict] | None:
    fixture = _rows_from_fixture(station_id)
    if fixture is not None:
        keep = [r for r in fixture if r["timestamp"] <= end][-n:]
        return keep if len(keep) >= n else None
    path = RAW_DIR / f"{station_id}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df["timestamp"] = df["timestamp"].map(_naive)
    df = df.dropna(subset=["temp", "rhum", "pres"]).sort_values("timestamp")
    end_rows = df[df["timestamp"] <= end].tail(n)
    if len(end_rows) < n:
        return None
    return [
        {
            "timestamp": _naive(r["timestamp"]),
            "temp": float(r["temp"]),
            "rhum": float(r["rhum"]),
            "pres": float(r["pres"]),
        }
        for _, r in end_rows.iterrows()
    ]


def load_buddies(end: datetime) -> list[dict]:
    engine = get_engine()
    out = []
    for bid in MUMBAI_BUDDIES:
        win = aligned_window(bid, end)
        if not win:
            continue
        dist = None
        for nb in engine.buddy_graph.get(DEMO, []):
            if str(nb["station_id"]) == bid:
                dist = nb.get("distance_km")
        out.append({"station_id": bid, "distance_km": dist, "window": win})
    return out


def summarize(title: str, payload: dict) -> dict:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    try:
        result = process_aws_data(payload)
    except UnknownStationError as exc:
        result = {"error": str(exc)}
        print(json.dumps(result, indent=2))
        return result
    keep = {
        "label": result["label"],
        "fault_type": result["fault_type"],
        "confidence": result["confidence"],
        "is_anomaly": result["is_anomaly"],
        "observed": result["observed"],
        "predicted": result["predicted"],
        "imputed_interval": result["imputed_interval"],
        "reason": result["reason"],
        "thermo": result["thermo"],
        "tier1": result["tier1"],
        "tier2": {k: result["tier2"][k] for k in ("ran", "score", "window_mse", "threshold") if k in result["tier2"]},
        "tier3": {
            k: result["tier3"][k]
            for k in ("performed", "method", "neighbors_agree", "usable_count", "buddy_ids", "reason_skip")
        },
        "timing": result.get("timing"),
        "health": result["health"],
    }
    print(json.dumps(keep, indent=2, default=str))
    return result


def main() -> None:
    get_engine(use_stgnn=True)
    window = load_hours(DEMO, 24)
    last = window[-1]
    ts = _naive(last["timestamp"])
    buddies = load_buddies(ts)
    engine = get_engine(use_stgnn=True)
    print("model_loaded:", engine.lstm.loaded)
    print("stgnn_on:", engine.use_stgnn, "stgnn_loaded:", engine.stgnn.loaded)
    print("overlay_loaded:", engine.overlay.loaded)
    print("threshold:", engine.lstm.threshold)
    print("raw:", RAW_DIR)
    print("timestamp:", ts.isoformat(), "buddies:", [b["station_id"] for b in buddies])

    base = {
        "station_id": DEMO,
        "timestamp": ts,
        "temp": last["temp"],
        "rhum": last["rhum"],
        "pres": last["pres"],
        "window": window,
        "buddies": buddies,
    }
    summarize("1. Clean Mumbai Santa Cruz", base)

    w55 = [dict(r) for r in window]
    w55[-1] = {**w55[-1], "temp": 55.0, "rhum": 95.0, "pres": 980.0}
    story2 = summarize(
        "2. 55 C + wild H/P on primary only (expect HARDWARE via T1 STEP + neighbors)",
        {**base, "temp": 55.0, "rhum": 95.0, "pres": 980.0, "window": w55},
    )
    print("timing_story2:", json.dumps(engine.get_timing(DEMO, ts, wait_s=8.0), indent=2, default=str))

    t8 = float(last["temp"]) + 8.0
    w8 = [dict(r) for r in window]
    w8[-1] = {**w8[-1], "temp": t8}
    summarize(
        "2b. +8 C primary only (T1 passes; expect HARDWARE if LSTM suspicious)",
        {**base, "temp": t8, "window": w8},
    )

    storm_t = float(last["temp"]) + 8.0
    wstorm = [dict(r) for r in window]
    wstorm[-1] = {**wstorm[-1], "temp": storm_t}
    storm_buddies = []
    for b in buddies:
        bw = [dict(r) for r in b["window"]]
        bw[-1] = {**bw[-1], "temp": float(bw[-1]["temp"]) + 8.0}
        storm_buddies.append({**b, "window": bw})
    summarize(
        "3. +8 C on Santa Cruz + Colaba + Juhu (same shock as 2b; expect WEATHER)",
        {**base, "temp": storm_t, "window": wstorm, "buddies": storm_buddies},
    )

    frozen = float(last["temp"])
    wfr = [dict(r) for r in window]
    for i in range(-12, 0):
        wfr[i] = {**wfr[i], "temp": frozen}
    summarize(
        "4. T frozen 12 h",
        {**base, "temp": frozen, "window": wfr},
    )

    summarize(
        "5. Missing temp (COMMUNICATION)",
        {**base, "temp": None, "window": [{**r, "temp": None} if i == 23 else r for i, r in enumerate(window)]},
    )

    for i in range(12):
        process_aws_data({**base, "temp": t8, "window": w8})
    last_h = summarize("6. After repeated +8 C hardware hours (health should drop)", {**base, "temp": t8, "window": w8})
    print("health_after_repeat:", last_h.get("health"))

    summarize("7. Unknown station", {"station_id": "99999", "timestamp": ts, "temp": 30.0, "rhum": 70.0, "pres": 1000.0})


if __name__ == "__main__":
    main()
