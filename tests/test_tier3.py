import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from skyguard.api.main import create_app
from skyguard.data.inject import default_rng, inject_storm
from skyguard.engine.tier3 import ResidualStore, idw_value, storm_shape
from skyguard.engine.windows import WindowPoint


SKIP_IDENTITY_LIVE = pytest.mark.skip(reason="I5: live ingest is ml.engine, not IdentityDetector / NORTH cluster")


def _write_catalog(path, west: bool = False) -> None:
    stations = [
        {
            "station_id": "42181",
            "name": "New Delhi / Palam",
            "latitude": 28.5667,
            "longitude": 77.1167,
            "elevation_m": 220.0,
            "cluster_id": "NORTH",
            "completeness": {"temp_c": 0.99, "pres_hpa": 0.99, "rhum_pct": 0.99},
        },
        {
            "station_id": "42182",
            "name": "New Delhi / Safdarjung",
            "latitude": 28.5833,
            "longitude": 77.2,
            "elevation_m": 211.0,
            "cluster_id": "NORTH",
            "completeness": {"temp_c": 0.95, "pres_hpa": 0.95, "rhum_pct": 0.95},
        },
    ]
    if west:
        stations.append(
            {
                "station_id": "43003",
                "name": "Bombay / Santacruz",
                "latitude": 19.1167,
                "longitude": 72.85,
                "elevation_m": 8.0,
                "cluster_id": "WEST",
                "completeness": {"temp_c": 0.99, "pres_hpa": 0.99, "rhum_pct": 0.99},
            }
        )
    path.write_text(json.dumps({"generated_at": "2026-09-06T12:00:00Z", "notes": "tier3", "stations": stations}), encoding="utf-8")


def _client(tmp_path, west: bool = False) -> TestClient:
    stations = tmp_path / "stations.json"
    _write_catalog(stations, west=west)
    return TestClient(create_app(db_path=tmp_path / "test.db", stations_path=stations))


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed(client: TestClient, station_id: str, hours: int = 8, start: datetime | None = None, temp: float = 32.0, vary: bool = True) -> None:
    start = start or datetime(2024, 6, 30, 16, tzinfo=timezone.utc)
    observations = []
    for i in range(hours):
        observations.append(
            {
                "timestamp": _iso(start + timedelta(hours=i)),
                "temp_c": temp + (0.05 * i if vary else 0.0),
                "pres_hpa": 1005.0 + (0.1 * i if vary else 0.0),
                "rhum_pct": 60.0 + (0.1 * i if vary else 0.0),
            }
        )
    response = client.post(f"/stations/{station_id}/seed", json={"observations": observations})
    assert response.status_code == 200, response.text


def _ingest(client: TestClient, station_id: str, ts: datetime, temp_c: float, pres_hpa: float = 1005.0, rhum_pct: float = 60.0):
    return client.post(
        "/ingest",
        json={
            "station_id": station_id,
            "timestamp": _iso(ts),
            "temp_c": temp_c,
            "pres_hpa": pres_hpa,
            "rhum_pct": rhum_pct,
        },
    )


def test_idw_equal_distances_is_mean() -> None:
    assert abs(idw_value([10.0, 20.0], [5.0, 5.0]) - 15.0) < 1e-9
    closer = idw_value([10.0, 20.0], [1.0, 4.0])
    assert closer < 15.0


def test_storm_shape_requires_correlated_tph() -> None:
    previous = WindowPoint(datetime(2024, 7, 1, tzinfo=timezone.utc), 32.0, 1005.0, 60.0)
    storm, heat = storm_shape(WindowPoint(previous.timestamp, 22.0, 990.0, 90.0), previous)
    assert storm is True and heat is False
    spike, _ = storm_shape(WindowPoint(previous.timestamp, 48.0, 1005.0, 60.0), previous)
    assert spike is False


def test_residual_store_detects_monotonic_rise() -> None:
    store = ResidualStore(size=24)
    assert store.drift_detected("42181") is False
    for i in range(24):
        store.update("42181", 4.0 + i * 0.2)
    assert store.drift_detected("42181") is True


