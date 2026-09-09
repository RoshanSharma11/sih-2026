from skyguard.api.main import create_app

CONTRACT_PATHS = {
    "/healthz": {"get"},
    "/stations": {"get"},
    "/stations/{station_id}": {"get"},
    "/stations/{station_id}/seed": {"post"},
    "/stations/{station_id}/telemetry": {"get"},
    "/alerts": {"get"},
    "/ingest": {"post"},
    "/demo/inject": {"post"},
    "/demo/reset": {"post"},
    "/demo/status": {"get"},
    "/demo/stream-filter": {"get", "post"},
}

CONTRACT_PROPERTIES = {
    "IngestPayload": {
        "station_id",
        "timestamp",
        "temp_c",
        "pres_hpa",
        "rhum_pct",
        "sequence_id",
    },
    "IngestResult": {
        "station_id",
        "timestamp",
        "label",
        "pipeline_status",
        "fault_type",
        "confidence",
        "severity",
        "explainability_text",
        "affected_variables",
        "contribution_pct",
        "observed",
        "imputed",
        "mse",
        "mse_vector",
        "health_score",
        "station_status",
        "demo_injected",
        "tier1",
        "tier2",
        "tier3",
    },
    "StationSummary": {
        "station_id",
        "name",
        "latitude",
        "longitude",
        "elevation_m",
        "cluster_id",
        "health_score",
        "status",
    },
    "StationDetail": {
        "station_id",
        "name",
        "latitude",
        "longitude",
        "elevation_m",
        "cluster_id",
        "health_score",
        "status",
        "latest",
    },
    "TelemetryRow": {
        "station_id",
        "timestamp",
        "temp_observed",
        "pres_observed",
        "rhum_observed",
        "temp_imputed",
        "pres_imputed",
        "rhum_imputed",
        "is_anomaly",
        "pipeline_status",
        "mse",
    },
    "AlertRow": {
        "alert_id",
        "station_id",
        "timestamp",
        "fault_type",
        "confidence_score",
        "severity",
        "explainability_text",
        "contribution_temp",
        "contribution_pres",
        "contribution_rhum",
    },
    "DemoInjectRequest": {
        "target",
        "station_id",
        "cluster_id",
        "kind",
        "channel",
        "duration_hours",
    },
    "DemoStatus": {"overlays"},
    "DemoOverlayStatus": {"kind", "station_ids", "channel", "remaining_hours", "hour_index"},
    "StreamFilterRequest": {"station_ids", "include_buddies"},
    "StreamFilterStatus": {"view", "ingest", "include_buddies"},
    "Healthz": {"ok", "model_loaded", "threshold", "n_stations", "n_isolates"},
    "SeedResult": {"station_id", "accepted", "skipped"},
    "ChannelValues": {"temp_c", "pres_hpa", "rhum_pct"},
    "Tier1View": {"passed", "violations"},
    "Tier2View": {"ran", "window_mse", "threshold", "feature_contributions"},
    "Tier3View": {"performed", "buddy_ids", "usable_count", "neighbors_agree", "reason_skip"},
}


def test_openapi_matches_contracts() -> None:
    spec = create_app().openapi()
    verbs = {"get", "post", "put", "patch", "delete"}
    actual = {path: set(item) & verbs for path, item in spec["paths"].items()}
    assert actual == CONTRACT_PATHS

    telemetry = spec["paths"]["/stations/{station_id}/telemetry"]["get"]["parameters"]
    assert {item["name"] for item in telemetry} >= {"from", "to", "limit"}
    alerts = spec["paths"]["/alerts"]["get"]["parameters"]
    assert {item["name"] for item in alerts} >= {"station_id", "limit"}

    schemas = spec["components"]["schemas"]
    for name, expected in CONTRACT_PROPERTIES.items():
        assert name in schemas, name
        assert set(schemas[name]["properties"]) == expected, name
