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
    resolve_cli_ingest,
    run,
    shared_start,
)


def _catalog(path, station_ids=("42181", "42182"), buddy_ids=None) -> None:
    names = {
        "42181": ("New Delhi / Palam", 28.5667, 77.1167, 220.0, "NORTH"),
        "42182": ("New Delhi / Safdarjung", 28.5833, 77.2, 211.0, "NORTH"),
        "43003": ("Bombay / Santacruz", 19.1167, 72.85, 8.0, "WEST"),
    }
    default_buddies = {"42181": ["42182"], "42182": ["42181"], "43003": []}
    buddies = buddy_ids if buddy_ids is not None else default_buddies
    stations = []
    for station_id in station_ids:
        name, lat, lon, elev, cluster = names[station_id]
        stations.append(
            {
                "station_id": station_id,
                "name": name,
                "latitude": lat,
                "longitude": lon,
                "elevation_m": elev,
                "cluster_id": cluster,
                "buddy_ids": list(buddies.get(station_id, [])),
                "completeness": {"temp_c": 0.99, "pres_hpa": 0.99, "rhum_pct": 0.99},
            }
        )
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
        if client.get("/healthz").json().get("model_loaded"):
            assert all(row["pipeline_status"] == "CLEAN" for row in live)
            assert client.get("/alerts").json() == []
        else:
            assert all(row["label"] == "UNCONFIRMED_ANOMALY" for row in live)
            assert all(row["pipeline_status"] == "UNKNOWN" for row in live)

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


def test_resolve_cli_ingest_expands_buddies(tmp_path) -> None:
    stations = tmp_path / "stations.json"
    _catalog(stations, station_ids=("42181", "42182", "43003"))
    catalog = json.loads(stations.read_text())
    assert resolve_cli_ingest(catalog, ["42181"], with_buddies=True) == ["42181", "42182"]
    assert resolve_cli_ingest(catalog, ["42181"], with_buddies=False) == ["42181"]
    try:
        resolve_cli_ingest(catalog, ["99999"], with_buddies=True)
    except ValueError as exc:
        assert "99999" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_stream_cli_stations_seeds_ingest_set_only(tmp_path) -> None:
    stations = tmp_path / "stations.json"
    processed = tmp_path / "processed"
    processed.mkdir()
    _catalog(stations, station_ids=("42181", "42182", "43003"))
    start = datetime(2024, 6, 30, tzinfo=timezone.utc)
    for station_id in ("42181", "42182", "43003"):
        _hourly_frame(start, 28).to_parquet(processed / f"{station_id}.parquet", index=False)

    app = create_app(db_path=tmp_path / "test.db", stations_path=stations)
    demo_start = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with TestClient(app) as client:
        stats = run(
            client=client,
            stations_path=stations,
            processed_dir=processed,
            start=demo_start,
            hours=1,
            ms=0,
            stations=["42181"],
            with_buddies=True,
        )
        assert stats.seeded == 48
        assert stats.ingested == 2
        palam = client.get("/stations/42181/telemetry?limit=50")
        west = client.get("/stations/43003/telemetry?limit=50")
        assert palam.status_code == 200
        assert len([row for row in palam.json() if row["timestamp"].startswith("2024-07-01")]) == 1
        assert west.json() == []


def test_stream_honors_api_stream_filter(tmp_path) -> None:
    stations = tmp_path / "stations.json"
    processed = tmp_path / "processed"
    processed.mkdir()
    _catalog(stations, station_ids=("42181", "42182", "43003"))
    start = datetime(2024, 6, 30, tzinfo=timezone.utc)
    for station_id in ("42181", "42182", "43003"):
        _hourly_frame(start, 28).to_parquet(processed / f"{station_id}.parquet", index=False)

    app = create_app(db_path=tmp_path / "test.db", stations_path=stations)
    with TestClient(app) as client:
        armed = client.post("/demo/stream-filter", json={"station_ids": ["43003"], "include_buddies": False})
        assert armed.status_code == 200
        assert armed.json()["ingest"] == ["43003"]
        stats = run(
            client=client,
            stations_path=stations,
            processed_dir=processed,
            start=datetime(2024, 7, 1, tzinfo=timezone.utc),
            hours=1,
            ms=0,
        )
        assert stats.seeded == 24
        assert stats.ingested == 1
        assert client.get("/stations/42181/telemetry?limit=50").json() == []
        assert len(client.get("/stations/43003/telemetry?limit=50").json()) == 25
