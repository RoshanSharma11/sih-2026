"""GET /reliability — per-station completeness and flag history over a window.

Health answers "is this sensor trustworthy". Reliability answers "is this station
actually reporting, and how often did QC have to step in". Both come from stored
`telemetry_logs` rows; nothing is recomputed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from skyguard.api.deps import get_db
from skyguard.db.models import Station, StationBuddy, TelemetryLog
from skyguard.engine.pipeline import as_utc
from skyguard.schemas import (
    Label,
    ReliabilityNetwork,
    ReliabilityReport,
    ReliabilityRow,
    StationStatus,
)

router = APIRouter()

_COMPLETE_MIN = 0.90
_HARDWARE = {Label.PHYSICAL_FAULT.value, Label.HARDWARE_ANOMALY.value}


def reliability_row(
    station: Station,
    *,
    hours: int,
    buddy_count: int,
    counts: dict[tuple[str | None, bool, bool], int],
    last_hour: datetime | None,
) -> ReliabilityRow:
    """Fold (label, warming_up, feed_gap) → count into one station row."""
    row = ReliabilityRow(
        station_id=station.station_id,
        name=station.name,
        isolate=bool(station.isolate),
        buddy_count=buddy_count,
        hours_expected=hours,
        health_score=float(station.health_score),
        status=StationStatus(station.status),
        last_hour=last_hour,
    )
    for (label, warming, gap), count in counts.items():
        row.hours_stored += count
        if gap:
            row.feed_gap += count
            continue
        if warming or not label:
            row.warming += count
            continue
        row.hours_scored += count
        if label == Label.CLEAN.value:
            row.clean += count
        elif label == Label.GENUINE_WEATHER_EVENT.value:
            row.weather += count
        elif label in _HARDWARE:
            row.hardware += count
        elif label == Label.UNCONFIRMED_ANOMALY.value:
            row.unconfirmed += count
    row.completeness = round(min(1.0, row.hours_stored / hours), 4) if hours else 0.0
    if row.hours_scored:
        row.flag_rate = round((row.hardware + row.unconfirmed) / row.hours_scored, 4)
    return row


@router.get("/reliability", response_model=ReliabilityReport)
def reliability(
    session: Session = Depends(get_db),
    hours: int = Query(default=168, ge=1, le=24 * 90),
    to: datetime | None = None,
) -> ReliabilityReport:
    as_of = as_utc(to) if to is not None else datetime.now(timezone.utc)
    cutoff = as_of - timedelta(hours=hours)

    stations = session.scalars(select(Station).order_by(Station.station_id)).all()
    buddy_counts = dict(
        session.execute(
            select(StationBuddy.station_id, func.count()).group_by(StationBuddy.station_id)
        ).all()
    )
    grouped = session.execute(
        select(
            TelemetryLog.station_id,
            TelemetryLog.label,
            TelemetryLog.warming_up,
            TelemetryLog.feed_gap.is_not(None),
            func.count(),
            func.max(TelemetryLog.timestamp),
        )
        .where(TelemetryLog.timestamp > cutoff, TelemetryLog.timestamp <= as_of)
        .group_by(
            TelemetryLog.station_id,
            TelemetryLog.label,
            TelemetryLog.warming_up,
            TelemetryLog.feed_gap.is_not(None),
        )
    ).all()

    counts: dict[str, dict[tuple[str | None, bool, bool], int]] = {}
    last_hours: dict[str, datetime] = {}
    for station_id, label, warming, gap, count, latest in grouped:
        counts.setdefault(station_id, {})[(label, bool(warming), bool(gap))] = int(count)
        if latest is not None:
            latest_utc = as_utc(latest)
            if station_id not in last_hours or latest_utc > last_hours[station_id]:
                last_hours[station_id] = latest_utc

    rows = [
        reliability_row(
            station,
            hours=hours,
            buddy_count=int(buddy_counts.get(station.station_id, 0)),
            counts=counts.get(station.station_id, {}),
            last_hour=last_hours.get(station.station_id),
        )
        for station in stations
    ]
    rows.sort(key=lambda row: (row.completeness, -(row.flag_rate or 0.0), row.station_id))

    network = ReliabilityNetwork(
        n_stations=len(rows),
        n_isolates=sum(1 for row in rows if row.isolate),
        hours_expected=hours,
        hours_stored=sum(row.hours_stored for row in rows),
        hours_scored=sum(row.hours_scored for row in rows),
        feed_gap_hours=sum(row.feed_gap for row in rows),
        mean_completeness=round(sum(row.completeness for row in rows) / len(rows), 4) if rows else 0.0,
        stations_complete=sum(1 for row in rows if row.completeness >= _COMPLETE_MIN),
        stations_degraded=sum(1 for row in rows if row.status != StationStatus.HEALTHY),
    )
    return ReliabilityReport(generated_at=as_of, hours=hours, network=network, stations=rows)
