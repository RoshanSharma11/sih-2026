import json

from fastapi.testclient import TestClient

from skyguard.api.main import create_app


def _write_catalog(path) -> None:
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-06T12:00:00Z",
                "notes": "test fixture",
                "stations": [
                    {
                        "station_id": "42181",
                        "name": "New Delhi / Palam",
                        "latitude": 28.5667,
                        "longitude": 77.1167,
                        "elevation_m": 220.0,
                        "cluster_id": "NORTH",
                        "completeness": {"temp_c": 0.99, "pres_hpa": 0.99, "rhum_pct": 0.99},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _client(tmp_path, catalog: bool = True) -> TestClient:
    stations = tmp_path / "stations.json"
    if catalog:
        _write_catalog(stations)
    app = create_app(db_path=tmp_path / "test.db", stations_path=stations)
    return TestClient(app)


def test_healthz_without_catalog(tmp_path) -> None:
    with _client(tmp_path, catalog=False) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["n_stations"] == 0
        assert body["n_isolates"] == 0
        assert "model_loaded" in body
        assert "threshold" in body


def test_ingest_without_catalog_is_503(tmp_path) -> None:
    with _client(tmp_path, catalog=False) as client:
        response = client.post(
            "/ingest",
            json={
                "station_id": "42181",
                "timestamp": "2024-07-01T14:00:00Z",
                "temp_c": 34.2,
                "pres_hpa": 1002.4,
                "rhum_pct": 71.0,
            },
        )
        assert response.status_code == 503


def test_list_stations_and_ingest_roundtrip(tmp_path) -> None:
    with _client(tmp_path) as client:
        stations = client.get("/stations")
        assert stations.status_code == 200
        assert stations.json()[0]["station_id"] == "42181"
        assert stations.json()[0]["cluster_id"] == "NORTH"

        payload = {
            "station_id": "42181",
            "timestamp": "2024-07-01T14:00:00Z",
            "temp_c": 34.2,
            "pres_hpa": 1002.4,
            "rhum_pct": 71.0,
        }
        created = client.post("/ingest", json=payload)
        assert created.status_code == 200
        body = created.json()
        # No 24h window → ML cannot run LSTM; honesty is UNCONFIRMED, not a fake CLEAN.
        assert body["label"] == "UNCONFIRMED_ANOMALY"
        assert body["pipeline_status"] == "UNKNOWN"
        assert body["observed"]["temp_c"] == 34.2

        duplicate = client.post("/ingest", json=payload)
        assert duplicate.status_code == 409

        missing = client.post("/ingest", json={**payload, "station_id": "99999", "timestamp": "2024-07-01T15:00:00Z"})
        assert missing.status_code == 404

        detail = client.get("/stations/42181")
        assert detail.status_code == 200
        assert detail.json()["latest"]["observed"]["temp_c"] == 34.2

        series = client.get("/stations/42181/telemetry")
        assert series.status_code == 200
        assert len(series.json()) == 1
        assert series.json()[0]["temp_observed"] == 34.2
        assert series.json()[0]["is_anomaly"] is True

        alerts = client.get("/alerts")
        assert alerts.status_code == 200
        assert alerts.json()[0]["fault_type"] in {"UNKNOWN", "COMM_ERROR"}

        unknown = client.get("/stations/99999")
        assert unknown.status_code == 404


def test_seed_and_tier1_faults(tmp_path) -> None:
    with _client(tmp_path) as client:
        missing = client.post(
            "/stations/99999/seed",
            json={"observations": [{"timestamp": "2024-06-30T15:00:00Z", "temp_c": 31.0, "pres_hpa": 1004.1, "rhum_pct": 68.0}]},
        )
        assert missing.status_code == 404

        seed = client.post(
            "/stations/42181/seed",
            json={
                "observations": [
                    {"timestamp": "2024-06-30T13:00:00Z", "temp_c": 31.0, "pres_hpa": 1004.1, "rhum_pct": 68.0},
                    {"timestamp": "2024-06-30T14:00:00Z", "temp_c": 31.2, "pres_hpa": 1004.0, "rhum_pct": 67.0},
                ]
            },
        )
        assert seed.status_code == 200
        assert seed.json() == {"station_id": "42181", "accepted": 2, "skipped": 0}
        again = client.post(
            "/stations/42181/seed",
            json={"observations": [{"timestamp": "2024-06-30T13:00:00Z", "temp_c": 31.0, "pres_hpa": 1004.1, "rhum_pct": 68.0}]},
        )
        assert again.json()["skipped"] == 1
        assert client.get("/alerts").json() == []

        comms = client.post(
            "/ingest",
            json={"station_id": "42181", "timestamp": "2024-06-30T15:00:00Z", "temp_c": None, "pres_hpa": 1004.0, "rhum_pct": 67.0},
        )
        assert comms.status_code == 200
        assert comms.json()["label"] == "PHYSICAL_FAULT"
        assert comms.json()["pipeline_status"] == "HARDWARE"
        assert comms.json()["fault_type"] == "COMM_ERROR"
        assert client.get("/alerts").json()[0]["fault_type"] == "COMM_ERROR"

        spike = client.post(
            "/ingest",
            json={"station_id": "42181", "timestamp": "2024-06-30T16:00:00Z", "temp_c": 99.0, "pres_hpa": 1004.0, "rhum_pct": 67.0},
        )
        assert spike.json()["label"] == "PHYSICAL_FAULT"
        assert spike.json()["pipeline_status"] == "HARDWARE"
        assert spike.json()["fault_type"] == "SPIKE"
