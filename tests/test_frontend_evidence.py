"""Station evidence block: decision trace, neighbor table, ribbon, TIMING chart, exports."""

from __future__ import annotations

import csv
import io

import pytest

pytest.importorskip("plotly")

from charts import alerts_timeline_figure, timing_figure
from evidence import (
    AGREE_BAND,
    decision_steps,
    decision_trace_html,
    neighbor_rows,
    neighbor_table_html,
    ribbon_hours,
    run_csv,
    technician_note,
    timing_channels_line,
    verdict_ribbon_html,
)
from map_view import india_map
from status import alert_kind
from theme import CLEAN, HARDWARE, WEATHER

THRESHOLD = 0.008487

HARDWARE_HOUR = {
    "station_id": "43003",
    "timestamp": "2024-12-31T23:00:00Z",
    "temp_observed": 55.0,
    "pres_observed": 980.0,
    "rhum_observed": 95.0,
    "temp_imputed": 25.24,
    "pres_imputed": 1013.29,
    "rhum_imputed": 69.07,
    "label": "HARDWARE_ANOMALY",
    "pipeline_status": "HARDWARE",
    "warming_up": False,
    "explainability_text": "temp observed 55.00 vs predicted 25.24. Neighbors disagree; treated as hardware anomaly.",
    "imputed_interval": {"temp_c": [24.2, 26.28], "rhum_pct": [61.94, 76.2], "pres_hpa": [1012.7, 1013.88]},
    "thermo": {"dewpoint_c": 53.9, "td_minus_t": -1.1, "passed": True},
    "tier2_score": 0.041,
    "tier3_method": "cw_idw",
    "tier3_mix": {"temp_c": 24.4, "rhum_pct": 77.0, "pres_hpa": 1012.8},
    "tier3_corr": {"43057": 0.91, "43002": 0.88, "43058": 0.72},
}

HARDWARE_ALERT = {
    "alert_id": 7,
    "station_id": "43003",
    "timestamp": "2024-12-31T23:00:00Z",
    "label": "HARDWARE_ANOMALY",
    "fault_type": "SPIKE",
    "confidence_score": 1.0,
    "severity": "HIGH",
    "explainability_text": HARDWARE_HOUR["explainability_text"],
    "contribution_temp": 60.0,
    "contribution_pres": 6.0,
    "contribution_rhum": 34.0,
}

NAMES = {"43057": "Colaba", "43002": "Juhu", "43058": "Alibag", "43003": "Santacruz"}


def _weather_hour() -> dict:
    row = dict(HARDWARE_HOUR)
    row.update(
        {
            "temp_observed": 34.0,
            "label": "GENUINE_WEATHER_EVENT",
            "pipeline_status": "GENUINE_WEATHER",
            "imputed_interval": None,
            "temp_imputed": 34.0,
            "tier3_mix": {"temp_c": 33.2, "rhum_pct": 66.0, "pres_hpa": 1013.1},
        }
    )
    return row


def test_decision_steps_hardware_reads_as_pass_flag_disagree() -> None:
    steps = decision_steps(HARDWARE_HOUR, HARDWARE_ALERT, THRESHOLD)
    assert [step["state"] for step in steps] == ["passed", "flagged", "disagree"]
    assert steps[1]["ratio"] == pytest.approx(0.041 / THRESHOLD)
    assert "4.8×" in steps[1]["detail"]
    assert "3 neighbors" in steps[2]["head"]
    assert "cw_idw" in steps[2]["head"]


def test_decision_steps_weather_and_clean_and_unconfirmed() -> None:
    weather = decision_steps(_weather_hour(), None, THRESHOLD)
    assert weather[2]["state"] == "agree"
    assert "Health unchanged" in weather[2]["detail"]

    clean = dict(HARDWARE_HOUR, label="CLEAN", tier2_score=0.002, tier3_mix=None, tier3_corr={})
    steps = decision_steps(clean, None, THRESHOLD)
    assert [step["state"] for step in steps] == ["passed", "passed", "not_run"]

    unconfirmed = dict(HARDWARE_HOUR, label="UNCONFIRMED_ANOMALY", tier3_mix=None, tier3_corr={})
    steps = decision_steps(unconfirmed, None, THRESHOLD)
    assert steps[2]["state"] == "skipped"
    assert "refused to guess" in steps[2]["detail"]


def test_decision_steps_physical_fault_names_the_rule() -> None:
    comms = dict(HARDWARE_HOUR, label="PHYSICAL_FAULT", temp_observed=None, tier3_mix=None, tier3_corr={})
    alert = dict(HARDWARE_ALERT, label="PHYSICAL_FAULT", fault_type="COMM_ERROR")
    steps = decision_steps(comms, alert, THRESHOLD)
    assert steps[0]["state"] == "failed"
    assert "Missing packet · temperature" == steps[0]["head"]
    assert steps[2]["state"] == "skipped"

    frozen = dict(HARDWARE_HOUR, label="PHYSICAL_FAULT", tier3_mix=None, tier3_corr={})
    steps = decision_steps(frozen, dict(alert, fault_type="FREEZE"), THRESHOLD)
    assert "frozen" in steps[0]["head"].lower()


