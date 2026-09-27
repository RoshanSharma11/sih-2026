"""GET /stations/{id}/timing reads the v2 cache. Ingest does not wait on it."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skyguard.api.main import create_app
from skyguard.config import BUDDY_EDGES_PATH, STATIONS_PATH


def _catalog(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-27T00:00:00Z",
                "stations": [
                    {
                        "station_id": "43003",
                        "name": "Bombay / Santacruz",
                        "latitude": 19.12,
                        "longitude": 72.85,
                        "elevation_m": 8.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class _Engine:
    def __init__(self) -> None:
        self.timing_calls: list[float] = []
        self.ingest_calls = 0

    def process_aws_data(self, payload: dict) -> dict:
        self.ingest_calls += 1
        return {"label": "CLEAN", "reason": "fixture", "predicted": {"temp": 26.0, "rhum": 65.0, "pres": 1013.0}}

    def get_timing(self, station_id: str, timestamp, wait_s: float = 0.0) -> dict:
        self.timing_calls.append(wait_s)
        if wait_s:
            return {
                "station_id": station_id,
                "timestamp": "2024-12-31T23:00:00",
                "status": "ready",
                "timing": {
                    "start_hour_in_window": 22,
                    "channel_attr": {"temp": 0.5, "rhum": 0.2, "pres": 0.3},
                    "hour_attr": [0.01] * 24,
                    "reason": "Anomaly attribution starts at hour 22 of the 24 h window (mostly temp).",
                },
            }
        return {
            "station_id": station_id,
            "timestamp": "2024-12-31T23:00:00",
            "status": "pending",
            "timing": None,
        }


def _client(tmp_path: Path) -> tuple[TestClient, _Engine]:
    stations = tmp_path / "stations.json"
    _catalog(stations)
    app = create_app(db_path=tmp_path / "test.db", stations_path=stations)
    engine = _Engine()
    client = TestClient(app)
    client.__enter__()
    app.state.qc_engine = engine
    return client, engine


def test_timing_reads_the_cache_and_maps_channel_names(tmp_path: Path) -> None:
    client, engine = _client(tmp_path)
    try:
        missing = client.get("/stations/43003/timing")
        assert missing.status_code == 422
        too_long = client.get("/stations/43003/timing", params={"ts": "2024-12-31T23:00:00Z", "wait_s": 11})
        assert too_long.status_code == 422
        unknown = client.get("/stations/99999/timing", params={"ts": "2024-12-31T23:00:00Z"})
        assert unknown.status_code == 404

        pending = client.get("/stations/43003/timing", params={"ts": "2024-12-31T23:00:00Z"})
        assert pending.status_code == 200, pending.text
        assert pending.json()["status"] == "pending"
        assert pending.json()["timing"] is None
        assert engine.timing_calls == [0.0]

        ready = client.get("/stations/43003/timing", params={"ts": "2024-12-31T23:00:00Z", "wait_s": 1})
        body = ready.json()
        assert body["status"] == "ready"
        assert body["timestamp"].startswith("2024-12-31T23:00:00")
        assert set(body["timing"]["channel_attr"]) == {"temp_c", "rhum_pct", "pres_hpa"}
        assert body["timing"]["channel_attr"]["temp_c"] == 0.5
        assert len(body["timing"]["hour_attr"]) == 24
        assert "hour 22" in body["timing"]["reason"]
        assert engine.timing_calls[-1] == 1.0
    finally:
        client.__exit__(None, None, None)


def test_ingest_does_not_read_timing(tmp_path: Path) -> None:
    client, engine = _client(tmp_path)
    try:
        seeded = client.post(
            "/stations/43003/seed",
            json={
                "observations": [
                    {
                        "timestamp": f"2024-12-31T{hour:02d}:00:00Z",
                        "temp_c": 20.0 + hour * 0.1,
                        "pres_hpa": 1010.0,
                        "rhum_pct": 60.0,
                    }
                    for hour in range(23)
                ]
            },
        )
        assert seeded.status_code == 200, seeded.text
        ingested = client.post(
            "/ingest",
            json={
                "station_id": "43003",
                "timestamp": "2024-12-31T23:00:00Z",
                "temp_c": 26.0,
                "pres_hpa": 1013.0,
                "rhum_pct": 65.0,
            },
        )
        assert ingested.status_code == 200, ingested.text
        assert "timing" not in ingested.json()
        assert engine.ingest_calls == 1
        assert engine.timing_calls == []
    finally:
        client.__exit__(None, None, None)


def test_live_anomaly_timing_is_cached_off_the_ingest_path(tmp_path: Path) -> None:
    if not STATIONS_PATH.exists() or not BUDDY_EDGES_PATH.exists():
        pytest.skip("product catalog is not imported")
    app = create_app(
        db_path=tmp_path / "live.db",
        stations_path=STATIONS_PATH,
        buddy_edges_path=BUDDY_EDGES_PATH,
    )
    with TestClient(app) as client:
        if not client.get("/healthz").json().get("model_loaded"):
            pytest.skip("v2 weights are not loaded")
        engine = client.app.state.qc_engine
        timing = getattr(engine, "timing", None)
        if timing is None or not timing.available:
            pytest.skip("TIMING worker is not available")
        missed = client.get("/stations/43003/timing", params={"ts": "2024-01-01T00:00:00Z"})
        assert missed.status_code == 200, missed.text
        assert missed.json()["status"] == "not_requested"
        hardware = client.post("/demo/replay", json={"story": "hardware"})
        assert hardware.status_code == 200, hardware.text
        immediate = client.get("/stations/43003/timing", params={"ts": "2024-12-31T23:00:00Z"})
        assert immediate.json()["status"] in {"pending", "ready"}
        ready = client.get(
            "/stations/43003/timing",
            params={"ts": "2024-12-31T23:00:00Z", "wait_s": 8},
        )
        body = ready.json()
        assert body["status"] == "ready"
        assert body["timing"]["reason"]
        assert "temp_c" in body["timing"]["channel_attr"]
        assert len(body["timing"]["hour_attr"]) == 24
