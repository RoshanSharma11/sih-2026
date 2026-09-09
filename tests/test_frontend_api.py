import httpx

from api import SkyGuardApiError, SkyGuardClient, merge_station


def _app(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/healthz":
        return httpx.Response(
            200,
            json={
                "ok": True,
                "model_loaded": True,
                "threshold": 0.00605,
                "n_stations": 151,
                "n_isolates": 24,
            },
        )
    if path == "/stations":
        ids = request.url.params.get("ids")
        rows = [
            {
                "station_id": "42181",
                "name": "New Delhi / Palam",
                "latitude": 28.57,
                "longitude": 77.12,
                "elevation_m": 220.0,
                "health_score": 100.0,
                "status": "HEALTHY",
                "buddy_ids": ["42182"],
                "isolate": False,
                "latest": {
                    "timestamp": "2024-07-01T14:00:00Z",
                    "label": "CLEAN",
                    "pipeline_status": "CLEAN",
                    "observed": {"temp_c": 34.2, "pres_hpa": 1002.4, "rhum_pct": 71.0},
                    "imputed": {"temp_c": None, "pres_hpa": None, "rhum_pct": None},
                },
            },
            {
                "station_id": "43003",
                "name": "Mumbai / Santacruz",
                "latitude": 19.09,
                "longitude": 72.85,
                "elevation_m": 14.0,
                "health_score": 100.0,
                "status": "HEALTHY",
                "buddy_ids": ["43057"],
                "isolate": False,
                "latest": None,
            },
        ]
        if ids:
            wanted = set(ids.split(","))
            rows = [row for row in rows if row["station_id"] in wanted]
        return httpx.Response(200, json=rows)
    if path == "/stations/42181":
        return httpx.Response(
            200,
            json={
                "station_id": "42181",
                "name": "New Delhi / Palam",
                "latitude": 28.57,
                "longitude": 77.12,
                "elevation_m": 220.0,
                "health_score": 100.0,
                "status": "HEALTHY",
                "latest": {
                    "station_id": "42181",
                    "timestamp": "2024-07-01T14:00:00Z",
                    "pipeline_status": "CLEAN",
                    "label": "CLEAN",
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
    if path == "/demo/stream-filter":
        return httpx.Response(
            200,
            json={"view": ["42181"], "ingest": ["42181", "42182"], "include_buddies": True},
        )
    if path == "/buddy-map":
        return httpx.Response(
            200,
            json={
                "stations": ["42181", "42182"],
                "isolates": [],
                "buddies": {"42181": ["42182"], "42182": ["42181"]},
            },
        )
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
    assert snap.stations[0]["label"] == "CLEAN"
    assert snap.telemetry[0]["temp_observed"] == 34.2
    assert snap.overlays == []
    assert snap.health["model_loaded"] is True
    assert snap.ingest == ["42181", "42182"]


def test_stations_ids_query_filters_view_set() -> None:
    rows = _client().stations(ids=["43003"])
    assert [row["station_id"] for row in rows] == ["43003"]


def test_buddy_map_and_stream_filter() -> None:
    client = _client()
    graph = client.buddy_map()
    assert graph["buddies"]["42181"] == ["42182"]
    filt = client.set_stream_filter(["42181"], include_buddies=True)
    assert "42182" in filt["ingest"]


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
    assert client.health() is None
    snap = client.snapshot("42181")
    assert snap.ok is False
    assert "not reachable" in (snap.error or "")


def test_merge_station_reads_latest_label() -> None:
    summary = {
        "station_id": "42181",
        "name": "New Delhi / Palam",
        "health_score": 88.0,
        "status": "HEALTHY",
        "latest": {"label": "HARDWARE_ANOMALY", "pipeline_status": "HARDWARE"},
    }
    merged = merge_station(summary)
    assert merged["label"] == "HARDWARE_ANOMALY"
    assert merged["pipeline_status"] == "HARDWARE"
    assert merge_station({"latest": None})["label"] is None