def test_decision_trace_html_uses_status_colors_not_all_rose() -> None:
    html = decision_trace_html(HARDWARE_HOUR, HARDWARE_ALERT, THRESHOLD)
    assert html.count("sg-trace-step") == 3
    assert CLEAN in html and WEATHER in html and HARDWARE in html
    weather = decision_trace_html(_weather_hour(), None, THRESHOLD)
    assert HARDWARE not in weather


def test_neighbor_rows_compare_against_agree_bands() -> None:
    rows = {row["channel"]: row for row in neighbor_rows(HARDWARE_HOUR)}
    assert rows["temp_c"]["delta"] == pytest.approx(30.6)
    assert rows["temp_c"]["inside"] is False
    assert rows["temp_c"]["band"] == AGREE_BAND["temp_c"] == 3.0
    assert rows["pres_hpa"]["inside"] is False
    weather = {row["channel"]: row for row in neighbor_rows(_weather_hour())}
    assert weather["temp_c"]["inside"] is True
    assert neighbor_rows({"tier3_mix": None}) == []
    assert neighbor_rows(None) == []


def test_neighbor_table_html_names_buddies_and_flags_band() -> None:
    html = neighbor_table_html(HARDWARE_HOUR, NAMES, "HARDWARE_ANOMALY")
    assert "Colaba (r 0.91)" in html
    assert "outside band" in html
    assert "± 3.0" in html
    assert "hardware" in html.lower()
    assert neighbor_table_html({"tier3_mix": None}, NAMES, "CLEAN") == ""
    weather = neighbor_table_html(_weather_hour(), NAMES, "GENUINE_WEATHER_EVENT")
    assert "inside band" in weather
    assert "no correction is drawn" in weather


def _window(n: int = 30) -> list[dict]:
    rows = []
    for index in range(n):
        label = "CLEAN"
        if index == n - 1:
            label = "HARDWARE_ANOMALY"
        elif index == n - 5:
            label = "GENUINE_WEATHER_EVENT"
        rows.append(
            {
                "timestamp": f"2024-12-{(index // 24) + 30:02d}T{index % 24:02d}:00:00Z",
                "temp_observed": 25.0,
                "label": label,
                "warming_up": False,
            }
        )
    return rows


def test_ribbon_is_the_24_hours_ending_at_the_focus() -> None:
    window = _window()
    focus = window[-1]["timestamp"]
    rows = ribbon_hours(window, focus)
    assert len(rows) == 24
    assert rows[-1]["timestamp"] == focus
    earlier = ribbon_hours(window, window[10]["timestamp"])
    assert len(earlier) == 11
    assert ribbon_hours([], focus) == []


def test_verdict_ribbon_html_colors_and_outlines_focus() -> None:
    window = _window()
    html = verdict_ribbon_html(window, window[-1]["timestamp"])
    assert html.count("sg-ribbon-cell") == 24
    assert html.count("sg-ribbon-focus") == 1
    assert HARDWARE in html and WEATHER in html and CLEAN in html
    assert "22 clean" in html and "1 weather" in html and "1 hardware" in html
    short = verdict_ribbon_html(window[:5], window[4]["timestamp"])
    assert short.count("border:1px dashed") == 19
    assert verdict_ribbon_html([], None) == ""


TIMING = {
    "station_id": "43003",
    "timestamp": "2024-12-31T23:00:00Z",
    "status": "ready",
    "timing": {
        "start_hour_in_window": 22,
        "channel_attr": {"temp_c": 0.5012, "rhum_pct": 0.1683, "pres_hpa": 0.3305},
        "hour_attr": [0.01] * 22 + [0.28, 0.5],
        "reason": "Anomaly attribution starts at hour 22 of the 24 h window (mostly temp).",
    },
}


def test_timing_figure_highlights_the_attributed_hours() -> None:
    fig = timing_figure(TIMING)
    assert fig is not None
    bar = fig.data[0]
    colors = list(bar.marker.color)
    assert len(colors) == 24
    assert colors[21] != colors[22]
    assert colors[22] == colors[23]
    assert list(bar.x)[-1] == "this hour"
    assert list(bar.x)[0] == "−23 h"
    assert timing_figure({"status": "pending", "timing": None}) is None
    assert timing_figure(None) is None


def test_timing_channels_line_is_sorted_by_share() -> None:
    line = timing_channels_line(TIMING)
    assert line.startswith("Attribution by channel · temperature 50%")
    assert "pressure 33%" in line
    assert timing_channels_line({"status": "pending"}) == ""


