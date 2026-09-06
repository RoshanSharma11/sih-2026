from api import merge_station
from status import pipeline_color, pipeline_label, short_name


def test_short_name_strips_city_prefix() -> None:
    assert short_name("New Delhi / Palam") == "Palam"
    assert short_name("Safdarjung") == "Safdarjung"


def test_pipeline_weather_is_not_red() -> None:
    assert pipeline_color("GENUINE_WEATHER") == "#f5b942"
    assert pipeline_color("HARDWARE") == "#f43f5e"
    assert pipeline_color("CLEAN") == "#2dd4bf"
    assert pipeline_color(None) == "#3d4f6f"
    assert pipeline_label(None) == "Waiting for stream"


def test_merge_station_reads_latest_pipeline_status() -> None:
    summary = {
        "station_id": "42181",
        "name": "New Delhi / Palam",
        "cluster_id": "NORTH",
        "health_score": 88.0,
        "status": "HEALTHY",
    }
    detail = {"latest": {"pipeline_status": "HARDWARE", "fault_type": "SPIKE"}}
    merged = merge_station(summary, detail)
    assert merged["pipeline_status"] == "HARDWARE"
    assert merged["health_score"] == 88.0
    assert merge_station(summary, {"latest": None})["pipeline_status"] is None
