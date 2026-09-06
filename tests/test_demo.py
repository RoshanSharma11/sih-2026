import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from skyguard.api.main import create_app
from skyguard.data.inject import Observation
from skyguard.engine.demo import DemoController
from skyguard.schemas import Channel, ClusterId, DemoInjectRequest, DemoKind, FaultType


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
    path.write_text(
        json.dumps({"generated_at": "2026-09-06T12:00:00Z", "notes": "demo", "stations": stations}),
        encoding="utf-8",
    )


def _client(tmp_path, west: bool = False, catalog: bool = True) -> TestClient:
    stations = tmp_path / "stations.json"
    if catalog:
        _write_catalog(stations, west=west)
    return TestClient(create_app(db_path=tmp_path / "test.db", stations_path=stations))


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed(client: TestClient, station_id: str, hours: int = 8, start: datetime | None = None) -> None:
    start = start or datetime(2024, 6, 30, 16, tzinfo=timezone.utc)
    observations = []
    for i in range(hours):
        observations.append(
            {
                "timestamp": _iso(start + timedelta(hours=i)),
                "temp_c": 32.0 + 0.05 * i,
                "pres_hpa": 1005.0 + 0.1 * i,
                "rhum_pct": 60.0 + 0.1 * i,
            }
        )
    response = client.post(f"/stations/{station_id}/seed", json={"observations": observations})
    assert response.status_code == 200, response.text


def _ingest(client: TestClient, station_id: str, ts: datetime, temp_c: float = 32.4, pres_hpa: float = 1005.0, rhum_pct: float = 60.8):
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


def test_controller_cluster_storm_reuses_hour_deltas() -> None:
    demo = DemoController()
    demo.arm(
        DemoInjectRequest(target="cluster", cluster_id=ClusterId.NORTH, kind=DemoKind.GENUINE_WEATHER, duration_hours=2),
        ["42181", "42182"],
    )
    palam, kind_a = demo.apply("42181", Observation(32.0, 1005.0, 60.0))
    neighbor, kind_b = demo.apply("42182", Observation(33.0, 1006.0, 61.0))
    assert kind_a is FaultType.GENUINE_WEATHER
    assert kind_b is FaultType.GENUINE_WEATHER
    assert palam.temp_c is not None and neighbor.temp_c is not None
    assert abs((32.0 - palam.temp_c) - (33.0 - neighbor.temp_c)) < 1e-9
    assert palam.temp_c < 32.0
    assert palam.pres_hpa is not None and palam.pres_hpa < 1005.0
    assert palam.rhum_pct is not None and palam.rhum_pct > 60.0
    west, west_kind = demo.apply("43003", Observation(32.0, 1005.0, 60.0))
    assert west_kind is None
    assert west == Observation(32.0, 1005.0, 60.0)
    status = demo.status()
    assert status.overlays[0].remaining_hours == 1
    assert status.overlays[0].hour_index == 1


def test_controller_freeze_holds_first_value() -> None:
    demo = DemoController()
    demo.arm(
        DemoInjectRequest(
            target="station",
            station_id="42181",
            kind=DemoKind.FREEZE,
            channel=Channel.TEMP_C,
            duration_hours=3,
        ),
        ["42181"],
    )
    first, kind = demo.apply("42181", Observation(31.4, 1005.0, 60.0))
    second, _ = demo.apply("42181", Observation(33.0, 1006.0, 62.0))
    third, _ = demo.apply("42181", Observation(29.0, 1004.0, 58.0))
    assert kind is FaultType.FREEZE
    assert first.temp_c == 31.4
    assert second.temp_c == 31.4
    assert third.temp_c == 31.4
    assert second.pres_hpa == 1006.0
    spent, leftover = demo.apply("42181", Observation(28.0, 1004.0, 58.0))
    assert leftover is None
    assert spent.temp_c == 28.0
    assert demo.status().overlays == []


def test_demo_routes_and_status(tmp_path) -> None:
    with _client(tmp_path) as client:
        empty = client.get("/demo/status")
        assert empty.status_code == 200
        assert empty.json() == {"overlays": []}

        storm = client.post(
            "/demo/inject",
            json={"target": "cluster", "cluster_id": "NORTH", "kind": "GENUINE_WEATHER"},
        )
        assert storm.status_code == 200
        body = storm.json()["overlays"][0]
        assert body["kind"] == "GENUINE_WEATHER"
        assert body["station_ids"] == ["42181", "42182"]
        assert body["remaining_hours"] == 3
        assert body["channel"] is None

        spike = client.post(
            "/demo/inject",
            json={
                "target": "station",
                "station_id": "42181",
                "kind": "SPIKE",
                "channel": "temp_c",
            },
        )
        assert spike.status_code == 200
        assert len(spike.json()["overlays"]) == 2

        reset = client.post("/demo/reset")
        assert reset.status_code == 200
        assert reset.json() == {"overlays": []}


