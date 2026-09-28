from panels import (
    WINDOW_HOURS,
    alert_card_html,
    alert_counts,
    alerts_intro_html,
    buddy_html,
    build_inject_body,
    channel_values,
    collected_hours,
    dispatch_lists,
    dispatch_panel_html,
    dispatch_reason,
    dispatch_row_html,
    event_preview_html,
    event_spec,
    fault_label,
    filter_alerts,
    fmt_stamp,
    hour_caption,
    hour_kind,
    identity_html,
    inject_targets,
    map_head_html,
    network_intro_html,
    roster_row_html,
    interval_pair,
    overlay_cards_html,
    poll_html,
    readings_html,
    result_cards_html,
    story_preview_html,
    story_spec,
    warmup_html,
)


def test_channel_values_read_telemetry_and_ingest() -> None:
    observed, imputed = channel_values(
        {"temp_observed": 55.0, "pres_observed": 980.0, "rhum_observed": 95.0, "temp_imputed": 25.2}
    )
    assert observed["temp_c"] == 55.0
    assert imputed["temp_c"] == 25.2
    ingest, predicted = channel_values(
        {"observed": {"temp_c": 25.7, "pres_hpa": 1013.1, "rhum_pct": None}, "imputed": {"temp_c": None}}
    )
    assert ingest["temp_c"] == 25.7
    assert ingest["rhum_pct"] is None
    assert predicted["temp_c"] is None


def test_warmup_html_is_a_progress_state() -> None:
    html = warmup_html(1, "2026-09-27 18:00 UTC")
    assert "1 / 24" in html
    assert "sg-dot-on" in html
    assert html.count("sg-dot-off") == WINDOW_HOURS - 1
    assert "no verdict" not in html.lower() or "does not score" in html
    assert collected_hours([{"timestamp": "a"}] * 30) == 24


def test_readings_hide_predicted_until_a_band_exists() -> None:
    trusted = readings_html(
        {"temp_observed": 25.7, "pres_observed": 1013.1, "rhum_observed": None, "imputed_interval": None},
        warming=True,
    )
    assert "25.7" in trusted
    assert "Predicted" not in trusted
    assert "Channel missing this hour" in trusted
    hardware = readings_html(
        {
            "temp_observed": 55.0,
            "pres_observed": 980.0,
            "rhum_observed": 95.0,
            "temp_imputed": 25.2,
            "imputed_interval": {"temp_c": [24.2, 26.3]},
        }
    )
    assert "Predicted 25.2" in hardware
    assert "24.2" in hardware
    assert interval_pair({"imputed_interval": {"temp_c": [24.2, 26.3]}}, "temp_c") == (24.2, 26.3)


def test_story_preview_and_results_show_the_affect() -> None:
    spec = story_spec("hardware")
    assert spec["kind"] == "hardware"
    preview = story_preview_html("hardware")
    assert "lone broken sensor" in preview.lower()
    assert "55 °C" in preview
    cards = result_cards_html(
        [
            {
                "station_id": "43003",
                "label": "HARDWARE_ANOMALY",
                "observed": {"temp_c": 55.0, "pres_hpa": 980.0, "rhum_pct": 95.0},
                "imputed": {"temp_c": 25.2},
                "imputed_interval": {"temp_c": [24.2, 26.3]},
                "health_score": 95.8,
                "explainability_text": "Neighbors disagree; treated as hardware anomaly.",
                "demo_injected": "SPIKE",
            },
            {
                "station_id": "43057",
                "label": "CLEAN",
                "observed": {"temp_c": 27.0, "pres_hpa": 1013.0, "rhum_pct": 70.0},
                "imputed_interval": None,
            },
        ],
        {"43003": "Santa Cruz", "43057": "Colaba"},
        "hardware",
    )
    assert "Santa Cruz" in cards
    assert "Hardware anomaly" in cards
    assert "55.0" in cards
    assert "predicted 25.2" in cards
    assert "Colaba" in cards
    assert "Clean" in cards


def test_poll_html_surfaces_a_failed_imd_hour() -> None:
    html = poll_html(
        {
            "matched": 0,
            "last_success": None,
            "last_error": "Hourly API limit exceeded",
        }
    )
    assert "Poll failed" in html
    assert "0 of 48" in html
    assert "Hourly API limit exceeded" in html
    assert "sg-poll-bad" in html
    waiting = poll_html({"matched": 0, "last_success": None, "last_error": None})
    assert "Waiting for first poll" in waiting


