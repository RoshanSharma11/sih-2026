import pytest

pytest.importorskip("plotly")

from charts import cluster_around, telemetry_figures
from map_view import MAP_HEIGHT, india_map, map_camera, offscreen_stations
from status import PIPELINE_COLOR
from theme import HARDWARE, WEATHER


def _palam(**extra):
    row = {
        "station_id": "42181",
        "name": "New Delhi / Palam",
        "latitude": 28.5667,
        "longitude": 77.1167,
        "health_score": 90.0,
        "latest": {"label": "CLEAN"},
    }
    row.update(extra)
    return row


def _safdarjung(**extra):
    row = {
        "station_id": "42182",
        "name": "New Delhi / Safdarjung",
        "latitude": 28.58,
        "longitude": 77.2,
        "health_score": 90.0,
        "latest": {"label": "CLEAN"},
    }
    row.update(extra)
    return row


def _santacruz(**extra):
    row = {
        "station_id": "43003",
        "name": "Bombay / Santacruz",
        "latitude": 19.1167,
        "longitude": 72.85,
        "health_score": 90.0,
        "latest": {"label": "CLEAN"},
    }
    row.update(extra)
    return row


def test_india_map_uses_weather_amber_not_red() -> None:
    fig = india_map(
        [
            _palam(latest={"label": "GENUINE_WEATHER_EVENT", "pipeline_status": "GENUINE_WEATHER"}),
            _safdarjung(latest={"label": "HARDWARE_ANOMALY", "pipeline_status": "HARDWARE"}),
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
        [_palam(), _safdarjung()],
        "42181",
        buddies={"42181": ["42182", "42139"], "42182": ["42181"]},
    )
    assert fig.data[0].mode == "lines"
    assert None in list(fig.data[0].lat)


def test_india_map_uses_readable_basemap_and_labels_only_selected() -> None:
    fig = india_map([_palam(), _safdarjung(), _santacruz()], "42181")
    assert fig.data[-1].type == "scattermap"
    assert fig.layout.map.style == "carto-positron"
    assert fig.layout.height == MAP_HEIGHT
    assert fig.layout.height >= 600
    texts = list(fig.data[-1].text)
    assert texts[0] == "Palam"
    assert texts[1] == ""
    assert texts[2] == ""


def test_default_camera_frames_mumbai_and_safdarjung() -> None:
    from chrome import DEMO_FOCUS

    stations = [_palam(), _safdarjung(), _santacruz()]
    camera = map_camera(stations, "43003", focus_ids=DEMO_FOCUS)
    assert 19 < camera["lat"] < 28
    assert camera["zoom"] < 6.5
    fig = india_map(stations, "42182", focus_ids=DEMO_FOCUS)
    hover = " ".join(fig.data[-1].hovertext)
    assert "Weather versus hardware cannot be called here." in hover


def test_chart_keeps_the_replay_run_apart_from_a_later_live_hour() -> None:
    story = [
        {
            "timestamp": f"2024-12-31T{hour:02d}:00:00Z",
            "temp_observed": 55.0 if hour == 23 else 26.0,
            "temp_imputed": 25.2 if hour == 23 else 26.0,
            "imputed_interval": {"temp_c": [24.2, 26.3]} if hour == 23 else None,
        }
        for hour in range(24)
    ]
    live = {"timestamp": "2026-09-27T18:00:00Z", "temp_observed": 25.7, "imputed_interval": None}
    window = cluster_around(story + [live], "2024-12-31T23:00:00Z")
    assert len(window) == 24
    assert window[-1]["temp_observed"] == 55.0
    assert live not in window
    figs = telemetry_figures(window, mark_at="2024-12-31T23:00:00Z", mark_label="Replay hour")
    assert figs[0].data[0].y[-1] == 55.0
    assert "Predicted" in [trace.name for trace in figs[0].data]


def test_warming_is_its_own_idle_state() -> None:
    from status import WARMING_COLOR, marker_color, status_label

    warming = _santacruz(latest={"warming_up": True, "label": None, "pipeline_status": None})
    assert marker_color(warming) == WARMING_COLOR
    assert status_label(warming) == "Warming up"
    assert status_label(warming) != "Waiting for stream"


def test_map_camera_zooms_to_selected_cluster_not_all_india() -> None:
    stations = [_palam(), _safdarjung(), _santacruz()]
    camera = map_camera(stations, "42181")
    assert camera["zoom"] >= 6.0
    assert camera["lat"] > 26
    far = offscreen_stations(stations, "42181")
    assert [row["station_id"] for row in far] == ["43003"]


def test_telemetry_keeps_observed_and_hides_the_band_until_distrusted() -> None:
    trusted = telemetry_figures(
        [
            {
                "timestamp": "2024-07-01T14:00:00Z",
                "temp_observed": 26.0,
                "temp_imputed": 26.0,
                "pres_observed": 1013.0,
                "pres_imputed": 1013.0,
                "rhum_observed": 65.0,
                "rhum_imputed": 65.0,
                "imputed_interval": None,
            }
        ]
    )
    assert len(trusted[0].data) == 1
    assert trusted[0].data[0].y[0] == 26.0

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
                "imputed_interval": {
                    "temp_c": [30.0, 34.0],
                    "pres_hpa": [1006.0, 1010.0],
                    "rhum_pct": [70.0, 86.0],
                },
                "is_anomaly": True,
            }
        ]
    )
    assert len(figs) == 3
    assert figs[0].data[0].y[0] == 48.1
    names = [trace.name for trace in figs[0].data]
    assert "Predicted" in names
    assert "90% band" in names
    predicted = next(trace for trace in figs[0].data if trace.name == "Predicted")
    assert predicted.y[0] == 32.0
    assert figs[0].layout.paper_bgcolor in {"#FFFFFF", "white", "#ffffff"}
    marked = telemetry_figures(
        [
            {
                "timestamp": "2024-07-01T14:00:00Z",
                "temp_observed": 48.1,
                "temp_imputed": 32.0,
                "pres_observed": 1008.0,
                "pres_imputed": 1008.0,
                "rhum_observed": 78.0,
                "rhum_imputed": 78.0,
            }
        ],
        mark_at="2024-07-01T14:00:00Z",
    )
    assert marked[0].layout.shapes


def test_contribution_html_uses_alert_shares() -> None:
    from charts import contribution_html

    html = contribution_html(
        {"contribution_temp": 94.1, "contribution_pres": 3.2, "contribution_rhum": 2.7}
    )
    assert "94.1%" in html
    assert "Temperature" in html
    assert contribution_html(None) == ""
