"""Station, telemetry, and alert queries."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from skyguard.api.deps import get_db
from skyguard.db.models import AnomalyAlert, Station, TelemetryLog
from skyguard.engine.pipeline import as_utc, result_from_row
from skyguard.schemas import (
    AlertRow,
    ClusterId,
    FaultType,
    Healthz,
    PipelineStatus,
    Severity,
    StationDetail,
    StationStatus,
    StationSummary,
    TelemetryRow,
)

router = APIRouter()


def _summary(station: Station) -> StationSummary:
    return StationSummary(
        station_id=station.station_id,
        name=station.name,
        latitude=station.latitude,
        longitude=station.longitude,
        elevation_m=station.elevation_m,
        cluster_id=ClusterId(station.cluster_id),
        health_score=station.health_score,
        status=StationStatus(station.status),
    )


def _require_station(session: Session, station_id: str) -> Station:
    station = session.get(Station, station_id)
    if station is None:
        raise HTTPException(status_code=404, detail=f"Unknown station_id: {station_id}")
    return station


@router.get("/healthz", response_model=Healthz)
def healthz() -> Healthz:
    return Healthz(ok=True)


@router.get("/stations", response_model=list[StationSummary])
def list_stations(session: Session = Depends(get_db)) -> list[StationSummary]:
    rows = session.scalars(select(Station).order_by(Station.station_id)).all()
    return [_summary(row) for row in rows]


@router.get("/stations/{station_id}", response_model=StationDetail)
def get_station(station_id: str, session: Session = Depends(get_db)) -> StationDetail:
    station = _require_station(session, station_id)
    latest_row = session.scalar(
        select(TelemetryLog)
        .where(TelemetryLog.station_id == station_id)
        .order_by(TelemetryLog.timestamp.desc())
    )
    base = _summary(station)
    return StationDetail(
        **base.model_dump(),
        latest=result_from_row(station, latest_row) if latest_row else None,
    )


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
