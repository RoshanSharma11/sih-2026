"""A station with fewer than 24 hours stays raw. The 24th hour gets the v2 label."""

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text

from skyguard.api.main import create_app
from skyguard.db.session import create_tables, make_engine


def _catalog(path) -> None:
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-27T00:00:00Z",
                "stations": [
                    {
                        "station_id": "42182",
                        "name": "New Delhi / Safdarjung",
                        "latitude": 28.58,
                        "longitude": 77.2,
                        "elevation_m": 211.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class _Engine:
    def __init__(self) -> None:
        self.calls = 0

    def process_aws_data(self, payload: dict) -> dict:
        self.calls += 1
        return {
            "label": "CLEAN",
            "confidence": 0.9,
            "fault_type": None,
            "reason": "within range",
            "predicted": {"temp": 30.0, "rhum": 60.0, "pres": 1000.0},
            "affected_variables": [],
            "tier1": {"passed": True, "violations": []},
            "imputed_interval": None,
            "thermo": {"dewpoint_c": 21.0, "td_minus_t": -9.0, "passed": True},
            "tier2": {
                "ran": True,
                "score": 0.001,
                "window_mse": 0.001,
                "threshold": 0.008487,
                "feature_contributions": {},
            },
            "tier3": {
                "performed": False,
                "method": "cw_idw",
                "buddy_ids": [],
                "usable_count": 0,
                "neighbors_agree": None,
                "reason_skip": "isolate_station",
                "mix": {},
                "corr": {},
            },
        }


def _hour(index: int) -> str:
    stamp = datetime(2024, 6, 30, tzinfo=timezone.utc) + timedelta(hours=index)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_short_window_is_raw_and_full_window_uses_the_engine_label(tmp_path) -> None:
    stations = tmp_path / "stations.json"
    _catalog(stations)
    app = create_app(db_path=tmp_path / "test.db", stations_path=stations)
    engine = _Engine()
    with TestClient(app) as client:
        app.state.qc_engine = engine
        first = client.post(
            "/ingest",
            json={
                "station_id": "42182",
                "timestamp": _hour(0),
                "temp_c": 31.5,
                "pres_hpa": 1002.0,
                "rhum_pct": 70.0,
            },
        )
        assert first.status_code == 200, first.text
        body = first.json()
        assert engine.calls == 0
        assert body["warming_up"] is True
        assert body["label"] is None
        assert body["observed"]["temp_c"] == 31.5
        assert body["imputed"]["temp_c"] is None
        assert body["health_score"] == 100.0
        assert client.get("/alerts").json() == []

        seeded = client.post(
            "/stations/42182/seed",
            json={
                "observations": [
                    {
                        "timestamp": _hour(index),
                        "temp_c": 30.0,
                        "pres_hpa": 1000.0,
                        "rhum_pct": 60.0,
                    }
                    for index in range(1, 23)
                ]
            },
        )
        assert seeded.status_code == 200
        assert seeded.json()["accepted"] == 22

        scored = client.post(
            "/ingest",
            json={
                "station_id": "42182",
                "timestamp": _hour(23),
                "temp_c": 32.0,
                "pres_hpa": 1001.0,
                "rhum_pct": 61.0,
            },
        )
        assert scored.status_code == 200, scored.text
        done = scored.json()
        assert engine.calls == 1
        assert done["warming_up"] is False
        assert done["label"] == "CLEAN"
        latest = client.get("/stations/42182").json()["latest"]
        assert latest["warming_up"] is False
        assert latest["label"] == "CLEAN"
        assert latest["observed"]["temp_c"] == 32.0


def test_old_not_null_label_column_stores_a_null_warming_hour(tmp_path) -> None:
    engine = make_engine(tmp_path / "old.db")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE telemetry_logs ("
                "id INTEGER PRIMARY KEY, "
                "station_id VARCHAR(20), "
                "timestamp DATETIME, "
                "is_anomaly BOOLEAN NOT NULL DEFAULT 0, "
                "label VARCHAR(40) NOT NULL DEFAULT 'CLEAN', "
                "pipeline_status VARCHAR(20) NOT NULL DEFAULT 'CLEAN')"
            )
        )
        conn.execute(text("CREATE INDEX ix_telemetry_logs_timestamp ON telemetry_logs (timestamp)"))
        conn.execute(
            text(
                "INSERT INTO telemetry_logs (station_id, timestamp, label, pipeline_status) "
                "VALUES ('42182', '2024-07-01 00:00:00', 'CLEAN', 'CLEAN')"
            )
        )
    create_tables(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO telemetry_logs (station_id, timestamp, is_anomaly, label, pipeline_status, warming_up) "
                "VALUES ('42182', '2024-07-01 01:00:00', 0, NULL, NULL, 1)"
            )
        )
        kept = conn.execute(
            text("SELECT label FROM telemetry_logs WHERE timestamp = '2024-07-01 00:00:00'")
        ).scalar()
        fresh = conn.execute(
            text(
                "SELECT label, warming_up FROM telemetry_logs "
                "WHERE timestamp = '2024-07-01 01:00:00'"
            )
        ).one()
    assert kept == "CLEAN"
    assert fresh[0] is None
    assert fresh[1] in (1, True)