def test_identity_names_buddies_and_isolate() -> None:
    santa = identity_html(
        {
            "station_id": "43003",
            "name": "Bombay / Santacruz",
            "aws_name": "MUMBAI_SANTA_CRUZ",
            "aws_id": "B489804E",
            "elevation_m": 8.0,
            "latitude": 19.1167,
            "longitude": 72.85,
            "buddy_ids": ["43002", "43057"],
            "isolate": False,
        },
        "Warming up",
        {"43002": "Juhu", "43057": "Colaba"},
    )
    assert "Santacruz" in santa
    assert "Juhu" in santa
    assert "Warming up" in santa
    isolate = buddy_html({"station_id": "42182", "isolate": True, "buddy_ids": []}, {})
    assert "cannot be called" in isolate
    named = buddy_html(
        {"station_id": "43003", "isolate": False, "buddy_ids": ["43002"]},
        {"43002": "Juhu"},
        {"tier3_corr": {"43002": 0.21}, "tier3_method": "cw_idw"},
    )
    assert "Juhu" in named
    assert "0.21" in named


def test_custom_inject_body_follows_the_contract() -> None:
    spike = build_inject_body(kind="SPIKE", station_id="43003", channel="pres_hpa", duration_hours=2)
    assert spike == {
        "target": "station",
        "station_id": "43003",
        "kind": "SPIKE",
        "duration_hours": 2,
        "channel": "pres_hpa",
    }
    weather = build_inject_body(kind="GENUINE_WEATHER", station_id="43003", channel="temp_c", duration_hours=3)
    assert weather["target"] == "neighborhood"
    assert "channel" not in weather
    comms = build_inject_body(kind="COMM_ERROR", station_id="42182", channel="temp_c", duration_hours=1)
    assert comms["kind"] == "COMM_ERROR"
    assert "channel" not in comms
    santa = {"station_id": "43003", "buddy_ids": ["43002", "43057"], "isolate": False}
    assert inject_targets(santa, "SPIKE") == ["43003"]
    assert inject_targets(santa, "GENUINE_WEATHER") == ["43003", "43002", "43057"]
    isolate = {"station_id": "42182", "buddy_ids": [], "isolate": True}
    assert inject_targets(isolate, "GENUINE_WEATHER") == ["42182"]
    preview = event_preview_html(
        event_spec("SPIKE"),
        santa,
        {"43003": "Santa Cruz"},
        "temp_c",
        1,
    )
    assert "next ingested hour" in preview
    assert "Santa Cruz" in preview
    armed = overlay_cards_html(
        [{"kind": "SPIKE", "station_ids": ["43003"], "channel": "temp_c", "remaining_hours": 1}],
        {"43003": "Santa Cruz"},
    )
    assert "Santa Cruz" in armed
    assert "1h left" in armed


def test_alerts_inbox_is_readable() -> None:
    rows = [
        {
            "alert_id": 130,
            "station_id": "43003",
            "timestamp": "2024-12-31T23:00:00Z",
            "label": "HARDWARE_ANOMALY",
            "fault_type": "SPIKE",
            "confidence_score": 1.0,
            "severity": "HIGH",
            "explainability_text": "Neighbors disagree; treated as hardware anomaly.",
            "contribution_temp": 46.35,
            "contribution_pres": 49.84,
            "contribution_rhum": 3.81,
        },
        {
            "alert_id": 78,
            "station_id": "42182",
            "timestamp": "2024-07-15T15:00:00Z",
            "label": "GENUINE_WEATHER_EVENT",
            "fault_type": "GENUINE_WEATHER",
            "confidence_score": 0.1,
            "severity": "LOW",
            "explainability_text": "2 nearby stations agree.",
        },
        {
            "alert_id": 12,
            "station_id": "42182",
            "label": "UNCONFIRMED_ANOMALY",
            "fault_type": "UNKNOWN",
            "explainability_text": "Not enough neighbors.",
        },
    ]
    assert alert_counts(rows) == {"hardware": 1, "weather": 1, "unknown": 1}
    assert [row["alert_id"] for row in filter_alerts(rows, "weather")] == [78]
    assert fault_label("COMM_ERROR") == "Missing packet"
    assert fault_label("SPIKE") == "Spike"
    html = alert_card_html(rows[0], {"43003": "Santa Cruz"})
    assert "Santa Cruz" in html
    assert "Hardware anomaly" in html
    assert "Spike" in html
    assert "SPIKE" not in html
    assert "does not lower" not in html
    weather = alert_card_html(rows[1], {"42182": "Safdarjung"})
    assert "does not lower sensor health" in weather
    assert "Genuine weather" in weather
    intro = alerts_intro_html()
    assert "Clean hours never appear" in intro
    assert "Hardware" in intro


