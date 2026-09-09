import httpx

from api import SkyGuardApiError, SkyGuardClient


def _app(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/healthz":
        return httpx.Response(200, json={"ok": True})
    if path == "/stations":
        return httpx.Response(
            200,
            json=[
                {
                    "station_id": "42181",
                    "name": "New Delhi / Palam",
                    "latitude": 28.57,
                    "longitude": 77.12,
                    "elevation_m": 220.0,
                    "cluster_id": "NORTH",
                    "health_score": 100.0,
                    "status": "HEALTHY",
                }
            ],
        )
    if path == "/stations/42181":
        return httpx.Response(
            200,
            json={
                "station_id": "42181",
                "name": "New Delhi / Palam",
                "latitude": 28.57,
                "longitude": 77.12,
                "elevation_m": 220.0,
                "cluster_id": "NORTH",
                "health_score": 100.0,
                "status": "HEALTHY",
                "latest": {
                    "station_id": "42181",
                    "timestamp": "2024-07-01T14:00:00Z",
                    "pipeline_status": "CLEAN",
                    "observed": {"temp_c": 34.2, "pres_hpa": 1002.4, "rhum_pct": 71.0},
                    "imputed": {"temp_c": None, "pres_hpa": None, "rhum_pct": None},
                    "health_score": 100.0,
                    "station_status": "HEALTHY",
                    "demo_injected": None,
                },
            },
        )
    if path == "/stations/42181/telemetry":
        return httpx.Response(
            200,
            json=[
                {
                    "station_id": "42181",
                    "timestamp": "2024-07-01T14:00:00Z",
                    "temp_observed": 34.2,
                    "pres_observed": 1002.4,
                    "rhum_observed": 71.0,
                    "temp_imputed": None,
                    "pres_imputed": None,
                    "rhum_imputed": None,
                    "is_anomaly": False,
                    "pipeline_status": "CLEAN",
                    "mse": 0.0,
                }
            ],
        )
    if path == "/alerts":
        return httpx.Response(200, json=[])
    if path == "/demo/status":
        return httpx.Response(200, json={"overlays": []})
    if path == "/demo/inject":
        return httpx.Response(400, json={"detail": "GENUINE_WEATHER inject must target a neighborhood"})
    if path == "/demo/reset":
        return httpx.Response(200, json={"overlays": []})
    return httpx.Response(404, json={"detail": "missing"})


def _client() -> SkyGuardClient:
    return SkyGuardClient(base_url="http://test", transport=httpx.MockTransport(_app))


def test_snapshot_merges_latest_pipeline_status() -> None:
    snap = _client().snapshot("42181")
    assert snap.ok is True
    assert snap.stations[0]["pipeline_status"] == "CLEAN"
    assert snap.telemetry[0]["temp_observed"] == 34.2
    assert snap.overlays == []


def test_inject_error_surfaces_detail() -> None:
    try:
        _client().inject({"target": "station", "station_id": "42181", "kind": "GENUINE_WEATHER"})
    except SkyGuardApiError as exc:
        assert "neighborhood" in str(exc)
        assert exc.status_code == 400
    else:
        raise AssertionError("expected SkyGuardApiError")


def test_healthz_false_when_down() -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    client = SkyGuardClient(base_url="http://test", transport=httpx.MockTransport(down))
    assert client.healthz() is False
    snap = client.snapshot("42181")
    assert snap.ok is False
    assert "not reachable" in (snap.error or "")
