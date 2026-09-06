"""Ingest orchestrator: persist raw, run Tier 1, record alerts."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from skyguard.db.models import AnomalyAlert, Station, TelemetryLog
from skyguard.engine.tier1 import CHANNEL_LABEL, Tier1Result, evaluate
from skyguard.engine.windows import WindowPoint, WindowStore
from skyguard.errors import CatalogNotLoaded, DuplicateObservation, StationNotFound
from skyguard.schemas import (
    ChannelValues,
    FaultType,
    IngestPayload,
    IngestResult,
    PipelineStatus,
    SeedObservation,
    Severity,
    StationStatus,
)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def ingest_observation(
    session: Session,
    payload: IngestPayload,
    catalog_ready: bool,
    windows: WindowStore,
) -> IngestResult:
    if not catalog_ready:
        raise CatalogNotLoaded("Station catalog not loaded")

    station = session.get(Station, payload.station_id)
    if station is None:
        raise StationNotFound(payload.station_id)

    timestamp = as_utc(payload.timestamp)
    _reject_duplicate(session, payload.station_id, timestamp)

    current = WindowPoint(timestamp, payload.temp_c, payload.pres_hpa, payload.rhum_pct)
    tier1 = evaluate(current, windows.last(payload.station_id))
    status, fault, confidence, severity, text = _classify_tier1(tier1)

    row = TelemetryLog(
        station_id=payload.station_id,
        timestamp=timestamp,
        temp_observed=payload.temp_c,
        pres_observed=payload.pres_hpa,
        rhum_observed=payload.rhum_pct,
        is_anomaly=status is PipelineStatus.HARDWARE,
        pipeline_status=status.value,
    )
    session.add(row)
    session.flush()

    if status is not PipelineStatus.CLEAN:
        session.add(
            AnomalyAlert(
                station_id=payload.station_id,
                timestamp=timestamp,
                fault_type=fault.value if fault else FaultType.UNKNOWN.value,
                confidence_score=confidence or 0.5,
                severity=(severity or Severity.LOW).value,
                explainability_text=text or "Tier 1 flagged this observation.",
            )
        )

    windows.append(payload.station_id, current)
    return result_from_row(
        station,
        row,
        fault_type=fault,
        confidence=confidence,
        severity=severity,
        explainability_text=text,
    )


def seed_station(
    session: Session,
    station_id: str,
    observations: list[SeedObservation],
    catalog_ready: bool,
    windows: WindowStore,
) -> tuple[int, int]:
    if not catalog_ready:
        raise CatalogNotLoaded("Station catalog not loaded")
    station = session.get(Station, station_id)
    if station is None:
        raise StationNotFound(station_id)

    accepted = 0
    skipped = 0
    ordered = sorted(observations, key=lambda item: as_utc(item.timestamp))
    for item in ordered:
        timestamp = as_utc(item.timestamp)
        exists = session.scalar(
            select(TelemetryLog.id).where(
                TelemetryLog.station_id == station_id,
                TelemetryLog.timestamp == timestamp,
            )
        )
        if exists is not None:
            skipped += 1
            continue
        session.add(
            TelemetryLog(
                station_id=station_id,
                timestamp=timestamp,
                temp_observed=item.temp_c,
                pres_observed=item.pres_hpa,
                rhum_observed=item.rhum_pct,
                is_anomaly=False,
                pipeline_status=PipelineStatus.CLEAN.value,
            )
        )
        windows.append(
            station_id,
            WindowPoint(timestamp, item.temp_c, item.pres_hpa, item.rhum_pct),
        )
        accepted += 1
    session.flush()
    return accepted, skipped


def result_from_row(
    station: Station,
    row: TelemetryLog,
    fault_type: FaultType | None = None,
    confidence: float | None = None,
    severity: Severity | None = None,
    explainability_text: str | None = None,
) -> IngestResult:
    return IngestResult(
        station_id=station.station_id,
        timestamp=as_utc(row.timestamp),
        pipeline_status=PipelineStatus(row.pipeline_status),
        fault_type=fault_type,
        confidence=confidence,
        severity=severity,
        explainability_text=explainability_text,
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


def _reject_duplicate(session: Session, station_id: str, timestamp: datetime) -> None:
    already = session.scalar(
        select(TelemetryLog.id).where(
            TelemetryLog.station_id == station_id,
            TelemetryLog.timestamp == timestamp,
        )
    )
    if already is not None:
        raise DuplicateObservation(f"{station_id} {timestamp.isoformat()}")


def _classify_tier1(
    tier1: Tier1Result,
) -> tuple[PipelineStatus, FaultType | None, float | None, Severity | None, str | None]:
    if tier1.comm_error:
        return (
            PipelineStatus.HARDWARE,
            FaultType.COMM_ERROR,
            0.99,
            Severity.HIGH,
            "One or more channels were null (communication or sensor gap).",
        )
    if tier1.range_fail or tier1.step_fail:
        channel = tier1.fail_channel
        label = CHANNEL_LABEL[channel] if channel else "A sensor"
        kind = "range" if tier1.range_fail else "step"
        return (
            PipelineStatus.HARDWARE,
            FaultType.SPIKE,
            0.95,
            Severity.HIGH,
            f"{label} failed the {kind} check and was treated as a hardware spike.",
        )
    return PipelineStatus.CLEAN, None, None, None, None
