"""Station, telemetry, and alert queries."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from skyguard.api.deps import get_db
from skyguard.db.models import AnomalyAlert, Station, StationBuddy, TelemetryLog
from skyguard.engine.pipeline import as_utc, latest_snapshot_from_row
from skyguard.schemas import (
    AlertRow,
    BuddyMap,
    ClusterId,
    FaultType,
    Healthz,
    Label,
    PipelineStatus,
    Severity,
    StationDetail,
    StationStatus,
    StationSummary,
    TelemetryRow,
)

router = APIRouter()


def _parse_ids(raw: str | None) -> list[str] | None:
    if raw is None or not raw.strip():
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def _cluster(value: str | None) -> ClusterId | None:
    if not value:
        return None
    try:
        return ClusterId(value)
    except ValueError:
        return None


def _label(value: str | None) -> Label | None:
    if not value:
        return None
    try:
        return Label(value)
    except ValueError:
        return None


def _buddy_ids_by_station(session: Session, station_ids: list[str]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {station_id: [] for station_id in station_ids}
    if not station_ids:
        return mapping
    rows = session.execute(
        select(StationBuddy.station_id, StationBuddy.buddy_id)
        .where(StationBuddy.station_id.in_(station_ids))
        .order_by(StationBuddy.buddy_id)
    ).all()
    for station_id, buddy_id in rows:
        mapping.setdefault(station_id, []).append(buddy_id)
    return mapping


def _latest_by_station(session: Session, station_ids: list[str]) -> dict[str, TelemetryLog]:
    if not station_ids:
        return {}
    latest_ts = (
        select(
            TelemetryLog.station_id.label("station_id"),
            func.max(TelemetryLog.timestamp).label("ts"),
        )
        .where(TelemetryLog.station_id.in_(station_ids))
        .group_by(TelemetryLog.station_id)
        .subquery()
    )
    rows = session.scalars(
        select(TelemetryLog).join(
            latest_ts,
            (TelemetryLog.station_id == latest_ts.c.station_id)
            & (TelemetryLog.timestamp == latest_ts.c.ts),
        )
    ).all()
    return {row.station_id: row for row in rows}


def _summary(
    station: Station,
    buddy_ids: list[str] | None = None,
    latest: TelemetryLog | None = None,
) -> StationSummary:
    return StationSummary(
        station_id=station.station_id,
        name=station.name,
        latitude=station.latitude,
        longitude=station.longitude,
        elevation_m=station.elevation_m,
        buddy_ids=list(buddy_ids or []),
        isolate=bool(station.isolate),
        cluster_id=_cluster(station.cluster_id),
        health_score=station.health_score,
        status=StationStatus(station.status),
        latest=latest_snapshot_from_row(latest) if latest is not None else None,
    )


def _require_station(session: Session, station_id: str) -> Station:
    station = session.get(Station, station_id)
    if station is None:
        raise HTTPException(status_code=404, detail=f"Unknown station_id: {station_id}")
    return station


@router.get("/healthz", response_model=Healthz)
def healthz(request: Request, session: Session = Depends(get_db)) -> Healthz:
    engine = getattr(request.app.state, "qc_engine", None)
    lstm = getattr(engine, "lstm", None) if engine is not None else None
    n_stations = session.scalar(select(func.count()).select_from(Station)) or 0
    n_isolates = session.scalar(
        select(func.count()).select_from(Station).where(Station.isolate.is_(True))
    ) or 0
    return Healthz(
        ok=True,
        model_loaded=bool(lstm is not None and lstm.loaded),
        threshold=getattr(lstm, "threshold", None),
        n_stations=int(n_stations),
        n_isolates=int(n_isolates),
    )


@router.get("/stations", response_model=list[StationSummary])
def list_stations(
    session: Session = Depends(get_db),
    ids: str | None = Query(default=None),
) -> list[StationSummary]:
    requested = _parse_ids(ids)
    stmt = select(Station)
    if requested is not None:
        stmt = stmt.where(Station.station_id.in_(requested))
    rows = session.scalars(stmt.order_by(Station.station_id)).all()
    if requested is not None:
        by_id = {row.station_id: row for row in rows}
        rows = [by_id[station_id] for station_id in requested if station_id in by_id]
    station_ids = [row.station_id for row in rows]
    buddies = _buddy_ids_by_station(session, station_ids)
    latest = _latest_by_station(session, station_ids)
    return [
        _summary(row, buddy_ids=buddies.get(row.station_id, []), latest=latest.get(row.station_id))
        for row in rows
    ]


@router.get("/stations/{station_id}", response_model=StationDetail)
def get_station(station_id: str, session: Session = Depends(get_db)) -> StationDetail:
    station = _require_station(session, station_id)
    buddies = _buddy_ids_by_station(session, [station_id])
    latest = _latest_by_station(session, [station_id])
    return StationDetail.model_validate(
        _summary(
            station,
            buddy_ids=buddies.get(station_id, []),
            latest=latest.get(station_id),
        ).model_dump()
    )


@router.get("/buddy-map", response_model=BuddyMap)
def buddy_map(session: Session = Depends(get_db)) -> BuddyMap:
    stations = list(session.scalars(select(Station).order_by(Station.station_id)).all())
    ids = [row.station_id for row in stations]
    buddies = _buddy_ids_by_station(session, ids)
    isolates = [row.station_id for row in stations if row.isolate]
    return BuddyMap(stations=ids, isolates=isolates, buddies=buddies)


@router.get("/stations/{station_id}/telemetry", response_model=list[TelemetryRow])
def list_telemetry(
    station_id: str,
    session: Session = Depends(get_db),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[TelemetryRow]:
    _require_station(session, station_id)
    stmt = select(TelemetryLog).where(TelemetryLog.station_id == station_id)
    if from_ is not None:
        stmt = stmt.where(TelemetryLog.timestamp >= as_utc(from_))
    if to is not None:
        stmt = stmt.where(TelemetryLog.timestamp <= as_utc(to))
    rows = session.scalars(stmt.order_by(TelemetryLog.timestamp.desc()).limit(limit)).all()
    rows = list(reversed(rows))
    return [
        TelemetryRow(
            station_id=row.station_id,
            timestamp=as_utc(row.timestamp),
            temp_observed=row.temp_observed,
            pres_observed=row.pres_observed,
            rhum_observed=row.rhum_observed,
            temp_imputed=row.temp_imputed,
            pres_imputed=row.pres_imputed,
            rhum_imputed=row.rhum_imputed,
            is_anomaly=row.is_anomaly,
            label=_label(row.label),
            pipeline_status=PipelineStatus(row.pipeline_status),
            mse=row.mse,
        )
        for row in rows
    ]


@router.get("/alerts", response_model=list[AlertRow])
def list_alerts(
    session: Session = Depends(get_db),
    station_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[AlertRow]:
    stmt = select(AnomalyAlert)
    if station_id is not None:
        _require_station(session, station_id)
        stmt = stmt.where(AnomalyAlert.station_id == station_id)
    rows = session.scalars(stmt.order_by(AnomalyAlert.timestamp.desc()).limit(limit)).all()
    return [
        AlertRow(
            alert_id=row.alert_id,
            station_id=row.station_id,
            timestamp=as_utc(row.timestamp),
            label=_label(row.label),
            fault_type=FaultType(row.fault_type),
            confidence_score=row.confidence_score,
            severity=Severity(row.severity),
            explainability_text=row.explainability_text,
            contribution_temp=row.contribution_temp,
            contribution_pres=row.contribution_pres,
            contribution_rhum=row.contribution_rhum,
        )
        for row in rows
    ]