@SKIP_IDENTITY_LIVE
def test_storm_with_neighbors_is_weather(tmp_path) -> None:
    hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    storm = inject_storm(32.4, 1005.0, 60.8, rng=default_rng(26073))
    with _client(tmp_path) as client:
        _seed(client, "42181")
        _seed(client, "42182")
        first = _ingest(client, "42182", hour, *storm)
        assert first.status_code == 200
        second = _ingest(client, "42181", hour, *storm)
        assert second.status_code == 200
        body = second.json()
        assert body["pipeline_status"] == "GENUINE_WEATHER"
        assert body["fault_type"] == "GENUINE_WEATHER"
        detail = client.get("/stations/42181/telemetry?limit=1").json()[0]
        assert detail["is_anomaly"] is False
        assert detail["pipeline_status"] == "GENUINE_WEATHER"
        alerts = client.get("/alerts?station_id=42181").json()
        assert alerts[0]["fault_type"] == "GENUINE_WEATHER"


@SKIP_IDENTITY_LIVE
def test_lone_spike_is_hardware(tmp_path) -> None:
    hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with _client(tmp_path) as client:
        _seed(client, "42181")
        _seed(client, "42182")
        neighbor = _ingest(client, "42182", hour, 32.4, 1005.0, 60.8)
        assert neighbor.json()["pipeline_status"] == "CLEAN"
        spiked = _ingest(client, "42181", hour, 48.0, 1005.0, 60.8)
        body = spiked.json()
        assert body["pipeline_status"] == "HARDWARE"
        assert body["fault_type"] == "SPIKE"
        row = client.get("/stations/42181/telemetry?limit=1").json()[0]
        assert row["is_anomaly"] is True


@SKIP_IDENTITY_LIVE
def test_west_station_is_not_a_north_buddy(tmp_path) -> None:
    hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with _client(tmp_path, west=True) as client:
        _seed(client, "42181")
        _seed(client, "43003")
        west = _ingest(client, "43003", hour, 22.0, 990.0, 95.0)
        assert west.status_code == 200
        north = _ingest(client, "42181", hour, 22.0, 990.0, 95.0)
        assert north.json()["pipeline_status"] == "UNKNOWN"


@SKIP_IDENTITY_LIVE
def test_freeze_is_hardware(tmp_path) -> None:
    start = datetime(2024, 6, 30, 16, tzinfo=timezone.utc)
    with _client(tmp_path) as client:
        observations = []
        for i in range(5):
            observations.append(
                {
                    "timestamp": _iso(start + timedelta(hours=i)),
                    "temp_c": 31.0,
                    "pres_hpa": 1005.0 + 0.2 * i,
                    "rhum_pct": 60.0 + 0.2 * i,
                }
            )
        assert client.post("/stations/42181/seed", json={"observations": observations}).status_code == 200
        _seed(client, "42182", hours=5, start=start, temp=32.0, vary=True)
        hour = start + timedelta(hours=5)
        _ingest(client, "42182", hour, 32.3, 1005.4, 60.4)
        frozen = _ingest(client, "42181", hour, 31.0, 1006.0, 61.0)
        assert frozen.json()["fault_type"] == "FREEZE"
        assert frozen.json()["pipeline_status"] == "HARDWARE"


@SKIP_IDENTITY_LIVE
def test_health_drops_after_spikes_not_storm(tmp_path) -> None:
    storm_hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    storm = inject_storm(32.4, 1005.0, 60.8, rng=default_rng(1))
    with _client(tmp_path) as client:
        _seed(client, "42181")
        _seed(client, "42182")
        _ingest(client, "42182", storm_hour, *storm)
        weather = _ingest(client, "42181", storm_hour, *storm)
        assert weather.json()["fault_type"] == "GENUINE_WEATHER"
        assert weather.json()["health_score"] == 100.0

        for i in range(11):
            hour = storm_hour + timedelta(hours=1 + i)
            baseline = 32.0 + (i % 2)
            _ingest(client, "42182", hour, baseline, 1005.0, 60.0)
            spiked = _ingest(client, "42181", hour, 65.0 if i % 2 == 0 else 32.0, 1005.0, 60.0)
            assert spiked.json()["fault_type"] == "SPIKE"

        palam = client.get("/stations/42181").json()
        assert palam["health_score"] < 80
        assert palam["status"] == "DEGRADED"
        safdarjung = client.get("/stations/42182").json()
        assert safdarjung["health_score"] == 100.0
        assert safdarjung["status"] == "HEALTHY"
