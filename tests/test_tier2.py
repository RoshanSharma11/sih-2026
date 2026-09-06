import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from skyguard.api.main import create_app
from skyguard.engine.tier2 import evaluate, window_matrix
from skyguard.engine.windows import WindowPoint
from skyguard.ml.identity import IdentityDetector
from skyguard.ml.protocol import Reconstruction


class HighTempDetector:
    def reconstruct(self, window: np.ndarray) -> Reconstruction:
        observed = np.asarray(window[-1], dtype=float)
        reconstructed = observed.copy()
        reconstructed[0] = observed[0] - 10.0
        err = (observed - reconstructed) ** 2
        total = float(err.sum())
        return Reconstruction(
            reconstructed=reconstructed,
            mse=float(err.mean()),
            mse_vector=err,
            contribution_pct=(err / total) * 100.0,
            skipped=False,
        )


def _write_catalog(path) -> None:
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-06T12:00:00Z",
                "notes": "tier2",
                "stations": [
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


def _seed(client: TestClient, station_id: str, hours: int = 23) -> None:
    start = datetime(2024, 6, 30, 1, tzinfo=timezone.utc)
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
    assert response.json()["accepted"] == hours


def _ingest(client: TestClient, station_id: str, ts: datetime, temp_c: float | None = 32.4, pres_hpa: float | None = 1005.0, rhum_pct: float | None = 60.8):
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


def _point(temp_c: float | None, hour: int = 0) -> WindowPoint:
    ts = datetime(2024, 7, 1, tzinfo=timezone.utc) + timedelta(hours=hour)
    return WindowPoint(ts, temp_c, 1005.0 if temp_c is not None else None, 60.0 if temp_c is not None else None)


def test_window_matrix_skips_short_or_null() -> None:
    short = [_point(32.0, i) for i in range(8)]
    assert window_matrix(short) is None
    full = [_point(32.0, i) for i in range(24)]
    matrix = window_matrix(full)
    assert matrix is not None
    assert matrix.shape == (24, 3)
    full[-1] = _point(None, 23)
    assert window_matrix(full) is None
    extra = [_point(30.0, -1), *[_point(32.0, i) for i in range(24)]]
    clipped = window_matrix(extra)
    assert clipped is not None
    assert clipped[0, 0] == 32.0


def test_identity_evaluate_never_exceeds_inf() -> None:
    points = [_point(32.0, i) for i in range(24)]
    result = evaluate(points, IdentityDetector())
    assert result.skipped is False
    assert result.over_threshold is False
    assert result.reconstruction.mse == 0.0


def test_short_window_keeps_imputed_null(tmp_path) -> None:
    hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with _client(tmp_path) as client:
        body = _ingest(client, "42181", hour).json()
        assert body["imputed"]["temp_c"] is None
        assert body["mse"] is None
        assert body["pipeline_status"] == "CLEAN"


def test_identity_fills_imputed_without_firing(tmp_path) -> None:
    hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with _client(tmp_path) as client:
        _seed(client, "42181")
        body = _ingest(client, "42181", hour).json()
        assert body["observed"]["temp_c"] == 32.4
        assert body["imputed"]["temp_c"] == 32.4
        assert body["imputed"]["pres_hpa"] == 1005.0
        assert body["mse"] == 0.0
        assert body["pipeline_status"] == "CLEAN"


def test_null_skips_reconstruction(tmp_path) -> None:
    hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with _client(tmp_path) as client:
        _seed(client, "42181")
        body = _ingest(client, "42181", hour, temp_c=None).json()
        assert body["fault_type"] == "COMM_ERROR"
        assert body["imputed"]["temp_c"] is None
        assert body["mse"] is None


def test_recon_over_threshold_is_hardware(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKYGUARD_RECON_THRESHOLD", "0.01")
    hour = datetime(2024, 7, 1, tzinfo=timezone.utc)
    with _client(tmp_path) as client:
        client.app.state.detector = HighTempDetector()
        _seed(client, "42181")
        _seed(client, "42182")
        neighbor = _ingest(client, "42182", hour)
        assert neighbor.status_code == 200
        palam = _ingest(client, "42181", hour)
        body = palam.json()
        assert body["pipeline_status"] == "HARDWARE"
        assert body["fault_type"] == "SPIKE"
        assert body["observed"]["temp_c"] == 32.4
        assert body["imputed"]["temp_c"] == pytest.approx(22.4)
        assert body["mse"] == pytest.approx(100.0 / 3.0)
        assert body["contribution_pct"]["temp_c"] == pytest.approx(100.0)
        assert body["mse_vector"]["temp_c"] == pytest.approx(100.0)
        row = client.get("/stations/42181/telemetry?limit=1").json()[0]
        assert row["temp_observed"] == 32.4
        assert row["temp_imputed"] == pytest.approx(22.4)
        assert row["is_anomaly"] is True
