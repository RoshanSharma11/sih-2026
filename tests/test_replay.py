"""Mumbai stories replay through /ingest. Mutations apply before QC."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skyguard.api.main import create_app
from skyguard.config import BUDDY_EDGES_PATH, STATIONS_PATH
from skyguard.data.inject import Observation
from skyguard.engine.demo import DemoController
from skyguard.engine.replay import load_demo_windows
from skyguard.errors import InvalidDemoRequest
from skyguard.schemas import FaultType, ReplayStory


def _catalog(path: Path) -> None:
    stations = [
        ("43003", "Bombay / Santacruz", 19.12, 72.85, False),
        ("43057", "Bombay / Colaba", 18.9, 72.82, False),
        ("43002", "Bombay / Juhu", 19.12, 72.83, False),
        ("43058", "Alibag", 18.63, 72.87, False),
        ("42182", "New Delhi / Safdarjung", 28.58, 77.2, True),
    ]
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-27T00:00:00Z",
                "stations": [
                    {
                        "station_id": station_id,
                        "name": name,
                        "latitude": lat,
                        "longitude": lon,
                        "elevation_m": 10.0,
                        "isolate": isolate,
                    }
                    for station_id, name, lat, lon, isolate in stations
                ],
            }
        ),
        encoding="utf-8",
    )


def _edges(path: Path) -> None:
    pairs = [
        ("43003", "43002", 1.755),
        ("43003", "43057", 24.349),
        ("43003", "43058", 53.78),
        ("43057", "43002", 24.159),
        ("43057", "43003", 24.349),
        ("43057", "43058", 30.119),
        ("43002", "43003", 1.755),
        ("43002", "43057", 24.159),
        ("43002", "43058", 53.866),
        ("43058", "43057", 30.119),
        ("43058", "43003", 53.78),
        ("43058", "43002", 53.866),
    ]
    path.write_text(
        json.dumps(
            {
                "edges": [
                    {
                        "primary_station_id": left,
                        "buddy_station_id": right,
                        "distance_km": distance,
                    }
                    for left, right, distance in pairs
                ]
            }
        ),
        encoding="utf-8",
    )


class _Engine:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def process_aws_data(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {
            "label": "CLEAN",
            "reason": "fixture",
            "predicted": {
                "temp": payload.get("temp"),
                "rhum": payload.get("rhum"),
                "pres": payload.get("pres"),
            },
        }


def _client(tmp_path: Path) -> tuple[TestClient, _Engine]:
    stations = tmp_path / "stations.json"
    edges = tmp_path / "edges.json"
    _catalog(stations)
    _edges(edges)
    app = create_app(db_path=tmp_path / "test.db", stations_path=stations, buddy_edges_path=edges)
    engine = _Engine()
    client = TestClient(app)
    client.__enter__()
    app.state.qc_engine = engine
    return client, engine


def _close(client: TestClient) -> None:
    client.__exit__(None, None, None)


def _santa(engine: _Engine) -> dict:
    matches = [payload for payload in engine.payloads if payload["station_id"] == "43003"]
    assert matches, "Santa Cruz was not scored"
    return matches[-1]


def _buddy_last(payload: dict) -> dict[str, float | None]:
    return {buddy["station_id"]: buddy["window"][-1]["temp"] for buddy in payload["buddies"]}


def test_replay_stories_mutate_before_qc_and_keep_a_newer_live_window(tmp_path: Path) -> None:
    client, engine = _client(tmp_path)
    try:
        hardware = client.post("/demo/replay", json={"story": "hardware"})
        assert hardware.status_code == 200, hardware.text
        body = hardware.json()
        assert body["story"] == "hardware"
        assert body["station_ids"] == ["43057", "43002", "43058", "43003"]
        assert body["end"].startswith("2024-12-31T23:00:00")
        santa = next(row for row in body["results"] if row["station_id"] == "43003")
        assert santa["warming_up"] is False
        assert santa["demo_injected"] == "SPIKE"
        assert santa["observed"] == {"temp_c": 55.0, "pres_hpa": 980.0, "rhum_pct": 95.0}
        for row in body["results"]:
            if row["station_id"] != "43003":
                assert row["demo_injected"] is None
                assert row["observed"]["temp_c"] != 55.0
        scored = _santa(engine)
        assert scored["temp"] == 55.0
        assert scored["rhum"] == 95.0
        assert scored["pres"] == 980.0
        assert len(scored["window"]) == 24
        assert len(scored["buddies"]) == 3
        assert all(len(buddy["window"]) == 24 for buddy in scored["buddies"])
        assert _buddy_last(scored) == {"43057": 24.4, "43002": 24.4, "43058": 24.0}

        engine.payloads.clear()
        weather = client.post("/demo/replay", json={"story": "weather"})
        assert weather.status_code == 200, weather.text
        weather_body = weather.json()
        assert weather_body["station_ids"] == ["43057", "43002", "43058", "43003"]
        by_id = {row["station_id"]: row for row in weather_body["results"]}
        assert by_id["43003"]["observed"]["temp_c"] == 34.0
        assert by_id["43003"]["demo_injected"] == "GENUINE_WEATHER"
        assert by_id["43057"]["observed"]["temp_c"] == 32.4
        assert by_id["43002"]["observed"]["temp_c"] == 32.4
        assert by_id["43058"]["observed"]["temp_c"] == 24.0
        assert by_id["43058"]["demo_injected"] is None
        heated = _santa(engine)
        assert heated["temp"] == 34.0
        assert _buddy_last(heated) == {"43057": 32.4, "43002": 32.4, "43058": 24.0}

        engine.payloads.clear()
        frozen = client.post("/demo/replay", json={"story": "freeze"})
        assert frozen.status_code == 200, frozen.text
        freeze_body = frozen.json()
        assert freeze_body["station_ids"] == ["43003"]
        assert freeze_body["results"][0]["demo_injected"] == "FREEZE"
        assert freeze_body["results"][0]["observed"]["temp_c"] == 26.0
        assert len(engine.payloads) == 1
        assert [row["temp"] for row in engine.payloads[0]["window"][-12:]] == [26.0] * 12

        engine.payloads.clear()
        comms = client.post("/demo/replay", json={"story": "comms"})
        assert comms.status_code == 200, comms.text
        assert comms.json()["results"][0]["demo_injected"] == "COMM_ERROR"
        assert comms.json()["results"][0]["observed"]["temp_c"] is None
        assert comms.json()["results"][0]["observed"]["rhum_pct"] == 65.0
        assert engine.payloads[-1]["temp"] is None
        assert engine.payloads[-1]["pres"] == 1013.0

        engine.payloads.clear()
        clean = client.post("/demo/replay", json={"story": "clean"})
        assert clean.status_code == 200, clean.text
        clean_body = clean.json()
        assert clean_body["station_ids"] == ["43057", "43002", "43058", "43003", "42182"]
        clean_santa = next(row for row in clean_body["results"] if row["station_id"] == "43003")
        assert clean_santa["demo_injected"] is None
        assert clean_santa["observed"]["temp_c"] == 26.0
        assert _santa(engine)["temp"] == 26.0
        assert client.get("/demo/status").json() == {"overlays": []}

        again = client.post("/demo/replay", json={"story": "hardware"})
        assert again.status_code == 200, again.text
        assert again.json()["results"][-1]["observed"]["temp_c"] == 55.0
    finally:
        _close(client)


def test_replay_leaves_a_newer_live_hour_in_the_window(tmp_path: Path) -> None:
    client, _engine = _client(tmp_path)
    try:
        live = client.post(
            "/ingest",
            json={
                "station_id": "43003",
                "timestamp": "2026-09-27T00:00:00Z",
                "temp_c": 31.0,
                "pres_hpa": 1008.0,
                "rhum_pct": 70.0,
            },
        )
        assert live.status_code == 200, live.text
        replay = client.post("/demo/replay", json={"story": "hardware"})
        assert replay.status_code == 200, replay.text
        points = client.app.state.windows.points("43003")
        assert len(points) == 1
        assert points[0].temp_c == 31.0
        rows = client.get("/stations/43003/telemetry").json()
        observed = {row["temp_observed"] for row in rows}
        assert 31.0 in observed
        assert 55.0 in observed
        follow = client.post(
            "/ingest",
            json={
                "station_id": "43003",
                "timestamp": "2026-09-27T01:00:00Z",
                "temp_c": 21.0,
                "pres_hpa": 1008.0,
                "rhum_pct": 70.0,
            },
        )
        assert follow.status_code == 200, follow.text
        assert follow.json()["observed"]["temp_c"] == 21.0
        assert follow.json()["demo_injected"] is None
        assert [point.temp_c for point in client.app.state.windows.points("43003")] == [31.0, 21.0]
    finally:
        _close(client)


def test_replay_rejects_unknown_story_and_missing_station(tmp_path: Path) -> None:
    client, _engine = _client(tmp_path)
    try:
        unknown = client.post("/demo/replay", json={"story": "palam"})
        assert unknown.status_code == 422
    finally:
        _close(client)

    stations = tmp_path / "only.json"
    stations.write_text(
        json.dumps(
            {
                "stations": [
                    {
                        "station_id": "42182",
                        "name": "Safdarjung",
                        "latitude": 28.58,
                        "longitude": 77.2,
                        "elevation_m": 211.0,
                        "isolate": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    app = create_app(db_path=tmp_path / "missing.db", stations_path=stations)
    with TestClient(app) as missing:
        response = missing.post("/demo/replay", json={"story": "hardware"})
        assert response.status_code == 404


def test_reset_clears_a_replay_arm() -> None:
    demo = DemoController()
    demo.arm_replay(ReplayStory.HARDWARE, ["43003"], 1)
    demo.reset()
    observed, kind = demo.apply("43003", Observation(26.0, 1013.0, 65.0))
    assert kind is None
    assert observed.temp_c == 26.0

    demo.arm_replay(ReplayStory.FREEZE, ["43003"], 2, freeze_anchor=26.0)
    first, freeze = demo.apply("43003", Observation(30.0, 1013.0, 65.0))
    assert freeze is FaultType.FREEZE
    assert first.temp_c == 26.0
    demo.clear_replay()
    second, kind = demo.apply("43003", Observation(30.0, 1013.0, 65.0))
    assert kind is None
    assert second.temp_c == 30.0


def test_demo_windows_must_end_on_the_replay_hour(tmp_path: Path) -> None:
    path = tmp_path / "demo_windows.json"
    path.write_text(
        json.dumps(
            {
                "end": "2024-12-30T23:00:00",
                "stations": {
                    station_id: [
                        {
                            "timestamp": f"2024-12-30T{hour:02d}:00:00",
                            "temp": 20.0,
                            "rhum": 60.0,
                            "pres": 1010.0,
                        }
                        for hour in range(24)
                    ]
                    for station_id in ("43003", "43057", "43002", "43058", "42182")
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(InvalidDemoRequest):
        load_demo_windows(path)


def test_replay_stories_match_v2_labels(tmp_path: Path) -> None:
    if not STATIONS_PATH.exists() or not BUDDY_EDGES_PATH.exists():
        pytest.skip("product catalog is not imported")
    app = create_app(
        db_path=tmp_path / "live.db",
        stations_path=STATIONS_PATH,
        buddy_edges_path=BUDDY_EDGES_PATH,
    )
    with TestClient(app) as client:
        health = client.get("/healthz").json()
        if not health.get("model_loaded"):
            pytest.skip("v2 weights are not loaded")
        hardware = client.post("/demo/replay", json={"story": "hardware"})
        assert hardware.status_code == 200, hardware.text
        santa = next(row for row in hardware.json()["results"] if row["station_id"] == "43003")
        assert santa["label"] == "HARDWARE_ANOMALY"
        assert santa["imputed_interval"] is not None
        imputed = santa["imputed"]["temp_c"]
        assert imputed is not None
        assert abs(imputed - 25.0) <= 5.0
        weather = client.post("/demo/replay", json={"story": "weather"})
        assert weather.status_code == 200, weather.text
        warmed = next(row for row in weather.json()["results"] if row["station_id"] == "43003")
        assert warmed["label"] == "GENUINE_WEATHER_EVENT"
        assert warmed["imputed_interval"] is None
        assert warmed["health_score"] == 100.0
        frozen = client.post("/demo/replay", json={"story": "freeze"})
        assert frozen.status_code == 200, frozen.text
        assert frozen.json()["results"][0]["label"] == "PHYSICAL_FAULT"
        assert frozen.json()["results"][0]["fault_type"] == "FREEZE"
        comms = client.post("/demo/replay", json={"story": "comms"})
        assert comms.status_code == 200, comms.text
        assert comms.json()["results"][0]["label"] == "PHYSICAL_FAULT"
        assert comms.json()["results"][0]["fault_type"] == "COMM_ERROR"
