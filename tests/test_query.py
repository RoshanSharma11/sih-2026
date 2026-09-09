import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from skyguard.api.main import create_app


def _write_catalog(path) -> None:
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-09T00:00:00Z",
                "notes": "I4 fixture",
                "stations": [
                    {
                        "station_id": "42181",
                        "name": "New Delhi / Palam",
                        "latitude": 28.5667,
                        "longitude": 77.1167,
                        "elevation_m": 220.0,
                        "cluster_id": "NORTH",
                        "isolate": False,
                        "buddy_ids": ["42182"],
                    },
                    {
                        "station_id": "42182",
                        "name": "New Delhi / Safdarjung",
                        "latitude": 28.5833,
                        "longitude": 77.2,
                        "elevation_m": 211.0,
                        "cluster_id": "NORTH",
                        "isolate": False,
                        "buddy_ids": ["42181"],
                    },
                    {
                        "station_id": "43003",
                        "name": "Bombay / Santacruz",
                        "latitude": 19.1167,
                        "longitude": 72.85,
                        "elevation_m": 8.0,
                        "isolate": True,
                        "buddy_ids": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _client(tmp_path) -> TestClient:
    stations = tmp_path / "stations.json"
    _write_catalog(stations)
    return TestClient(create_app(db_path=tmp_path / "test.db", stations_path=stations))


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_stations_ids_filter_and_latest_on_list(tmp_path) -> None:
    hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with _client(tmp_path) as client:
        all_rows = client.get("/stations")
        assert all_rows.status_code == 200
        assert [row["station_id"] for row in all_rows.json()] == ["42181", "42182", "43003"]
        palam = all_rows.json()[0]
        assert palam["buddy_ids"] == ["42182"]
        assert palam["isolate"] is False
        assert palam["latest"] is None
        west = all_rows.json()[2]
        assert west["isolate"] is True
        assert "cluster_id" not in west or west["cluster_id"] is None

        filtered = client.get("/stations", params={"ids": "43003,42181,99999"})
        assert [row["station_id"] for row in filtered.json()] == ["43003", "42181"]

        seed_hours = [
            {
                "timestamp": _iso(hour - timedelta(hours=24 - i)),
                "temp_c": 31.0 + 0.1 * i,
                "pres_hpa": 1004.0,
                "rhum_pct": 68.0,
            }
            for i in range(2)
        ]
        assert client.post("/stations/42181/seed", json={"observations": seed_hours}).status_code == 200
        ingested = client.post(
            "/ingest",
            json={
                "station_id": "42181",
                "timestamp": _iso(hour),
                "temp_c": 34.2,
                "pres_hpa": 1002.4,
                "rhum_pct": 71.0,
            },
        )
        assert ingested.status_code == 200

        listed = client.get("/stations", params={"ids": "42181"})
        latest = listed.json()[0]["latest"]
        assert latest["timestamp"] == "2024-07-01T00:00:00Z"
        assert latest["observed"]["temp_c"] == 34.2
        assert latest["label"] == ingested.json()["label"]
        assert latest["pipeline_status"] == ingested.json()["pipeline_status"]
        assert "fault_type" not in latest

        detail = client.get("/stations/42181")
        assert detail.json()["latest"]["observed"]["temp_c"] == 34.2
        assert detail.json()["buddy_ids"] == ["42182"]


def test_buddy_map_and_labels(tmp_path) -> None:
    hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with _client(tmp_path) as client:
        graph = client.get("/buddy-map")
        assert graph.status_code == 200
        body = graph.json()
        assert body["stations"] == ["42181", "42182", "43003"]
        assert body["isolates"] == ["43003"]
        assert body["buddies"]["42181"] == ["42182"]
        assert body["buddies"]["43003"] == []

        client.post(
            "/stations/42181/seed",
            json={
                "observations": [
                    {
                        "timestamp": _iso(hour - timedelta(hours=1)),
                        "temp_c": 31.0,
                        "pres_hpa": 1004.0,
                        "rhum_pct": 68.0,
                    }
                ]
            },
        )
        spike = client.post(
            "/ingest",
            json={
                "station_id": "42181",
                "timestamp": _iso(hour),
                "temp_c": 99.0,
                "pres_hpa": 1004.0,
                "rhum_pct": 67.0,
            },
        )
        assert spike.status_code == 200
        assert spike.json()["label"] == "PHYSICAL_FAULT"

        series = client.get("/stations/42181/telemetry")
        live = [row for row in series.json() if row["timestamp"] == "2024-07-01T00:00:00Z"]
        assert live[0]["label"] == "PHYSICAL_FAULT"
        seed_row = [row for row in series.json() if row["timestamp"].startswith("2024-06-30")][0]
        assert seed_row["label"] == "CLEAN"
        assert seed_row["is_anomaly"] is False

        alerts = client.get("/alerts")
        assert alerts.json()[0]["label"] == "PHYSICAL_FAULT"
        assert alerts.json()[0]["fault_type"] == "SPIKE"
