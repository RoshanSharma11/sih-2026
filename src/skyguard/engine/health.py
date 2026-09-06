"""7-day sensor health score. Genuine weather does not lower health."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from skyguard.db.models import AnomalyAlert, Station, TelemetryLog
from skyguard.schemas import FaultType, StationStatus

HEALTH_HOURS = 7 * 24
DRIFT_TERM_CAP = 20.0


def status_for(score: float) -> StationStatus:
    if score > 80:
        return StationStatus.HEALTHY
    if score >= 50:
        return StationStatus.DEGRADED
    return StationStatus.CRITICAL


def recompute(session: Session, station: Station, now: datetime) -> float:
    start = now - timedelta(hours=HEALTH_HOURS)
    alerts = session.scalars(
        select(AnomalyAlert).where(
            AnomalyAlert.station_id == station.station_id,
            AnomalyAlert.timestamp >= start,
            AnomalyAlert.timestamp <= now,
        )
    ).all()
    rows = session.scalars(
        select(TelemetryLog).where(
            TelemetryLog.station_id == station.station_id,
            TelemetryLog.timestamp >= start,
            TelemetryLog.timestamp <= now,
        )
    ).all()

    f_spike = sum(1 for alert in alerts if alert.fault_type == FaultType.SPIKE.value)
    f_freeze = sum(1 for alert in alerts if alert.fault_type == FaultType.FREEZE.value)
    d_drift = min(
        sum(1 for alert in alerts if alert.fault_type == FaultType.DRIFT.value),
        DRIFT_TERM_CAP,
    )
    expected = max(len(rows), 1)
    missing = sum(
        1
        for row in rows
        if row.temp_observed is None or row.pres_observed is None or row.rhum_observed is None
    )
    m_missing = missing / expected
    score = 100.0 - (2 * f_spike + 3 * f_freeze + 5 * d_drift + 10 * m_missing)
    score = max(0.0, min(100.0, score))
    station.health_score = score
    station.status = status_for(score).value
    return score