def test_demo_inject_errors(tmp_path) -> None:
    with _client(tmp_path) as client:
        storm_on_station = client.post(
            "/demo/inject",
            json={"target": "station", "station_id": "42181", "kind": "GENUINE_WEATHER"},
        )
        assert storm_on_station.status_code == 422

        spike_on_cluster = client.post(
            "/demo/inject",
            json={"target": "cluster", "cluster_id": "NORTH", "kind": "SPIKE", "channel": "temp_c"},
        )
        assert spike_on_cluster.status_code == 422

        missing_channel = client.post(
            "/demo/inject",
            json={"target": "station", "station_id": "42181", "kind": "SPIKE"},
        )
        assert missing_channel.status_code == 422

        unknown = client.post(
            "/demo/inject",
            json={"target": "station", "station_id": "99999", "kind": "COMM_ERROR"},
        )
        assert unknown.status_code == 404

        missing_cluster = client.post(
            "/demo/inject",
            json={"target": "cluster", "cluster_id": "WEST", "kind": "GENUINE_WEATHER"},
        )
        assert missing_cluster.status_code == 404

        bad_duration = client.post(
            "/demo/inject",
            json={
                "target": "station",
                "station_id": "42181",
                "kind": "SPIKE",
                "channel": "temp_c",
                "duration_hours": 0,
            },
        )
        assert bad_duration.status_code == 400


def test_demo_inject_without_catalog_is_503(tmp_path) -> None:
    with _client(tmp_path, catalog=False) as client:
        response = client.post(
            "/demo/inject",
            json={"target": "station", "station_id": "42181", "kind": "COMM_ERROR"},
        )
        assert response.status_code == 503


def test_storm_overlay_is_weather(tmp_path) -> None:
    hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with _client(tmp_path) as client:
        _seed(client, "42181")
        _seed(client, "42182")
        armed = client.post(
            "/demo/inject",
            json={"target": "cluster", "cluster_id": "NORTH", "kind": "GENUINE_WEATHER", "duration_hours": 1},
        )
        assert armed.status_code == 200
        first = _ingest(client, "42182", hour)
        assert first.status_code == 200
        assert first.json()["demo_injected"] == "GENUINE_WEATHER"
        second = _ingest(client, "42181", hour)
        body = second.json()
        assert body["demo_injected"] == "GENUINE_WEATHER"
        assert body["pipeline_status"] == "GENUINE_WEATHER"
        assert body["fault_type"] == "GENUINE_WEATHER"
        assert body["observed"]["temp_c"] < 32.4
        assert client.get("/demo/status").json() == {"overlays": []}


def test_spike_overlay_is_hardware(tmp_path) -> None:
    hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with _client(tmp_path) as client:
        _seed(client, "42181")
        _seed(client, "42182")
        client.post(
            "/demo/inject",
            json={"target": "station", "station_id": "42181", "kind": "SPIKE", "channel": "temp_c", "duration_hours": 1},
        )
        neighbor = _ingest(client, "42182", hour)
        assert neighbor.json()["pipeline_status"] == "CLEAN"
        assert neighbor.json()["demo_injected"] is None
        spiked = _ingest(client, "42181", hour)
        body = spiked.json()
        assert body["demo_injected"] == "SPIKE"
        assert body["pipeline_status"] == "HARDWARE"
        assert body["fault_type"] == "SPIKE"
        assert body["observed"]["temp_c"] != 32.4
        later = _ingest(client, "42181", hour + timedelta(hours=1), 32.5, 1005.1, 60.9)
        assert later.json()["demo_injected"] is None
        assert client.get("/demo/status").json() == {"overlays": []}


def test_storm_and_spike_produce_different_status(tmp_path) -> None:
    hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with _client(tmp_path) as client:
        _seed(client, "42181")
        _seed(client, "42182")
        client.post("/demo/inject", json={"target": "cluster", "cluster_id": "NORTH", "kind": "GENUINE_WEATHER", "duration_hours": 1})
        client.post(
            "/demo/inject",
            json={"target": "station", "station_id": "42181", "kind": "SPIKE", "channel": "temp_c", "duration_hours": 1},
        )
        neighbor = _ingest(client, "42182", hour)
        palam = _ingest(client, "42181", hour)
        assert neighbor.json()["demo_injected"] == "GENUINE_WEATHER"
        assert palam.json()["demo_injected"] == "SPIKE"
        assert palam.json()["pipeline_status"] == "HARDWARE"
        assert neighbor.json()["pipeline_status"] != palam.json()["pipeline_status"]


def test_duplicate_ingest_does_not_consume_overlay(tmp_path) -> None:
    hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with _client(tmp_path) as client:
        _seed(client, "42181")
        client.post(
            "/demo/inject",
            json={"target": "station", "station_id": "42181", "kind": "SPIKE", "channel": "temp_c", "duration_hours": 2},
        )
        first = _ingest(client, "42181", hour)
        assert first.status_code == 200
        remaining = client.get("/demo/status").json()["overlays"][0]["remaining_hours"]
        duplicate = _ingest(client, "42181", hour)
        assert duplicate.status_code == 409
        assert client.get("/demo/status").json()["overlays"][0]["remaining_hours"] == remaining


def test_west_is_not_affected_by_north_storm(tmp_path) -> None:
    hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with _client(tmp_path, west=True) as client:
        _seed(client, "43003")
        client.post("/demo/inject", json={"target": "cluster", "cluster_id": "NORTH", "kind": "GENUINE_WEATHER"})
        west = _ingest(client, "43003", hour)
        assert west.json()["demo_injected"] is None
        assert west.json()["observed"]["temp_c"] == 32.4
