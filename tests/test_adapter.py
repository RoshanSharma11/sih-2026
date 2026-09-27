from datetime import datetime, timezone
from pathlib import Path

import pytest

from skyguard.db.models import Station, StationBuddy
from skyguard.db.session import create_tables, make_engine, make_session_factory
from skyguard.engine.adapter import (
    LABEL_TO_PIPELINE,
    ML_TO_PUBLIC,
    PUBLIC_TO_ML,
    build_ml_payload,
    map_ml_result,
    point_to_ml,
    severity_for,
)
from skyguard.engine.windows import WindowPoint, WindowStore
from skyguard.schemas import FaultType, Label, PipelineStatus, Severity


def test_public_and_ml_channel_names_round_trip() -> None:
    assert PUBLIC_TO_ML == {"temp_c": "temp", "rhum_pct": "rhum", "pres_hpa": "pres"}
    assert ML_TO_PUBLIC["temp"] == "temp_c"
    assert ML_TO_PUBLIC["rhum"] == "rhum_pct"
    assert ML_TO_PUBLIC["pres"] == "pres_hpa"


def test_buddy_payload_skips_neighbors_with_no_hours(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "buddies.db")
    create_tables(engine)
    session = make_session_factory(engine)()
    for station_id, name in (("43003", "Santa Cruz"), ("43057", "Colaba"), ("43002", "Juhu")):
        session.add(
            Station(station_id=station_id, name=name, latitude=19.1, longitude=72.8, isolate=False)
        )
    session.flush()
    session.add(StationBuddy(station_id="43003", buddy_id="43057", distance_km=24.3))
    session.add(StationBuddy(station_id="43003", buddy_id="43002", distance_km=1.8))
    session.commit()

    windows = WindowStore()
    ts = datetime(2024, 12, 31, 23, tzinfo=timezone.utc)
    windows.append("43003", WindowPoint(ts, 26.0, 1013.0, 65.0))
    windows.append("43057", WindowPoint(ts, 25.0, 1013.0, 66.0))
    payload = build_ml_payload(session, "43003", ts, 26.0, 1013.0, 65.0, windows)
    session.close()

    assert {row["station_id"] for row in payload["buddies"]} == {"43057"}
    assert payload["buddies"][0]["window"][0]["temp"] == 25.0


def test_point_to_ml_uses_engine_field_names() -> None:
    point = WindowPoint(
        timestamp=datetime(2024, 7, 1, 14, tzinfo=timezone.utc),
        temp_c=34.2,
        pres_hpa=1002.4,
        rhum_pct=71.0,
    )
    row = point_to_ml(point)
    assert set(row) == {"timestamp", "temp", "rhum", "pres"}
    assert row["temp"] == 34.2
    assert row["pres"] == 1002.4
    assert row["rhum"] == 71.0


def test_d18_label_map() -> None:
    assert LABEL_TO_PIPELINE[Label.CLEAN] is PipelineStatus.CLEAN
    assert LABEL_TO_PIPELINE[Label.PHYSICAL_FAULT] is PipelineStatus.HARDWARE
    assert LABEL_TO_PIPELINE[Label.HARDWARE_ANOMALY] is PipelineStatus.HARDWARE
    assert LABEL_TO_PIPELINE[Label.GENUINE_WEATHER_EVENT] is PipelineStatus.GENUINE_WEATHER
    assert LABEL_TO_PIPELINE[Label.UNCONFIRMED_ANOMALY] is PipelineStatus.UNKNOWN


def _minimal_ml(label: str, **overrides) -> dict:
    body = {
        "label": label,
        "is_anomaly": False,
        "confidence": 0.4,
        "fault_type": None,
        "reason": "test",
        "predicted": {"temp": 28.4, "rhum": 70.0, "pres": 1004.0},
        "affected_variables": ["temp"],
        "tier1": {"passed": True, "violations": []},
        "tier2": {
            "ran": True,
            "window_mse": 0.02,
            "threshold": 0.00605,
            "feature_contributions": {"temp": 0.9, "rhum": 0.05, "pres": 0.05},
        },
        "tier3": {
            "performed": False,
            "buddy_ids": [],
            "usable_count": 0,
            "neighbors_agree": None,
            "reason_skip": "not_required",
        },
        "health": {"index_7d": 1.0, "state": "HEALTHY"},
    }
    body.update(overrides)
    return body


@pytest.mark.parametrize(
    ("label", "pipeline", "is_anomaly"),
    [
        (Label.CLEAN.value, PipelineStatus.CLEAN, False),
        (Label.PHYSICAL_FAULT.value, PipelineStatus.HARDWARE, True),
        (Label.HARDWARE_ANOMALY.value, PipelineStatus.HARDWARE, True),
        (Label.GENUINE_WEATHER_EVENT.value, PipelineStatus.GENUINE_WEATHER, True),
        (Label.UNCONFIRMED_ANOMALY.value, PipelineStatus.UNKNOWN, True),
    ],
)
def test_d18_map_follows_label_not_ml_is_anomaly_flag(
    label: str, pipeline: PipelineStatus, is_anomaly: bool
) -> None:
    mapped = map_ml_result(_minimal_ml(label, is_anomaly=not is_anomaly))
    assert mapped["label"].value == label
    assert mapped["pipeline_status"] is pipeline
    assert mapped["is_anomaly"] is is_anomaly


