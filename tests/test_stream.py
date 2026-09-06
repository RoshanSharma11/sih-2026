import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from skyguard.api.main import create_app
from skyguard.data.stream import (
    hours_before,
    ingest_payload,
    json_float,
    load_station_frames,
    run,
    shared_start,
)


def _catalog(path, station_ids=("42181", "42182")) -> None:
    stations = [
        {
            "station_id": station_ids[0],
            "name": "New Delhi / Palam",
            "latitude": 28.5667,
            "longitude": 77.1167,
            "elevation_m": 220.0,
            "cluster_id": "NORTH",
            "completeness": {"temp_c": 0.99, "pres_hpa": 0.99, "rhum_pct": 0.99},
        },
        {
            "station_id": station_ids[1],
            "name": "New Delhi / Safdarjung",
            "latitude": 28.5833,
            "longitude": 77.2,
            "elevation_m": 211.0,
            "cluster_id": "NORTH",
            "completeness": {"temp_c": 0.95, "pres_hpa": 0.95, "rhum_pct": 0.95},
        },
    ]
    path.write_text(
        json.dumps({"generated_at": "2026-09-06T12:00:00Z", "notes": "stream fixture", "stations": stations}),
        encoding="utf-8",
    )


def _hourly_frame(start: datetime, hours: int, temp: float = 31.0) -> pd.DataFrame:
    timestamps = [start + timedelta(hours=i) for i in range(hours)]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "temp_c": [temp + (i * 0.05) for i in range(hours)],
            "pres_hpa": [1004.0] * hours,
            "rhum_pct": [68.0] * hours,
        }
    )


def test_json_float_maps_nan_to_none() -> None:
    assert json_float(np.nan) is None
    assert json_float(pd.NA) is None
    assert json_float(31.5) == 31.5


def test_shared_start_is_first_common_hour() -> None:
    start_a = datetime(2024, 6, 30, 22, tzinfo=timezone.utc)
    start_b = datetime(2024, 7, 1, 1, tzinfo=timezone.utc)
    frames = {
        "A": _hourly_frame(start_a, 6),
        "B": _hourly_frame(start_b, 4),
    }
    found = shared_start(frames, requested=datetime(2024, 7, 1, tzinfo=timezone.utc))
    assert found == pd.Timestamp("2024-07-01T01:00:00Z")


def test_hours_before_takes_calendar_window() -> None:
    start = datetime(2024, 6, 30, tzinfo=timezone.utc)
    frame = _hourly_frame(start, 30)
    demo = pd.Timestamp("2024-07-01T00:00:00Z")
    window = hours_before(frame, demo, n=24)
    assert len(window) == 24
    assert window["timestamp"].iloc[0] == pd.Timestamp("2024-06-30T00:00:00Z")
    assert window["timestamp"].iloc[-1] == pd.Timestamp("2024-06-30T23:00:00Z")


def test_ingest_payload_uses_zulu_and_nulls() -> None:
    row = {"timestamp": datetime(2024, 7, 1, 14, tzinfo=timezone.utc), "temp_c": np.nan, "pres_hpa": 1002.4, "rhum_pct": 71.0}
    payload = ingest_payload("42181", row, sequence_id=7)
    assert payload == {
        "station_id": "42181",
        "sequence_id": 7,
        "timestamp": "2024-07-01T14:00:00Z",
        "temp_c": None,
        "pres_hpa": 1002.4,
        "rhum_pct": 71.0,
    }


def test_missing_parquet_raises(tmp_path) -> None:
    stations = tmp_path / "stations.json"
    _catalog(stations)
    try:
        load_station_frames(json.loads(stations.read_text()), processed_dir=tmp_path)
    except FileNotFoundError as exc:
        assert "42181" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_stream_seeds_then_ingests_and_skips_duplicates(tmp_path) -> None:
    stations = tmp_path / "stations.json"
    processed = tmp_path / "processed"
    processed.mkdir()
    _catalog(stations)
    start = datetime(2024, 6, 30, tzinfo=timezone.utc)
    _hourly_frame(start, 28).to_parquet(processed / "42181.parquet", index=False)
    _hourly_frame(start, 28).to_parquet(processed / "42182.parquet", index=False)

    app = create_app(db_path=tmp_path / "test.db", stations_path=stations)
    demo_start = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with TestClient(app) as client:
        stats = run(
            client=client,
            stations_path=stations,
            processed_dir=processed,
            start=demo_start,
            hours=2,
            ms=0,
        )
        assert stats.seeded == 48
        assert stats.ingested == 4
        assert stats.skipped_duplicate == 0

        series = client.get("/stations/42181/telemetry?limit=50")
        assert series.status_code == 200
        rows = series.json()
        assert len(rows) == 26
        live = [row for row in rows if row["timestamp"].startswith("2024-07-01")]
        assert len(live) == 2
        assert all(row["pipeline_status"] == "CLEAN" for row in live)
        assert client.get("/alerts").json() == []

        again = run(
            client=client,
            stations_path=stations,
            processed_dir=processed,
            start=demo_start,
            hours=2,
            ms=0,
        )
        assert again.seed_skipped == 48
        assert again.skipped_duplicate == 4
        assert again.ingested == 0
        assert len(client.get("/stations/42181/telemetry?limit=50").json()) == 26


def test_stream_skips_station_hours_missing_from_parquet(tmp_path) -> None:
    stations = tmp_path / "stations.json"
    processed = tmp_path / "processed"
    processed.mkdir()
    _catalog(stations)
    start = datetime(2024, 6, 30, tzinfo=timezone.utc)
    left = _hourly_frame(start, 28)
    right = _hourly_frame(start, 28)
    right = right[right["timestamp"] != datetime(2024, 7, 1, 1, tzinfo=timezone.utc)]
    left.to_parquet(processed / "42181.parquet", index=False)
    right.to_parquet(processed / "42182.parquet", index=False)

    app = create_app(db_path=tmp_path / "test.db", stations_path=stations)
    with TestClient(app) as client:
        stats = run(
            client=client,
            stations_path=stations,
            processed_dir=processed,
            start=datetime(2024, 7, 1, tzinfo=timezone.utc),
            hours=3,
            ms=0,
        )
        assert stats.ingested == 5
        gap = [
            row
            for row in client.get("/stations/42182/telemetry?limit=50").json()
            if row["timestamp"].startswith("2024-07-01T01")
        ]
        assert gap == []