def test_dispatch_pages_health_and_watches_a_healthy_spike() -> None:
    weather = {
        "station_id": "43057",
        "name": "Bombay / Colaba",
        "health_score": 100.0,
        "status": "HEALTHY",
        "latest": {"label": "GENUINE_WEATHER_EVENT", "warming_up": False},
    }
    spike = {
        "station_id": "43003",
        "name": "Bombay / Santacruz",
        "health_score": 95.8,
        "status": "HEALTHY",
        "latest": {"label": "HARDWARE_ANOMALY", "warming_up": False},
    }
    broken = {
        "station_id": "42182",
        "name": "New Delhi / Safdarjung",
        "health_score": 62.0,
        "status": "CRITICAL",
        "latest": {"label": "PHYSICAL_FAULT", "warming_up": False},
    }
    warming = {
        "station_id": "43002",
        "name": "Bombay / Juhu",
        "health_score": 40.0,
        "status": "CRITICAL",
        "latest": {"warming_up": True, "label": None},
    }
    unconfirmed = {
        "station_id": "42807",
        "name": "Dummy",
        "health_score": 100.0,
        "status": "HEALTHY",
        "latest": {"label": "UNCONFIRMED_ANOMALY", "warming_up": False},
    }
    weather_but_hurt = {
        "station_id": "43058",
        "name": "Alibag",
        "health_score": 80.0,
        "status": "DEGRADED",
        "latest": {"label": "GENUINE_WEATHER_EVENT", "warming_up": False},
    }
    lists = dispatch_lists(
        [weather, spike, broken, warming, unconfirmed, weather_but_hurt],
        [
            {
                "alert_id": 130,
                "station_id": "43003",
                "label": "HARDWARE_ANOMALY",
                "fault_type": "SPIKE",
                "explainability_text": "Neighbors disagree; treated as hardware anomaly.",
            }
        ],
    )
    assert [row["station_id"] for row in lists["page"]] == ["42182", "43058"]
    assert [row["station_id"] for row in lists["watch"]] == ["43003"]
    assert lists["watch"][0]["alert_id"] == 130
    empty = dispatch_lists([weather, warming, unconfirmed])
    assert empty["page"] == []
    assert empty["watch"] == []
    assert "No station needs a technician" in dispatch_panel_html(empty)
    assert "never appear" in dispatch_panel_html(empty)
    assert lists["page"][0]["reason"] == "Physical fault"
    assert lists["watch"][0]["reason"] == "Neighbors disagree; treated as hardware anomaly"
    filled = dispatch_panel_html(lists)
    assert "need a technician" in filled
    assert "on watch" in filled


def test_dispatch_reason_hides_engine_tokens() -> None:
    assert (
        dispatch_reason(
            "Tier 1 physical rule failed: COMMUNICATION:temp,rhum,pres",
            "COMMUNICATION",
            "Physical fault",
        )
        == "Missing packet · temperature, humidity, pressure"
    )
    assert (
        dispatch_reason("Neighbors disagree; treated as hardware anomaly.")
        == "Neighbors disagree; treated as hardware anomaly"
    )
    assert dispatch_reason(None, "COMM_ERROR", "Physical fault") == "Missing packet"
    html = dispatch_row_html(
        {
            "station_id": "42182",
            "name": "Safdarjung",
            "health_score": 0,
            "status": "CRITICAL",
            "rank": "page",
            "reason": "Missing packet · temperature, humidity, pressure",
        }
    )
    assert "Safdarjung" in html
    assert "7-day 0" in html
    assert "COMMUNICATION" not in html
    assert "sg-chip" not in html
    assert "sg-dispatch-page" in html


def test_network_intro_and_roster_name_the_hour() -> None:
    intro = network_intro_html()
    assert "amber" in intro.lower()
    assert "Warming up" in intro
    assert "Safdarjung" in intro
    row = roster_row_html(
        {
            "station_id": "43003",
            "name": "Bombay / Santacruz",
            "health_score": 96.0,
            "latest": {"label": "HARDWARE_ANOMALY", "warming_up": False},
        },
        selected=True,
    )
    assert "Santacruz" in row
    assert "sg-roster-row-on" in row
    assert "Hardware anomaly" in row
    assert "India · this hour" in map_head_html(48, "Santacruz")


def test_hour_helpers() -> None:
    assert hour_kind({"warming_up": True, "label": None}) == "warming"
    assert hour_kind({"label": "HARDWARE_ANOMALY"}) == "hardware"
    assert hour_caption({"warming_up": True}) == "Warming up"
    assert hour_caption({"label": "GENUINE_WEATHER_EVENT"}) == "Genuine weather"
    assert "UTC" in fmt_stamp("2024-12-31T23:00:00Z")
    assert fmt_stamp(None) == "—"
