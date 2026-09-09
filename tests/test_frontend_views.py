import pytest

pytest.importorskip("plotly")

from charts import telemetry_figures
from map_view import india_map
from status import PIPELINE_COLOR
from theme import HARDWARE, WEATHER


def test_india_map_uses_weather_amber_not_red() -> None:
    fig = india_map(
        [
            {
                "station_id": "42181",
                "name": "New Delhi / Palam",
                "latitude": 28.57,
                "longitude": 77.12,
                "health_score": 90.0,
                "latest": {"label": "GENUINE_WEATHER_EVENT", "pipeline_status": "GENUINE_WEATHER"},
            },
            {
                "station_id": "42182",
                "name": "New Delhi / Safdarjung",
                "latitude": 28.58,
                "longitude": 77.2,
                "health_score": 90.0,
                "latest": {"label": "HARDWARE_ANOMALY", "pipeline_status": "HARDWARE"},
            },
        ],
        "42181",
    )
    marker_trace = fig.data[-1]
    colors = list(marker_trace.marker.color)
    assert colors[0] == WEATHER
    assert colors[1] == HARDWARE
    assert colors[0] != colors[1]
    assert colors[0] == PIPELINE_COLOR["GENUINE_WEATHER"]


def test_india_map_draws_buddy_edges_only_in_view() -> None:
    fig = india_map(
        [
            {
                "station_id": "42181",
                "name": "Palam",
                "latitude": 28.57,
                "longitude": 77.12,
                "latest": {"label": "CLEAN"},
            },
            {
                "station_id": "42182",
                "name": "Safdarjung",
                "latitude": 28.58,
                "longitude": 77.2,
                "latest": {"label": "CLEAN"},
            },
        ],
        "42181",
        buddies={"42181": ["42182", "42139"], "42182": ["42181"]},
    )
    assert fig.data[0].mode == "lines"
    assert None in list(fig.data[0].lat)


def test_telemetry_keeps_observed_when_anomaly() -> None:
    figs = telemetry_figures(
        [
            {
                "timestamp": "2024-07-01T14:00:00Z",
                "temp_observed": 48.1,
                "temp_imputed": 32.0,
                "pres_observed": 1008.0,
                "pres_imputed": 1008.0,
                "rhum_observed": 78.0,
                "rhum_imputed": 78.0,
                "is_anomaly": True,
            }
        ]
    )
    assert len(figs) == 3
    assert figs[0].data[0].y[0] == 48.1
    assert figs[0].data[1].y[0] == 32.0
    assert figs[0].layout.paper_bgcolor in {"#FFFFFF", "white", "#ffffff"}


def test_contribution_html_uses_alert_shares() -> None:
    from charts import contribution_html

    html = contribution_html(
        {"contribution_temp": 94.1, "contribution_pres": 3.2, "contribution_rhum": 2.7}
    )
    assert "94.1%" in html
    assert "Temperature" in html
    assert contribution_html(None) == ""
