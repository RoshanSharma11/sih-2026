"""Ingest orchestrator: persist raw, run tiers, classify, update health."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from skyguard.data.inject import Observation
from skyguard.db.models import AnomalyAlert, Station, TelemetryLog
from skyguard.engine import health as health_mod
from skyguard.engine.classify import Classification, classify
from skyguard.engine.demo import DemoController
from skyguard.engine.tier1 import evaluate as evaluate_tier1
from skyguard.engine.tier3 import BuddyResult, ResidualStore, evaluate as evaluate_buddy, load_neighbors
from skyguard.engine.windows import WindowPoint, WindowStore
from skyguard.errors import CatalogNotLoaded, DuplicateObservation, StationNotFound
from skyguard.schemas import (
    Channel,
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
    residuals: ResidualStore | None = None,
    demo: DemoController | None = None,
) -> IngestResult:
    if not catalog_ready:
        raise CatalogNotLoaded("Station catalog not loaded")

    station = session.get(Station, payload.station_id)
    if station is None:
        raise StationNotFound(payload.station_id)

    timestamp = as_utc(payload.timestamp)
    _reject_duplicate(session, payload.station_id, timestamp)

    observed = Observation(payload.temp_c, payload.pres_hpa, payload.rhum_pct)
    demo_injected = None
    if demo is not None:
        observed, demo_injected = demo.apply(payload.station_id, observed)

    current = WindowPoint(timestamp, observed.temp_c, observed.pres_hpa, observed.rhum_pct)
    previous = windows.last(payload.station_id)
    tier1 = evaluate_tier1(current, previous)
    neighbors = [] if tier1.comm_error else load_neighbors(session, station, timestamp)
    buddy = (
        BuddyResult()
        if tier1.comm_error
        else evaluate_buddy(station, current, previous, neighbors)
    )
    tracker = residuals if residuals is not None else ResidualStore()
    tracker.update(payload.station_id, buddy.spatial_residual)
    decision = classify(
        cluster_id=station.cluster_id,
        current=current,
        points=[*windows.points(payload.station_id), current],
        tier1=tier1,
        buddy=buddy,
        drift=tracker.drift_detected(payload.station_id),
    )

    row = TelemetryLog(
        station_id=payload.station_id,
        timestamp=timestamp,
        temp_observed=observed.temp_c,
        pres_observed=observed.pres_hpa,
        rhum_observed=observed.rhum_pct,
        is_anomaly=decision.pipeline_status is PipelineStatus.HARDWARE,
        pipeline_status=decision.pipeline_status.value,
    )
    session.add(row)
    session.flush()

    contrib = _contributions(decision.fail_channel)
    if decision.pipeline_status is not PipelineStatus.CLEAN:
        session.add(
            AnomalyAlert(
                station_id=payload.station_id,
                timestamp=timestamp,
                fault_type=(decision.fault_type or FaultType.UNKNOWN).value,
                confidence_score=decision.confidence or 0.5,
                severity=(decision.severity or Severity.LOW).value,
                explainability_text=decision.explainability_text or "Pipeline flagged this observation.",
                contribution_temp=contrib[Channel.TEMP_C],
                contribution_pres=contrib[Channel.PRES_HPA],
                contribution_rhum=contrib[Channel.RHUM_PCT],
            )
        )
        session.flush()

    health_mod.recompute(session, station, timestamp)
    windows.append(payload.station_id, current)
    return result_from_row(
        station,
        row,
        classification=decision,
        contribution=ChannelValues(
            temp_c=contrib[Channel.TEMP_C],
            pres_hpa=contrib[Channel.PRES_HPA],
            rhum_pct=contrib[Channel.RHUM_PCT],
        ),
        demo_injected=demo_injected,
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
    classification: Classification | None = None,
    contribution: ChannelValues | None = None,
    demo_injected: FaultType | None = None,
) -> IngestResult:
    if classification is not None:
        fault_type = classification.fault_type
        confidence = classification.confidence
        severity = classification.severity
        explainability_text = classification.explainability_text
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
        contribution_pct=contribution or ChannelValues(),
        mse=row.mse,
        mse_vector=ChannelValues(),
        health_score=station.health_score,
        station_status=StationStatus(station.status),
        demo_injected=demo_injected,
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


def _contributions(channel: Channel | None) -> dict[Channel, float | None]:
    values: dict[Channel, float | None] = {
        Channel.TEMP_C: 0.0,
        Channel.PRES_HPA: 0.0,
        Channel.RHUM_PCT: 0.0,
    }
    if channel is not None:
        values[channel] = 100.0
    return values
