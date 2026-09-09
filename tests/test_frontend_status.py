from api import merge_station
from status import (
    kpi_counts,
    marker_color,
    pipeline_color,
    pipeline_label,
    short_name,
)
from theme import CLEAN, HARDWARE, SLATE, WEATHER


def test_short_name_strips_city_prefix() -> None:
    assert short_name("New Delhi / Palam") == "Palam"
    assert short_name("Safdarjung") == "Safdarjung"


def test_pipeline_weather_is_not_red() -> None:
    assert pipeline_color("GENUINE_WEATHER") == WEATHER
    assert pipeline_color("GENUINE_WEATHER_EVENT") == WEATHER
    assert pipeline_color("HARDWARE") == HARDWARE
    assert pipeline_color("HARDWARE_ANOMALY") == HARDWARE
    assert pipeline_color("CLEAN") == CLEAN
    assert pipeline_color(None) == SLATE
    assert pipeline_label(None) == "Waiting for stream"
    assert pipeline_color("GENUINE_WEATHER") != pipeline_color("HARDWARE")


def test_marker_color_prefers_label() -> None:
    weather = {
        "station_id": "42181",
        "latest": {"label": "GENUINE_WEATHER_EVENT", "pipeline_status": "GENUINE_WEATHER"},
    }
    hardware = {
        "station_id": "42182",
        "latest": {"label": "HARDWARE_ANOMALY", "pipeline_status": "HARDWARE"},
    }
    idle = {"station_id": "43003", "latest": None}
    assert marker_color(weather) == WEATHER
    assert marker_color(hardware) == HARDWARE
    assert marker_color(idle) == SLATE


def test_kpi_counts_split_weather_and_idle() -> None:
    counts = kpi_counts(
        [
            {"latest": {"label": "CLEAN"}},
            {"latest": {"label": "GENUINE_WEATHER_EVENT"}},
            {"latest": {"label": "HARDWARE_ANOMALY"}},
            {"latest": {"label": "UNCONFIRMED_ANOMALY"}},
            {"latest": None},
        ]
    )
    assert counts == {"clean": 1, "weather": 1, "hardware": 1, "unconfirmed": 1, "idle": 1}


def test_merge_station_reads_latest_pipeline_status() -> None:
    summary = {
        "station_id": "42181",
        "name": "New Delhi / Palam",
        "cluster_id": "NORTH",
        "health_score": 88.0,
        "status": "HEALTHY",
    }
    detail = {"latest": {"pipeline_status": "HARDWARE", "fault_type": "SPIKE", "label": "HARDWARE_ANOMALY"}}
    merged = merge_station(summary, detail)
    assert merged["pipeline_status"] == "HARDWARE"
    assert merged["label"] == "HARDWARE_ANOMALY"
    assert merged["health_score"] == 88.0
    assert merge_station(summary, {"latest": None})["pipeline_status"] is None
