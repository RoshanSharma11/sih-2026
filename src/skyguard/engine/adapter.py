"""SkyGuard public fields ↔ ml.engine.process_aws_data (D12 / D16 / D18)."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from skyguard.config import REPO_ROOT
from skyguard.db.models import StationBuddy
from skyguard.engine.windows import WindowPoint, WindowStore
from skyguard.schemas import (
    Channel,
    ChannelValues,
    FaultType,
    Label,
    PipelineStatus,
    Severity,
    StationStatus,
    Tier1View,
    Tier2View,
    Tier3View,
)

PUBLIC_TO_ML = {
    Channel.TEMP_C.value: "temp",
    Channel.RHUM_PCT.value: "rhum",
    Channel.PRES_HPA.value: "pres",
}
ML_TO_PUBLIC = {ml: public for public, ml in PUBLIC_TO_ML.items()}

LABEL_TO_PIPELINE = {
    Label.CLEAN: PipelineStatus.CLEAN,
    Label.PHYSICAL_FAULT: PipelineStatus.HARDWARE,
    Label.HARDWARE_ANOMALY: PipelineStatus.HARDWARE,
    Label.GENUINE_WEATHER_EVENT: PipelineStatus.GENUINE_WEATHER,
    Label.UNCONFIRMED_ANOMALY: PipelineStatus.UNKNOWN,
}

ML_FAULT_TO_PUBLIC = {
    "SPIKE": FaultType.SPIKE,
    "FREEZE": FaultType.FREEZE,
    "DRIFT": FaultType.DRIFT,
    "COMMUNICATION": FaultType.COMM_ERROR,
    "COMM_ERROR": FaultType.COMM_ERROR,
    "GENUINE_WEATHER": FaultType.GENUINE_WEATHER,
    "GENUINE_WEATHER_EVENT": FaultType.GENUINE_WEATHER,
}

UNCONFIRMED_FALLBACK = {
    "label": Label.UNCONFIRMED_ANOMALY.value,
    "is_anomaly": True,
    "confidence": 0.0,
    "fault_type": None,
    "reason": "INSUFFICIENT_WINDOW: model artifacts not loaded",
    "predicted": {"temp": None, "rhum": None, "pres": None},
    "affected_variables": [],
    "tier1": {"passed": True, "violations": []},
    "tier2": {
        "ran": False,
        "window_mse": None,
        "threshold": None,
        "feature_contributions": {"temp": None, "rhum": None, "pres": None},
    },
    "tier3": {
        "performed": False,
        "buddy_ids": [],
        "usable_count": 0,
        "neighbors_agree": None,
        "reason_skip": "lstm_not_run",
    },
    "health": {"index_7d": 1.0, "state": StationStatus.HEALTHY.value, "window_hours": 0},
}


def ensure_ml_on_path() -> Path:
    """Inner package is `ml/ml/`; imports are `ml.engine` with this parent on sys.path."""
    ml_root = REPO_ROOT / "ml"
    path = str(ml_root)
    if path not in sys.path:
        sys.path.insert(0, path)
    return ml_root


def load_qc_engine():
    """Construct a per-app DetectionEngine. Never use the module-level singleton."""
    try:
        ensure_ml_on_path()
        from ml.engine import DetectionEngine

        return DetectionEngine()
    except Exception:
        return None


def unknown_station_error_type():
    ensure_ml_on_path()
    try:
        from ml.engine import UnknownStationError

        return UnknownStationError
    except Exception:
        return None


def qc_has_scaler(engine, station_id: str) -> bool | None:
    """True/False when artifacts are loaded; None if the engine cannot check."""
    if engine is None:
        return None
    lstm = getattr(engine, "lstm", None)
    if lstm is None or not getattr(lstm, "loaded", False):
        return None
    return bool(lstm.has_scaler(station_id))


def point_to_ml(point: WindowPoint) -> dict[str, Any]:
    return {
        "timestamp": point.timestamp,
        "temp": point.temp_c,
        "rhum": point.rhum_pct,
        "pres": point.pres_hpa,
    }


def build_ml_payload(
    session: Session,
    station_id: str,
    timestamp: datetime,
    temp_c: float | None,
    pres_hpa: float | None,
    rhum_pct: float | None,
    windows: WindowStore,
) -> dict[str, Any]:
    window = [point_to_ml(point) for point in windows.points(station_id)]
    if not window or window[-1]["timestamp"] != timestamp:
        window.append(
            point_to_ml(WindowPoint(timestamp, temp_c, pres_hpa, rhum_pct))
        )
    else:
        window[-1] = point_to_ml(WindowPoint(timestamp, temp_c, pres_hpa, rhum_pct))
    return {
        "station_id": station_id,
        "timestamp": timestamp,
        "temp": temp_c,
        "rhum": rhum_pct,
        "pres": pres_hpa,
        "window": window,
        "buddies": _buddy_payloads(session, station_id, windows),
    }


def map_ml_result(ml_out: dict[str, Any]) -> dict[str, Any]:
    raw_label = ml_out.get("label") or Label.UNCONFIRMED_ANOMALY.value
    try:
        label = Label(raw_label)
    except ValueError:
        label = Label.UNCONFIRMED_ANOMALY
    pipeline_status = LABEL_TO_PIPELINE[label]
    is_anomaly = label is not Label.CLEAN
    predicted = ml_out.get("predicted") or {}
    contrib = (ml_out.get("tier2") or {}).get("feature_contributions") or {}
    return {
        "label": label,
        "pipeline_status": pipeline_status,
        "is_anomaly": is_anomaly,
        "fault_type": _fault_type(ml_out.get("fault_type"), label),
        "confidence": ml_out.get("confidence"),
        "severity": severity_for(label, ml_out.get("confidence")),
        "explainability_text": ml_out.get("reason"),
        "affected_variables": [_public_name(name) for name in ml_out.get("affected_variables") or []],
        "imputed": ChannelValues(
            temp_c=_float_or_none(predicted.get("temp")),
            pres_hpa=_float_or_none(predicted.get("pres")),
            rhum_pct=_float_or_none(predicted.get("rhum")),
        ),
        "contribution_pct": ChannelValues(
            temp_c=_share_pct(contrib.get("temp")),
            pres_hpa=_share_pct(contrib.get("pres")),
            rhum_pct=_share_pct(contrib.get("rhum")),
        ),
        "mse": _float_or_none((ml_out.get("tier2") or {}).get("window_mse")),
        "tier1": _tier1(ml_out.get("tier1") or {}),
        "tier2": _tier2(ml_out.get("tier2") or {}),
        "tier3": _tier3(ml_out.get("tier3") or {}),
        "health_score": _health_score(ml_out.get("health") or {}),
        "station_status": _station_status(ml_out.get("health") or {}),
    }


def severity_for(label: Label, confidence: float | None) -> Severity | None:
    if label is Label.CLEAN:
        return None
    score = 0.0 if confidence is None else float(confidence)
    if label in {Label.PHYSICAL_FAULT, Label.HARDWARE_ANOMALY}:
        return Severity.HIGH if score >= 0.7 else Severity.MEDIUM
    if label is Label.GENUINE_WEATHER_EVENT:
        return Severity.LOW
    return Severity.MEDIUM if score >= 0.5 else Severity.LOW


def _buddy_payloads(session: Session, station_id: str, windows: WindowStore) -> list[dict[str, Any]]:
    rows = session.scalars(select(StationBuddy).where(StationBuddy.station_id == station_id)).all()
    return [
        {
            "station_id": row.buddy_id,
            "distance_km": float(row.distance_km),
            "window": [point_to_ml(point) for point in windows.points(row.buddy_id)],
        }
        for row in rows
    ]


def _fault_type(raw: str | None, label: Label) -> FaultType | None:
    if label is Label.CLEAN:
        return None
    if label is Label.GENUINE_WEATHER_EVENT:
        return FaultType.GENUINE_WEATHER
    if not raw:
        return FaultType.UNKNOWN
    return ML_FAULT_TO_PUBLIC.get(raw, FaultType.UNKNOWN)


def _public_name(name: str) -> str:
    return ML_TO_PUBLIC.get(name, name)


def _tier1(raw: dict[str, Any]) -> Tier1View:
    return Tier1View(passed=bool(raw.get("passed", False)), violations=list(raw.get("violations") or []))


def _tier2(raw: dict[str, Any]) -> Tier2View:
    contrib = raw.get("feature_contributions") or {}
    return Tier2View(
        ran=bool(raw.get("ran", False)),
        window_mse=_float_or_none(raw.get("window_mse")),
        threshold=_float_or_none(raw.get("threshold")),
        feature_contributions={
            _public_name(key): _float_or_none(value) for key, value in contrib.items()
        },
    )


def _tier3(raw: dict[str, Any]) -> Tier3View:
    return Tier3View(
        performed=bool(raw.get("performed", False)),
        buddy_ids=[str(item) for item in raw.get("buddy_ids") or []],
        usable_count=int(raw.get("usable_count") or 0),
        neighbors_agree=raw.get("neighbors_agree"),
        reason_skip=raw.get("reason_skip"),
    )


def _health_score(health: dict[str, Any]) -> float:
    index = health.get("index_7d")
    if index is None:
        return 100.0
    return round(float(index) * 100.0, 2)


def _station_status(health: dict[str, Any]) -> StationStatus:
    raw = health.get("state")
    try:
        return StationStatus(raw) if raw else StationStatus.HEALTHY
    except ValueError:
        return StationStatus.HEALTHY


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _share_pct(value: Any) -> float | None:
    number = _float_or_none(value)
    if number is None:
        return None
    return round(number * 100.0, 2)
