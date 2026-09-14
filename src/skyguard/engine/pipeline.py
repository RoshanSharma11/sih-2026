"""Ingest orchestrator: persist raw, call ML, persist overlay/alert/health."""

from __future__ import annotations

import json
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
    TelemetryRow,
    Tier1View,
    Tier2View,
    Tier3View,
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
        _apply_overlay(row, station, mapped, demo_injected=demo_injected)
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


def telemetry_row_from_log(row: TelemetryLog) -> TelemetryRow:
    return TelemetryRow(
        station_id=row.station_id,
        timestamp=as_utc(row.timestamp),
        temp_observed=row.temp_observed,
        pres_observed=row.pres_observed,
        rhum_observed=row.rhum_observed,
        temp_imputed=row.temp_imputed,
        pres_imputed=row.pres_imputed,
        rhum_imputed=row.rhum_imputed,
        is_anomaly=bool(row.is_anomaly),
        label=_label(row.label),
        pipeline_status=_pipeline(row.pipeline_status),
        mse=row.mse,
        fault_type=_fault(row.fault_type),
        confidence=row.confidence,
        severity=_severity(row.severity),
        explainability_text=row.explainability_text,
        contribution_temp=row.contribution_temp,
        contribution_pres=row.contribution_pres,
        contribution_rhum=row.contribution_rhum,
        demo_injected=_fault(row.demo_injected),
        affected_variables=_string_list(row.affected_variables),
        tier1=_tier1(row.tier1_json),
        tier2=_tier2(row.tier2_json),
        tier3=_tier3(row.tier3_json),
    )


def latest_snapshot_from_row(row: TelemetryLog) -> LatestSnapshot:
    contrib = ChannelValues(
        temp_c=row.contribution_temp,
        pres_hpa=row.contribution_pres,
        rhum_pct=row.contribution_rhum,
    )
    return LatestSnapshot(
        timestamp=as_utc(row.timestamp),
        label=_label(row.label),
        pipeline_status=_pipeline(row.pipeline_status),
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
        is_anomaly=bool(row.is_anomaly),
        fault_type=_fault(row.fault_type),
        confidence=row.confidence,
        severity=_severity(row.severity),
        explainability_text=row.explainability_text,
        demo_injected=_fault(row.demo_injected),
        contribution_pct=contrib,
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


def _apply_overlay(
    row: TelemetryLog,
    station: Station,
    mapped: dict,
    demo_injected: FaultType | None = None,
) -> None:
    contrib = mapped["contribution_pct"]
    row.temp_imputed = mapped["imputed"].temp_c
    row.pres_imputed = mapped["imputed"].pres_hpa
    row.rhum_imputed = mapped["imputed"].rhum_pct
    row.is_anomaly = mapped["is_anomaly"]
    row.pipeline_status = mapped["pipeline_status"].value
    row.label = mapped["label"].value
    row.mse = mapped["mse"]
    row.fault_type = mapped["fault_type"].value if mapped["fault_type"] else None
    row.confidence = mapped["confidence"]
    row.severity = mapped["severity"].value if mapped["severity"] else None
    row.explainability_text = mapped["explainability_text"]
    row.contribution_temp = contrib.temp_c
    row.contribution_pres = contrib.pres_hpa
    row.contribution_rhum = contrib.rhum_pct
    row.demo_injected = demo_injected.value if demo_injected else None
    row.affected_variables = list(mapped["affected_variables"] or [])
    row.tier1_json = _dump_view(mapped.get("tier1"))
    row.tier2_json = _dump_view(mapped.get("tier2"))
    row.tier3_json = _dump_view(mapped.get("tier3"))
    station.health_score = mapped["health_score"]
    station.status = mapped["station_status"].value


def _dump_view(view) -> dict | None:
    if view is None:
        return None
    if hasattr(view, "model_dump"):
        return view.model_dump(mode="json")
    if isinstance(view, dict):
        return view
    return None


def _pipeline(value: str | None) -> PipelineStatus:
    try:
        return PipelineStatus(value) if value else PipelineStatus.UNKNOWN
    except ValueError:
        return PipelineStatus.UNKNOWN


def _fault(value: str | None) -> FaultType | None:
    if not value:
        return None
    try:
        return FaultType(value)
    except ValueError:
        return None


def _severity(value: str | None) -> Severity | None:
    if not value:
        return None
    try:
        return Severity(value)
    except ValueError:
        return None


def _label(value: str | None) -> Label | None:
    if not value:
        return None
    try:
        return Label(value)
    except ValueError:
        return None


def _string_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except ValueError:
            return [value]
        value = loaded
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _as_dict(value) -> dict | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except ValueError:
            return None
        return loaded if isinstance(loaded, dict) else None
    return None


def _tier1(raw) -> Tier1View | None:
    data = _as_dict(raw)
    if not data:
        return None
    return Tier1View.model_validate(data)


def _tier2(raw) -> Tier2View | None:
    data = _as_dict(raw)
    if not data:
        return None
    return Tier2View.model_validate(data)


def _tier3(raw) -> Tier3View | None:
    data = _as_dict(raw)
    if not data:
        return None
    return Tier3View.model_validate(data)


def _reject_duplicate(session: Session, station_id: str, timestamp: datetime) -> None:
    already = session.scalar(
        select(TelemetryLog.id).where(
            TelemetryLog.station_id == station_id,
            TelemetryLog.timestamp == timestamp,
        )
    )
    if already is not None:
        raise DuplicateObservation(f"{station_id} {timestamp.isoformat()}")