def test_map_ml_result_maps_communication_and_health() -> None:
    mapped = map_ml_result(
        {
            "label": "PHYSICAL_FAULT",
            "is_anomaly": True,
            "confidence": 1.0,
            "fault_type": "COMMUNICATION",
            "reason": "Tier 1 physical rule failed: COMMUNICATION:temp",
            "predicted": {"temp": None, "rhum": 67.0, "pres": 1004.0},
            "affected_variables": ["temp"],
            "tier1": {"passed": False, "violations": ["COMMUNICATION:temp"]},
            "tier2": {
                "ran": False,
                "window_mse": None,
                "threshold": 0.00605,
                "feature_contributions": {"temp": 1.0, "rhum": 0.0, "pres": 0.0},
            },
            "tier3": {
                "performed": False,
                "buddy_ids": [],
                "usable_count": 0,
                "neighbors_agree": None,
                "reason_skip": "tier1_failed",
            },
            "health": {"index_7d": 0.88, "state": "HEALTHY"},
        }
    )
    assert mapped["label"] is Label.PHYSICAL_FAULT
    assert mapped["pipeline_status"] is PipelineStatus.HARDWARE
    assert mapped["fault_type"] is FaultType.COMM_ERROR
    assert mapped["is_anomaly"] is True
    assert mapped["health_score"] == 88.0
    assert mapped["affected_variables"] == ["temp_c"]
    assert mapped["contribution_pct"].temp_c == 100.0
    assert mapped["tier2"].feature_contributions["temp_c"] == 1.0
    assert mapped["severity"] is Severity.HIGH


def test_weather_label_does_not_use_hardware_fault_type() -> None:
    mapped = map_ml_result(
        {
            "label": "GENUINE_WEATHER_EVENT",
            "is_anomaly": True,
            "confidence": 0.4,
            "fault_type": None,
            "reason": "Neighbors agree",
            "predicted": {"temp": 28.4, "rhum": 80.0, "pres": 995.0},
            "affected_variables": ["temp"],
            "tier1": {"passed": True, "violations": []},
            "tier2": {
                "ran": True,
                "window_mse": 0.02,
                "threshold": 0.00605,
                "feature_contributions": {"temp": 0.9, "rhum": 0.05, "pres": 0.05},
            },
            "tier3": {
                "performed": True,
                "buddy_ids": ["42182", "42369"],
                "usable_count": 2,
                "neighbors_agree": True,
                "reason_skip": None,
            },
            "health": {"index_7d": 1.0, "state": "HEALTHY"},
        }
    )
    assert mapped["fault_type"] is FaultType.GENUINE_WEATHER
    assert mapped["severity"] is Severity.LOW
    assert mapped["is_anomaly"] is True
    assert mapped["health_score"] == 100.0
    assert severity_for(Label.GENUINE_WEATHER_EVENT, 0.9) is Severity.LOW


def test_map_hardware_and_unconfirmed() -> None:
    hardware = map_ml_result(
        _minimal_ml(
            "HARDWARE_ANOMALY",
            confidence=0.8,
            fault_type="SPIKE",
            health={"index_7d": 0.7, "state": "DEGRADED"},
            tier3={
                "performed": True,
                "buddy_ids": ["42182", "42139"],
                "usable_count": 2,
                "neighbors_agree": False,
                "reason_skip": None,
            },
        )
    )
    assert hardware["label"] is Label.HARDWARE_ANOMALY
    assert hardware["pipeline_status"] is PipelineStatus.HARDWARE
    assert hardware["fault_type"] is FaultType.SPIKE
    assert hardware["severity"] is Severity.HIGH
    assert hardware["health_score"] == 70.0

    unconfirmed = map_ml_result(
        _minimal_ml(
            "UNCONFIRMED_ANOMALY",
            confidence=0.2,
            fault_type=None,
            tier3={
                "performed": False,
                "buddy_ids": [],
                "usable_count": 0,
                "neighbors_agree": None,
                "reason_skip": "isolate_station",
            },
        )
    )
    assert unconfirmed["label"] is Label.UNCONFIRMED_ANOMALY
    assert unconfirmed["pipeline_status"] is PipelineStatus.UNKNOWN
    assert unconfirmed["fault_type"] is FaultType.UNKNOWN
    assert unconfirmed["severity"] is Severity.LOW
    assert unconfirmed["tier3"].reason_skip == "isolate_station"


def test_map_v2_overlay_fields() -> None:
    mapped = map_ml_result(
        _minimal_ml(
            "HARDWARE_ANOMALY",
            confidence=0.8,
            fault_type="SPIKE",
            imputed_interval={
                "temp": [24.2, 26.3],
                "rhum": [61.9, 76.2],
                "pres": [1012.7, 1013.9],
            },
            thermo={"dewpoint_c": 18.9, "td_minus_t": -7.1, "passed": True},
            tier2={
                "ran": True,
                "score": 0.1646,
                "window_mse": 0.0327,
                "threshold": 0.008487,
                "feature_contributions": {"temp": 0.46, "rhum": 0.04, "pres": 0.50},
            },
            tier3={
                "performed": True,
                "method": "cw_idw",
                "buddy_ids": ["43057"],
                "usable_count": 3,
                "neighbors_agree": False,
                "reason_skip": None,
                "mix": {"temp": 24.4, "rhum": 77.0, "pres": 1012.8},
                "corr": {"43057": 0.2445},
            },
        )
    )
    assert mapped["explainability_text"] == "test"
    assert mapped["imputed_interval"].temp_c == [24.2, 26.3]
    assert mapped["imputed_interval"].rhum_pct == [61.9, 76.2]
    assert mapped["imputed_interval"].pres_hpa == [1012.7, 1013.9]
    assert mapped["thermo"].dewpoint_c == 18.9
    assert mapped["thermo"].td_minus_t == -7.1
    assert mapped["thermo"].passed is True
    assert mapped["tier2"].score == 0.1646
    assert mapped["tier3"].method == "cw_idw"
    assert mapped["tier3"].mix.temp_c == 24.4
    assert mapped["tier3"].corr == {"43057": 0.2445}
