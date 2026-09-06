"""Ingest orchestrator. Slice 1b persists only; tiers land in later slices."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from skyguard.db.models import Station, TelemetryLog
from skyguard.errors import CatalogNotLoaded, DuplicateObservation, StationNotFound
from skyguard.schemas import (
    ChannelValues,
    IngestPayload,
    IngestResult,
    PipelineStatus,
    StationStatus,
)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def ingest_observation(session: Session, payload: IngestPayload, catalog_ready: bool) -> IngestResult:
    if not catalog_ready:
        raise CatalogNotLoaded("Station catalog not loaded")

    station = session.get(Station, payload.station_id)
    if station is None:
        raise StationNotFound(payload.station_id)

    timestamp = as_utc(payload.timestamp)
    already = session.scalar(
        select(TelemetryLog.id).where(
            TelemetryLog.station_id == payload.station_id,
            TelemetryLog.timestamp == timestamp,
        )
    )
    if already is not None:
        raise DuplicateObservation(f"{payload.station_id} {timestamp.isoformat()}")

    row = TelemetryLog(
        station_id=payload.station_id,
        timestamp=timestamp,
        temp_observed=payload.temp_c,
        pres_observed=payload.pres_hpa,
        rhum_observed=payload.rhum_pct,
        is_anomaly=False,
        pipeline_status=PipelineStatus.CLEAN.value,
    )
    session.add(row)
    session.flush()
    return result_from_row(station, row)


def result_from_row(station: Station, row: TelemetryLog) -> IngestResult:
    return IngestResult(
        station_id=station.station_id,
        timestamp=as_utc(row.timestamp),
        pipeline_status=PipelineStatus(row.pipeline_status),
        observed=ChannelValues(
            temp_c=row.temp_observed,
            pres_hpa=row.pres_observed,
            rhum_pct=row.rhum_observed,
        ),
        imputed=ChannelValues(
            temp_c=row.temp_imputed,
            pres_hpa=row.pres_imputed,
            rhum_pct=row.rhum_imputed,
        ),
        contribution_pct=ChannelValues(),
        mse=row.mse,
        mse_vector=ChannelValues(),
        health_score=station.health_score,
        station_status=StationStatus(station.status),
    )
