import pytest

pytest.importorskip("plotly")

from charts import telemetry_figures
from map_view import india_map
from status import PIPELINE_COLOR


def test_india_map_uses_weather_amber_not_red() -> None:
    fig = india_map(
        [
            {
                "station_id": "42181",
                "name": "New Delhi / Palam",
                "latitude": 28.57,
                "longitude": 77.12,
                "cluster_id": "NORTH",
                "health_score": 90.0,
                "pipeline_status": "GENUINE_WEATHER",
            },
            {
                "station_id": "42182",
                "name": "New Delhi / Safdarjung",
                "latitude": 28.58,
                "longitude": 77.2,
                "cluster_id": "NORTH",
                "health_score": 90.0,
                "pipeline_status": "HARDWARE",
            },
        ],
        "42181",
    )
    colors = list(fig.data[0].marker.color)
    assert colors[0] == PIPELINE_COLOR["GENUINE_WEATHER"]
    assert colors[1] == PIPELINE_COLOR["HARDWARE"]
    assert colors[0] != colors[1]


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