def test_run_csv_keeps_raw_and_only_fills_predicted_on_corrected_hours() -> None:
    clean = dict(HARDWARE_HOUR, timestamp="2024-12-31T22:00:00Z", temp_observed=26.0, label="CLEAN", imputed_interval=None)
    text = run_csv({"station_id": "43003", "name": "Bombay / Santacruz"}, [clean, HARDWARE_HOUR])
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 2
    assert rows[0]["temp_c_observed"] == "26.0"
    assert rows[0]["temp_c_predicted"] == ""
    assert rows[1]["temp_c_observed"] == "55.0"
    assert rows[1]["temp_c_predicted"] == "25.24"
    assert rows[1]["temp_c_band_low"] == "24.2"
    assert rows[1]["station_name"] == "Santacruz"


def test_technician_note_is_plain_text_with_action() -> None:
    station = {
        "station_id": "43003",
        "name": "Bombay / Santacruz",
        "aws_name": "SANTACRUZ",
        "aws_id": "ABC123",
        "health_score": 96.0,
        "status": "HEALTHY",
    }
    note = technician_note(station, HARDWARE_HOUR, HARDWARE_ALERT, NAMES)
    assert note.startswith("SkyGuard QC note · Santacruz (43003)")
    assert "T 55.0 °C" in note
    assert "Suggested correction: T 25.2 °C" in note
    assert "outside the ±3.0 band" in note
    assert "Colaba (43057)" in note
    assert "Action: inspect" in note
    assert "<" not in note
    weather = technician_note(station, _weather_hour(), None, NAMES)
    assert "Do not dispatch" in weather


def test_alerts_timeline_stacks_by_kind_per_hour() -> None:
    rows = [
        dict(HARDWARE_ALERT, timestamp="2024-12-31T23:00:00Z"),
        dict(HARDWARE_ALERT, alert_id=8, station_id="43057", label="GENUINE_WEATHER_EVENT", fault_type="GENUINE_WEATHER", timestamp="2024-12-31T23:00:00Z"),
        dict(HARDWARE_ALERT, alert_id=9, label="UNCONFIRMED_ANOMALY", fault_type="UNKNOWN", timestamp="2024-12-31T21:00:00Z"),
    ]
    fig = alerts_timeline_figure(rows, alert_kind)
    assert fig is not None
    names = [trace.name for trace in fig.data]
    assert names == ["Hardware", "Weather", "Unconfirmed"]
    by_name = {trace.name: trace for trace in fig.data}
    assert list(by_name["Hardware"].x) == ["2024-12-31T21:00Z", "2024-12-31T23:00Z"]
    assert list(by_name["Hardware"].y) == [0, 1]
    assert list(by_name["Weather"].y) == [0, 1]
    assert list(by_name["Unconfirmed"].y) == [1, 0]
    assert by_name["Weather"].marker.color == WEATHER
    assert alerts_timeline_figure([], alert_kind) is None


def test_map_hover_shows_latest_reading_when_present() -> None:
    fig = india_map(
        [
            {
                "station_id": "43003",
                "name": "Bombay / Santacruz",
                "latitude": 19.1,
                "longitude": 72.85,
                "health_score": 96.0,
                "latest": {
                    "timestamp": "2024-12-31T23:00:00Z",
                    "label": "HARDWARE_ANOMALY",
                    "observed": {"temp_c": 55.0, "pres_hpa": 980.0, "rhum_pct": 95.0},
                },
            },
            {
                "station_id": "42182",
                "name": "New Delhi / Safdarjung",
                "latitude": 28.58,
                "longitude": 77.2,
                "health_score": 100.0,
                "latest": None,
            },
        ],
        "43003",
    )
    hovers = list(fig.data[-1].hovertext)
    assert "T 55.0 °C · P 980.0 hPa · H 95.0 %" in hovers[0]
    assert "2024-12-31 23:00 UTC" in hovers[0]
    assert "T " not in hovers[1]
    assert "7-day health 100" in hovers[1]


def test_corroborated_clean_hour_shows_flagged_lstm_and_calm_agreeing_neighbors() -> None:
    from evidence import decision_steps, is_corroborated_clean

    hour = {
        "timestamp": "2026-09-28T09:00:00Z",
        "label": "CLEAN",
        "tier2_score": 0.0121,
        "tier3_method": "cw_idw",
        "tier3_corr": {"43057": 0.8, "43002": 0.7},
        "explainability_text": (
            "temp observed 30.40, neighbor mix 30.20 (n=2). LSTM score above threshold, but neighbors agree "
            "and did not move themselves (no shared shock). Corroborated by neighbors; treated as clean."
        ),
    }
    assert is_corroborated_clean(hour)
    steps = decision_steps(hour, None, THRESHOLD)
    assert steps[1]["state"] == "flagged"
    assert steps[2]["state"] == "agree"
    assert "stayed calm" in steps[2]["head"]
    plain = {**hour, "explainability_text": "Last-hour-weighted reconstruction within the frozen 2023 threshold.", "tier2_score": 0.002}
    assert not is_corroborated_clean(plain)
    assert decision_steps(plain, None, THRESHOLD)[2]["state"] == "not_run"
