"""Clean hourly streamer: seed 24h windows, then POST /ingest. No faults."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

from skyguard.config import DEMO_START, PROCESSED_DIR, STATIONS_PATH, STREAM_MS, WINDOW_HOURS
from skyguard.data.catalog import read_catalog

CHANNELS = ("temp_c", "pres_hpa", "rhum_pct")


@dataclass
class StreamStats:
    seeded: int = 0
    seed_skipped: int = 0
    ingested: int = 0
    skipped_duplicate: int = 0


def iso_z(value: datetime | pd.Timestamp) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def json_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    return float(value)


def parse_start(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_hourly(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    if "timestamp" not in frame.columns:
        frame = frame.reset_index()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    for channel in CHANNELS:
        if channel not in frame.columns:
            frame[channel] = pd.NA
        frame[channel] = pd.to_numeric(frame[channel], errors="coerce")
    return frame.sort_values("timestamp")[["timestamp", *CHANNELS]].reset_index(drop=True)


def load_station_frames(
    catalog: dict,
    processed_dir: Path | None = None,
) -> dict[str, pd.DataFrame]:
    out_dir = processed_dir or PROCESSED_DIR
    missing: list[str] = []
    frames: dict[str, pd.DataFrame] = {}
    for station in catalog["stations"]:
        station_id = station["station_id"]
        path = out_dir / f"{station_id}.parquet"
        if not path.exists():
            missing.append(station_id)
            continue
        frames[station_id] = load_hourly(path)
    if missing:
        raise FileNotFoundError(
            "Missing processed parquet for "
            + ", ".join(missing)
            + f". Run `python -m skyguard.data.fetch` and look in {out_dir}."
        )
    return frames


def shared_start(
    frames: dict[str, pd.DataFrame],
    requested: datetime | None = None,
) -> pd.Timestamp:
    floor = pd.Timestamp(requested or DEMO_START)
    if floor.tzinfo is None:
        floor = floor.tz_localize("UTC")
    else:
        floor = floor.tz_convert("UTC")
    sets = [set(pd.to_datetime(frame["timestamp"], utc=True)) for frame in frames.values()]
    if not sets:
        raise ValueError("No station series loaded")
    common = set.intersection(*sets)
    later = sorted(ts for ts in common if ts >= floor)
    if not later:
        raise ValueError(f"No shared timestamp on all stations at or after {iso_z(floor)}")
    return pd.Timestamp(later[0])


def hours_before(frame: pd.DataFrame, start: pd.Timestamp, n: int = WINDOW_HOURS) -> pd.DataFrame:
    window_start = start - pd.Timedelta(hours=n)
    times = pd.to_datetime(frame["timestamp"], utc=True)
    return frame[(times >= window_start) & (times < start)].copy()


def observation_fields(row: pd.Series | dict) -> dict:
    timestamp = row["timestamp"] if "timestamp" in row else row.name
    return {
        "timestamp": iso_z(timestamp),
        "temp_c": json_float(row["temp_c"]),
        "pres_hpa": json_float(row["pres_hpa"]),
        "rhum_pct": json_float(row["rhum_pct"]),
    }


def ingest_payload(station_id: str, row: pd.Series | dict, sequence_id: int) -> dict:
    return {"station_id": station_id, "sequence_id": sequence_id, **observation_fields(row)}


def wait_healthy(
    client: httpx.Client,
    timeout_s: float = 60.0,
    interval_s: float = 0.25,
) -> None:
    deadline = time.monotonic() + timeout_s
    last: object = None
    while time.monotonic() < deadline:
        try:
            response = client.get("/healthz")
            if response.status_code == 200 and response.json().get("ok") is True:
                return
            last = response.status_code
        except httpx.HTTPError as exc:
            last = exc
        time.sleep(interval_s)
    raise TimeoutError(f"API /healthz not ready: {last}")


def _row_at(frame: pd.DataFrame, tick: pd.Timestamp) -> pd.Series | None:
    times = pd.to_datetime(frame["timestamp"], utc=True)
    matched = frame[times == tick]
    if matched.empty:
        return None
    return matched.iloc[0]


def seed_station(client: httpx.Client, station_id: str, window: pd.DataFrame) -> tuple[int, int]:
    observations = [observation_fields(row) for row in window.to_dict(orient="records")]
    if not observations:
        print(f"seed {station_id} skipped (no hours before start)")
        return 0, 0
    response = client.post(f"/stations/{station_id}/seed", json={"observations": observations})
    if response.status_code >= 400:
        raise RuntimeError(f"seed {station_id} failed {response.status_code}: {response.text}")
    body = response.json()
    accepted = int(body["accepted"])
    skipped = int(body["skipped"])
    print(f"seed {station_id} accepted={accepted} skipped={skipped}")
    return accepted, skipped


def ingest_hour(
    client: httpx.Client,
    frames: dict[str, pd.DataFrame],
    tick: pd.Timestamp,
    sequence_id: int,
    stats: StreamStats,
) -> int:
    next_id = sequence_id
    for station_id, frame in frames.items():
        row = _row_at(frame, tick)
        if row is None:
            continue
        response = client.post("/ingest", json=ingest_payload(station_id, row, next_id))
        next_id += 1
        if response.status_code == 409:
            stats.skipped_duplicate += 1
            print(f"skip duplicate {station_id} {iso_z(tick)}")
            continue
        if response.status_code >= 400:
            raise RuntimeError(
                f"ingest {station_id} {iso_z(tick)} failed {response.status_code}: {response.text}"
            )
        stats.ingested += 1
    return next_id


def run(
    api: str = "http://127.0.0.1:8000",
    ms: int | None = None,
    start: datetime | None = None,
    hours: int | None = None,
    stations_path: Path | None = None,
    processed_dir: Path | None = None,
    client: httpx.Client | None = None,
    sleep_fn=time.sleep,
    health_timeout_s: float = 60.0,
) -> StreamStats:
    catalog = read_catalog(stations_path or STATIONS_PATH)
    frames = load_station_frames(catalog, processed_dir=processed_dir)
    demo_start = shared_start(frames, requested=start)
    delay_s = (STREAM_MS if ms is None else ms) / 1000.0
    stats = StreamStats()

    own_client = client is None
    http = client or httpx.Client(base_url=api.rstrip("/"), timeout=30.0)
    try:
        wait_healthy(http, timeout_s=health_timeout_s)
        for station_id, frame in frames.items():
            window = hours_before(frame, demo_start)
            if len(window) > 48:
                window = window.tail(48)
            accepted, skipped = seed_station(http, station_id, window)
            stats.seeded += accepted
            stats.seed_skipped += skipped

        end = min(pd.to_datetime(frame["timestamp"], utc=True).max() for frame in frames.values())
        ticks = pd.date_range(demo_start, end, freq="h", tz="UTC")
        if hours is not None:
            ticks = ticks[:hours]

        sequence_id = 1
        try:
            for tick in ticks:
                sequence_id = ingest_hour(http, frames, pd.Timestamp(tick), sequence_id, stats)
                print(
                    f"{iso_z(tick)} ingested={stats.ingested} skip409={stats.skipped_duplicate}"
                )
                if delay_s > 0:
                    sleep_fn(delay_s)
        except KeyboardInterrupt:
            print("stream stopped")
    finally:
        if own_client:
            http.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream clean SkyGuard observations into a running API.")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--ms", type=int, default=None, help="Sleep between weather-hours (default SKYGUARD_STREAM_MS).")
    parser.add_argument("--start", type=parse_start, default=None, help="First hour to ingest, ISO-8601 UTC.")
    parser.add_argument("--hours", type=int, default=None, help="Stop after this many weather-hours.")
    args = parser.parse_args()
    run(api=args.api, ms=args.ms, start=args.start, hours=args.hours)


if __name__ == "__main__":
    main()
