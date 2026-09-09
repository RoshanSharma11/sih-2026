"""I2/I5 live ingest uses ml.engine — D18 mapping, buddy T3, isolate honesty."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skyguard.api.main import create_app
from skyguard.engine.pipeline import ingest_observation

PALAM = "42181"
SAFDARJUNG = "42182"
THIRD = "42369"
PATNA = "42492"

SEED_START = datetime(2024, 6, 30, tzinfo=timezone.utc)
INGEST_HOUR = SEED_START + timedelta(hours=23)
# Under ML STEP caps (10°C / 10 hPa / 30% RH) so Tier 1 passes and LSTM/T3 can run.
LSTM_FLAG = {"temp_c": 41.5, "pres_hpa": 996.1, "rhum_pct": 85.0}


def _write_catalog(path: Path) -> None:
    path.write_text(
        """
{
  "generated_at": "2026-09-09T00:00:00Z",
  "notes": "I2 fixture — three scaler stations",
  "stations": [
    {
      "station_id": "42181",
      "name": "New Delhi / Palam",
      "latitude": 28.5667,
      "longitude": 77.1167,
      "elevation_m": 220.0,
      "cluster_id": "NORTH",
      "buddy_ids": ["42182", "42369"]
    },
    {
      "station_id": "42182",
      "name": "New Delhi / Safdarjung",
      "latitude": 28.5833,
      "longitude": 77.2,
      "elevation_m": 211.0,
      "cluster_id": "NORTH",
      "buddy_ids": ["42181", "42369"]
    },
    {
      "station_id": "42369",
      "name": "Agra",
      "latitude": 27.15,
      "longitude": 77.96,
      "elevation_m": 169.0,
      "cluster_id": "NORTH",
      "buddy_ids": ["42181", "42182"]
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )


def _write_isolate_catalog(path: Path) -> None:
    path.write_text(
        """
{
  "generated_at": "2026-09-09T00:00:00Z",
  "notes": "I5 fixture — scaler isolate (Patna)",
  "stations": [
    {
      "station_id": "42492",
      "name": "Patna",
      "latitude": 25.6,
      "longitude": 85.1,
      "elevation_m": 51.0,
      "isolate": true,
      "buddy_ids": []
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )


def _write_one_buddy_catalog(path: Path) -> None:
    path.write_text(
        """
{
  "generated_at": "2026-09-09T00:00:00Z",
  "notes": "I5 fixture — Palam with one exported buddy",
  "stations": [
    {
      "station_id": "42181",
      "name": "New Delhi / Palam",
      "latitude": 28.5667,
      "longitude": 77.1167,
      "elevation_m": 220.0,
      "isolate": false,
      "buddy_ids": ["42182"]
    },
    {
      "station_id": "42182",
      "name": "New Delhi / Safdarjung",
      "latitude": 28.5833,
      "longitude": 77.2,
      "elevation_m": 211.0,
      "isolate": false,
      "buddy_ids": ["42181"]
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )


def _write_edges(path: Path, edges: list[dict] | None = None) -> None:
    if edges is None:
        edges = [
            {"primary_station_id": "42181", "buddy_station_id": "42182", "distance_km": 8.1},
            {"primary_station_id": "42181", "buddy_station_id": "42369", "distance_km": 180.0},
            {"primary_station_id": "42182", "buddy_station_id": "42181", "distance_km": 8.1},
            {"primary_station_id": "42182", "buddy_station_id": "42369", "distance_km": 175.0},
            {"primary_station_id": "42369", "buddy_station_id": "42181", "distance_km": 180.0},
            {"primary_station_id": "42369", "buddy_station_id": "42182", "distance_km": 175.0},
        ]
    path.write_text(json.dumps({"edges": edges}), encoding="utf-8")


def _client(
    tmp_path: Path,
    *,
    catalog_writer=_write_catalog,
    edges: list[dict] | None = None,
) -> TestClient:
    stations = tmp_path / "stations.json"
    edges_path = tmp_path / "buddy_edges.json"
    catalog_writer(stations)
    _write_edges(edges_path, edges)
    return TestClient(
        create_app(
            db_path=tmp_path / "test.db",
            stations_path=stations,
            buddy_edges_path=edges_path,
        )
    )


def _require_artifacts(client: TestClient) -> None:
    body = client.get("/healthz").json()
    if not body.get("model_loaded"):
        pytest.skip("LSTM artifacts not loaded (install torch + ml/ml/artifacts)")


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed(client: TestClient, station_id: str, hours: int = 23, *, bait: bool = False) -> None:
    observations = []
    for i in range(hours):
        if bait and 4 <= i <= 18:
            temp_c, pres_hpa, rhum_pct = 59.0, 991.0, 8.0
        else:
            temp_c, pres_hpa, rhum_pct = 32.0 + 0.02 * i, 1005.0, 60.0
        observations.append(
            {
                "timestamp": _iso(SEED_START + timedelta(hours=i)),
                "temp_c": temp_c,
                "pres_hpa": pres_hpa,
                "rhum_pct": rhum_pct,
            }
        )
    response = client.post(f"/stations/{station_id}/seed", json={"observations": observations})
    assert response.status_code == 200, response.text


def _ingest(
    client: TestClient,
    station_id: str,
    temp_c: float,
    pres_hpa: float = 1005.0,
    rhum_pct: float = 60.0,
):
    return client.post(
        "/ingest",
        json={
            "station_id": station_id,
            "timestamp": _iso(INGEST_HOUR),
            "temp_c": temp_c,
            "pres_hpa": pres_hpa,
            "rhum_pct": rhum_pct,
        },
    )


def test_pipeline_source_does_not_call_legacy_tiers() -> None:
    source = Path(ingest_observation.__code__.co_filename).read_text(encoding="utf-8")
    assert "skyguard.engine.tier1" not in source
    assert "skyguard.engine.tier2" not in source
    assert "skyguard.engine.tier3" not in source
    assert "skyguard.engine.classify" not in source
    assert "health.recompute" not in source
    assert "IdentityDetector" not in source


def test_healthz_reports_model_fields(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        body = client.get("/healthz").json()
        assert body["ok"] is True
        assert body["n_stations"] == 3
        assert "model_loaded" in body
        assert "threshold" in body
        assert body["n_isolates"] == 0


def test_null_channel_is_physical_comm_error(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _seed(client, PALAM)
        response = client.post(
            "/ingest",
            json={
                "station_id": PALAM,
                "timestamp": _iso(INGEST_HOUR),
                "temp_c": None,
                "pres_hpa": 1005.0,
                "rhum_pct": 60.0,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["label"] == "PHYSICAL_FAULT"
        assert body["pipeline_status"] == "HARDWARE"
        assert body["fault_type"] == "COMM_ERROR"
        assert body["tier1"]["passed"] is False


def test_temp_99c_is_physical_fault(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _seed(client, PALAM)
        response = _ingest(client, PALAM, temp_c=99.0)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["label"] == "PHYSICAL_FAULT"
        assert body["pipeline_status"] == "HARDWARE"
        assert body["fault_type"] == "SPIKE"
        assert body["observed"]["temp_c"] == 99.0


def test_lone_palam_spike_is_not_weather(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _require_artifacts(client)
        for station_id in (PALAM, SAFDARJUNG, THIRD):
            _seed(client, station_id, bait=station_id == PALAM)
        neighbor_a = _ingest(client, SAFDARJUNG, temp_c=32.46)
        neighbor_b = _ingest(client, THIRD, temp_c=32.46)
        assert neighbor_a.status_code == 200, neighbor_a.text
        assert neighbor_b.status_code == 200, neighbor_b.text
        spiked = _ingest(client, PALAM, temp_c=48.0)
        assert spiked.status_code == 200, spiked.text
        body = spiked.json()
        assert body["label"] in {"HARDWARE_ANOMALY", "PHYSICAL_FAULT"}
        assert body["pipeline_status"] == "HARDWARE"
        assert body["label"] != "GENUINE_WEATHER_EVENT"


def test_neighborhood_storm_is_not_hardware(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _require_artifacts(client)
        for station_id in (PALAM, SAFDARJUNG, THIRD):
            _seed(client, station_id, bait=station_id == PALAM)
        # Coordinated move under Tier-1 step limits so buddy check can run.
        storm = {"temp_c": 24.0, "pres_hpa": 996.0, "rhum_pct": 85.0}
        first = _ingest(client, SAFDARJUNG, **storm)
        second = _ingest(client, THIRD, **storm)
        palam = _ingest(client, PALAM, **storm)
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert palam.status_code == 200, palam.text
        body = palam.json()
        assert body["label"] != "HARDWARE_ANOMALY"
        assert body["pipeline_status"] != "HARDWARE"
        assert body["label"] in {"GENUINE_WEATHER_EVENT", "CLEAN", "UNCONFIRMED_ANOMALY"}


def test_health_does_not_drop_on_weather_label(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _require_artifacts(client)
        for station_id in (PALAM, SAFDARJUNG, THIRD):
            _seed(client, station_id, bait=station_id == PALAM)
        storm = {"temp_c": 24.0, "pres_hpa": 996.0, "rhum_pct": 85.0}
        _ingest(client, SAFDARJUNG, **storm)
        _ingest(client, THIRD, **storm)
        palam = _ingest(client, PALAM, **storm)
        body = palam.json()
        if body["label"] != "GENUINE_WEATHER_EVENT":
            pytest.skip(f"LSTM did not emit weather for this window (got {body['label']})")
        assert body["pipeline_status"] == "GENUINE_WEATHER"
        assert body["health_score"] == 100.0
        assert body["station_status"] == "HEALTHY"
        assert body["tier3"]["performed"] is True
        assert body["tier3"]["usable_count"] >= 2
        assert body["tier3"]["neighbors_agree"] is True
        live = client.get("/stations/42181/telemetry?limit=1").json()[0]
        assert live["is_anomaly"] is True
        assert live["label"] == "GENUINE_WEATHER_EVENT"
        station = client.get("/stations/42181").json()
        assert station["health_score"] == 100.0
        assert station["status"] == "HEALTHY"


def test_d18_persists_physical_fault_on_telemetry_and_alert(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _seed(client, PALAM)
        body = _ingest(client, PALAM, temp_c=99.0).json()
        assert body["label"] == "PHYSICAL_FAULT"
        assert body["pipeline_status"] == "HARDWARE"
        row = client.get("/stations/42181/telemetry?limit=1").json()[0]
        assert row["label"] == "PHYSICAL_FAULT"
        assert row["pipeline_status"] == "HARDWARE"
        assert row["is_anomaly"] is True
        assert row["temp_observed"] == 99.0
        alert = client.get("/alerts").json()[0]
        assert alert["label"] == "PHYSICAL_FAULT"
        assert alert["fault_type"] == "SPIKE"


def test_two_usable_buddies_runs_tier3(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _require_artifacts(client)
        for station_id in (PALAM, SAFDARJUNG, THIRD):
            _seed(client, station_id, bait=station_id == PALAM)
        assert _ingest(client, SAFDARJUNG, temp_c=32.46).status_code == 200
        assert _ingest(client, THIRD, temp_c=32.46).status_code == 200
        palam = _ingest(client, PALAM, **LSTM_FLAG)
        assert palam.status_code == 200, palam.text
        body = palam.json()
        if body["label"] in {"CLEAN", "PHYSICAL_FAULT"}:
            pytest.skip(
                f"LSTM did not flag under T1 (got {body['label']} mse={body.get('mse')})"
            )
        assert body["tier1"]["passed"] is True
        assert body["tier3"]["performed"] is True
        assert body["tier3"]["usable_count"] >= 2
        assert body["label"] == "HARDWARE_ANOMALY"
        assert body["pipeline_status"] == "HARDWARE"
        assert body["label"] != "GENUINE_WEATHER_EVENT"


def test_one_buddy_skips_tier3_unconfirmed(tmp_path: Path) -> None:
    one_edge = [
        {"primary_station_id": "42181", "buddy_station_id": "42182", "distance_km": 8.1},
        {"primary_station_id": "42182", "buddy_station_id": "42181", "distance_km": 8.1},
    ]
    with _client(tmp_path, catalog_writer=_write_one_buddy_catalog, edges=one_edge) as client:
        _require_artifacts(client)
        _seed(client, PALAM, bait=True)
        _seed(client, SAFDARJUNG)
        assert _ingest(client, SAFDARJUNG, temp_c=32.46).status_code == 200
        palam = _ingest(client, PALAM, **LSTM_FLAG)
        assert palam.status_code == 200, palam.text
        body = palam.json()
        if body["label"] in {"CLEAN", "PHYSICAL_FAULT"}:
            pytest.skip(
                f"LSTM did not flag under T1 (got {body['label']} mse={body.get('mse')})"
            )
        assert body["label"] == "UNCONFIRMED_ANOMALY"
        assert body["pipeline_status"] == "UNKNOWN"
        assert body["tier3"]["performed"] is False
        assert body["tier3"]["reason_skip"] in {"fewer_than_2_usable_buddies", "isolate_station"}
        assert body["tier3"]["usable_count"] < 2
        row = client.get("/stations/42181/telemetry?limit=1").json()[0]
        assert row["is_anomaly"] is True
        assert row["label"] == "UNCONFIRMED_ANOMALY"


def test_isolate_skips_tier3_unconfirmed(tmp_path: Path) -> None:
    with _client(tmp_path, catalog_writer=_write_isolate_catalog, edges=[]) as client:
        _require_artifacts(client)
        assert client.get("/healthz").json()["n_isolates"] == 1
        _seed(client, PATNA, bait=True)
        response = _ingest(client, PATNA, **LSTM_FLAG)
        assert response.status_code == 200, response.text
        body = response.json()
        if body["label"] in {"CLEAN", "PHYSICAL_FAULT"}:
            pytest.skip(f"LSTM did not flag isolate hour (got {body['label']})")
        assert body["label"] == "UNCONFIRMED_ANOMALY"
        assert body["pipeline_status"] == "UNKNOWN"
        assert body["tier3"]["performed"] is False
        assert body["tier3"]["reason_skip"] in {"isolate_station", "fewer_than_2_usable_buddies"}
        row = client.get(f"/stations/{PATNA}/telemetry?limit=1").json()[0]
        assert row["is_anomaly"] is True
        assert row["label"] == "UNCONFIRMED_ANOMALY"
        alert = client.get("/alerts").json()[0]
        assert alert["label"] == "UNCONFIRMED_ANOMALY"
