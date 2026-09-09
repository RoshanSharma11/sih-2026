"""Ingest orchestrator: persist raw, call ML, persist overlay/alert/health."""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from skyguard.data.inject import Observation
from skyguard.db.models import AnomalyAlert, Station, TelemetryLog
from skyguard.engine.adapter import (
    UNCONFIRMED_FALLBACK,
    build_ml_payload,
    map_ml_result,
    qc_has_scaler,
    unknown_station_error_type,
)
from skyguard.engine.demo import DemoController
from skyguard.engine.windows import WindowPoint, WindowStore
from skyguard.errors import CatalogNotLoaded, DuplicateObservation, StationNotFound
from skyguard.schemas import (
    ChannelValues,
    FaultType,
    IngestPayload,
    IngestResult,
    Label,
    LatestSnapshot,
    PipelineStatus,
    SeedObservation,
    Severity,
    StationStatus,
)

_STATION_LOCKS: dict[str, threading.Lock] = defaultdict(threading.Lock)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def ingest_observation(
    session: Session,
    payload: IngestPayload,
    catalog_ready: bool,
    windows: WindowStore,
    residuals=None,
    demo: DemoController | None = None,
    detector=None,
    qc_engine=None,
) -> IngestResult:
    del residuals, detector
    if not catalog_ready:
        raise CatalogNotLoaded("Station catalog not loaded")

    station = session.get(Station, payload.station_id)
    if station is None:
        raise StationNotFound(payload.station_id)

    scaler = qc_has_scaler(qc_engine, payload.station_id)
    if scaler is False:
        raise StationNotFound(payload.station_id)

    timestamp = as_utc(payload.timestamp)
    with _STATION_LOCKS[payload.station_id]:
        _reject_duplicate(session, payload.station_id, timestamp)

        observed = Observation(payload.temp_c, payload.pres_hpa, payload.rhum_pct)
        demo_injected = None
        if demo is not None:
            observed, demo_injected = demo.apply(payload.station_id, observed)

        current = WindowPoint(timestamp, observed.temp_c, observed.pres_hpa, observed.rhum_pct)
        row = TelemetryLog(
            station_id=payload.station_id,
            timestamp=timestamp,
            temp_observed=observed.temp_c,
            pres_observed=observed.pres_hpa,
            rhum_observed=observed.rhum_pct,
            is_anomaly=False,
            label=Label.CLEAN.value,
            pipeline_status=PipelineStatus.UNKNOWN.value,
        )
        session.add(row)
        session.flush()
        windows.append(payload.station_id, current)

        try:
            ml_out = _run_qc(
                qc_engine,
                build_ml_payload(
                    session,
                    payload.station_id,
                    timestamp,
                    observed.temp_c,
                    observed.pres_hpa,
                    observed.rhum_pct,
                    windows,
                ),
            )
        except Exception as exc:
            unknown = unknown_station_error_type()
            if unknown is not None and isinstance(exc, unknown):
                raise StationNotFound(payload.station_id) from exc
            raise
        mapped = map_ml_result(ml_out)
        _apply_overlay(row, station, mapped)
        if mapped["is_anomaly"]:
            contrib = mapped["contribution_pct"]
            session.add(
                AnomalyAlert(
                    station_id=payload.station_id,
                    timestamp=timestamp,
                    label=mapped["label"].value,
                    fault_type=(mapped["fault_type"] or FaultType.UNKNOWN).value,
                    confidence_score=mapped["confidence"] or 0.0,
                    severity=(mapped["severity"] or Severity.LOW).value,
                    explainability_text=mapped["explainability_text"]
                    or "Pipeline flagged this observation.",
                    contribution_temp=contrib.temp_c,
                    contribution_pres=contrib.pres_hpa,
                    contribution_rhum=contrib.rhum_pct,
                )
            )
            session.flush()

        return result_from_row(
            station,
            row,
            fault_type=mapped["fault_type"],
            confidence=mapped["confidence"],
            severity=mapped["severity"],
            explainability_text=mapped["explainability_text"],
            contribution=mapped["contribution_pct"],
            demo_injected=demo_injected,
            label=mapped["label"],
            affected_variables=mapped["affected_variables"],
            tier1=mapped["tier1"],
            tier2=mapped["tier2"],
            tier3=mapped["tier3"],
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
                label=Label.CLEAN.value,
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
    classification=None,
    contribution: ChannelValues | None = None,
    mse_vector: ChannelValues | None = None,
    demo_injected: FaultType | None = None,
    label: Label | None = None,
    affected_variables: list[str] | None = None,
    tier1=None,
    tier2=None,
    tier3=None,
) -> IngestResult:
    if classification is not None:
        fault_type = classification.fault_type
        confidence = classification.confidence
        severity = classification.severity
        explainability_text = classification.explainability_text
    resolved_label = label
    if resolved_label is None and row.label:
        try:
            resolved_label = Label(row.label)
        except ValueError:
            resolved_label = None
    return IngestResult(
        station_id=station.station_id,
        timestamp=as_utc(row.timestamp),
        label=resolved_label,
        pipeline_status=PipelineStatus(row.pipeline_status),
        fault_type=fault_type,
        confidence=confidence,
        severity=severity,
        explainability_text=explainability_text,
        affected_variables=affected_variables or [],
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
        mse_vector=mse_vector or ChannelValues(),
        health_score=station.health_score,
        station_status=StationStatus(station.status),
        demo_injected=demo_injected,
        tier1=tier1,
        tier2=tier2,
        tier3=tier3,
    )


def latest_snapshot_from_row(row: TelemetryLog) -> LatestSnapshot:
    label = None
    if row.label:
        try:
            label = Label(row.label)
        except ValueError:
            label = None
    return LatestSnapshot(
        timestamp=as_utc(row.timestamp),
        label=label,
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
    )


def _run_qc(qc_engine, payload: dict) -> dict:
    if qc_engine is None:
        return dict(UNCONFIRMED_FALLBACK)
    unknown = unknown_station_error_type()
    try:
        return qc_engine.process_aws_data(payload)
    except Exception as exc:
        if unknown is not None and isinstance(exc, unknown):
            raise
        return dict(UNCONFIRMED_FALLBACK)


def _apply_overlay(row: TelemetryLog, station: Station, mapped: dict) -> None:
    row.temp_imputed = mapped["imputed"].temp_c
    row.pres_imputed = mapped["imputed"].pres_hpa
    row.rhum_imputed = mapped["imputed"].rhum_pct
    row.is_anomaly = mapped["is_anomaly"]
    row.pipeline_status = mapped["pipeline_status"].value
    row.label = mapped["label"].value
    row.mse = mapped["mse"]
    station.health_score = mapped["health_score"]
    station.status = mapped["station_status"].value


def _reject_duplicate(session: Session, station_id: str, timestamp: datetime) -> None:
    already = session.scalar(
        select(TelemetryLog.id).where(
            TelemetryLog.station_id == station_id,
            TelemetryLog.timestamp == timestamp,
        )
    )
    if already is not None:
        raise DuplicateObservation(f"{station_id} {timestamp.isoformat()}")
