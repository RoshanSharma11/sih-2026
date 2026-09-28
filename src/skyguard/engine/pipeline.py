"""Ingest orchestrator: persist raw, call v2, persist overlay/alert/health."""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from skyguard.data.inject import Observation
from skyguard.db.models import AnomalyAlert, Station, TelemetryLog
from skyguard.engine.adapter import (
    UNCONFIRMED_FALLBACK,
    build_ml_payload,
    dump_json,
    load_corr,
    load_model,
    map_ml_result,
    qc_has_scaler,
    unknown_station_error_type,
)
from skyguard.engine.demo import DemoController
from skyguard.engine.windows import WindowPoint, WindowStore
from skyguard.errors import CatalogNotLoaded, DuplicateObservation, StationNotFound, UnknownScaler
from skyguard.notify import Notifier, WebhookEvent, should_page_alert, should_page_status
from skyguard.schemas import (
    Channel,
    ChannelValues,
    FaultType,
    ImputedInterval,
    IngestPayload,
    IngestResult,
    Label,
    LatestSnapshot,
    PipelineStatus,
    SeedObservation,
    Severity,
    StationStatus,
    ThermoView,
)

_HEALTH_HOURS = 24 * 7
_HEALTHY_MIN = 0.90
_DEGRADED_MIN = 0.70
_SENSOR_HEALTH_LABELS = {
    Label.PHYSICAL_FAULT.value,
    Label.HARDWARE_ANOMALY.value,
    Label.UNCONFIRMED_ANOMALY.value,
}
_STATION_LOCKS: dict[str, threading.RLock] = defaultdict(threading.RLock)


@contextmanager
def hold_station_locks(station_ids: list[str]) -> Iterator[None]:
    """Hold every station lock for one replay so a live poll cannot join that window.

    Locks are re-entrant. `ingest_observation` takes the same lock on this thread.
    """
    locks = [_STATION_LOCKS[station_id] for station_id in sorted(set(station_ids))]
    for lock in locks:
        lock.acquire()
    try:
        yield
    finally:
        for lock in reversed(locks):
            lock.release()


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def feed_gap_for(payload: IngestPayload, feed_gap: list[Channel] | None) -> list[Channel]:
    """Channels that are both network-wide missing this hour and missing on this payload.

    A station that did report the channel is scored normally even during a feed gap.
    """
    if not feed_gap:
        return []
    values = {
        Channel.TEMP_C: payload.temp_c,
        Channel.PRES_HPA: payload.pres_hpa,
        Channel.RHUM_PCT: payload.rhum_pct,
    }
    return [channel for channel in feed_gap if values.get(channel) is None]


def feed_gap_from_row(row: TelemetryLog) -> list[Channel]:
    if not row.feed_gap:
        return []
    try:
        return [Channel(value) for value in json.loads(row.feed_gap)]
    except (ValueError, TypeError):
        return []


def ingest_observation(
    session: Session,
    payload: IngestPayload,
    catalog_ready: bool,
    windows: WindowStore,
    residuals=None,
    demo: DemoController | None = None,
    detector=None,
    qc_engine=None,
    feed_gap: list[Channel] | None = None,
    notifier: Notifier | None = None,
) -> IngestResult:
    """Persist one hour and run v2 QC on it.

    `feed_gap` lists channels the upstream feed left empty on most stations this hour
    (see `skyguard.imd.poller.detect_feed_gap`). Such an hour is stored raw with a null
    label, is not sent to v2, opens no alert and does not charge 7-day health: the
    sensor did not fail, the feed did.
    """
    del residuals, detector
    if not catalog_ready:
        raise CatalogNotLoaded("Station catalog not loaded")

    station = session.get(Station, payload.station_id)
    if station is None:
        raise StationNotFound(payload.station_id)

    scaler = qc_has_scaler(qc_engine, payload.station_id)
    if scaler is False:
        raise UnknownScaler(payload.station_id)

    timestamp = as_utc(payload.timestamp)
    with _STATION_LOCKS[payload.station_id]:
        _reject_duplicate(session, payload.station_id, timestamp)

        observed = Observation(payload.temp_c, payload.pres_hpa, payload.rhum_pct)
        demo_injected = None
        if demo is not None:
            observed, demo_injected = demo.apply(payload.station_id, observed)

        current = WindowPoint(timestamp, observed.temp_c, observed.pres_hpa, observed.rhum_pct)
        gap_channels = feed_gap_for(payload, feed_gap)
        row = TelemetryLog(
            station_id=payload.station_id,
            timestamp=timestamp,
            temp_observed=observed.temp_c,
            pres_observed=observed.pres_hpa,
            rhum_observed=observed.rhum_pct,
            is_anomaly=False,
            label=None,
            pipeline_status=None,
            warming_up=True,
            feed_gap=json.dumps([channel.value for channel in gap_channels]) if gap_channels else None,
        )
        session.add(row)
        session.flush()
        windows.append(payload.station_id, current)

        warming = len(windows.points(payload.station_id)) < windows.size
        if warming or gap_channels:
            row.warming_up = warming
            health_score, station_status = health_from_stored_labels(
                session, payload.station_id, timestamp
            )
            station.health_score = health_score
            station.status = station_status.value
            return result_from_row(station, row, demo_injected=demo_injected)

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
                raise UnknownScaler(payload.station_id) from exc
            raise
        mapped = map_ml_result(ml_out)
        _apply_overlay(row, mapped)
        session.flush()
        previous_status = station.status
        health_score, station_status = health_from_stored_labels(
            session, payload.station_id, timestamp
        )
        station.health_score = health_score
        station.status = station_status.value
        alert: AnomalyAlert | None = None
        if mapped["is_anomaly"]:
            contrib = mapped["contribution_pct"]
            alert = AnomalyAlert(
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
            session.add(alert)
            session.flush()
        _page(notifier, station, timestamp, previous_status, alert)

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
            imputed_interval=mapped["imputed_interval"],
            thermo=mapped["thermo"],
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
    imputed_interval: ImputedInterval | None = None,
    thermo: ThermoView | None = None,
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
        pipeline_status=_pipeline_status(row.pipeline_status),
        warming_up=bool(row.warming_up),
        feed_gap=feed_gap_from_row(row),
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
        imputed_interval=imputed_interval,
        thermo=thermo,
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
        pipeline_status=_pipeline_status(row.pipeline_status),
        warming_up=bool(row.warming_up),
        feed_gap=feed_gap_from_row(row),
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


def health_from_stored_labels(
    session: Session, station_id: str, as_of: datetime
) -> tuple[float, StationStatus]:
    """7-day flag rate from stored labels. Weather does not count. Not the engine tracker."""
    cutoff = as_of - timedelta(hours=_HEALTH_HOURS)
    labels = session.scalars(
        select(TelemetryLog.label).where(
            TelemetryLog.station_id == station_id,
            TelemetryLog.timestamp >= cutoff,
            TelemetryLog.timestamp <= as_of,
        )
    ).all()
    labels = [label for label in labels if label]
    count = len(labels)
    if count == 0:
        return 100.0, StationStatus.HEALTHY
    flagged = sum(1 for label in labels if label in _SENSOR_HEALTH_LABELS)
    index = 1.0 - (flagged / count)
    if index >= _HEALTHY_MIN:
        status = StationStatus.HEALTHY
    elif index >= _DEGRADED_MIN:
        status = StationStatus.DEGRADED
    else:
        status = StationStatus.CRITICAL
    return round(index * 100.0, 2), status


def telemetry_qc(row: TelemetryLog) -> dict:
    return {
        "feed_gap": feed_gap_from_row(row),
        "explainability_text": row.explainability_text,
        "imputed_interval": load_model(row.imputed_interval, ImputedInterval),
        "thermo": load_model(row.thermo, ThermoView),
        "tier2_score": row.tier2_score,
        "tier3_method": row.tier3_method,
        "tier3_mix": load_model(row.tier3_mix, ChannelValues),
        "tier3_corr": load_corr(row.tier3_corr),
    }


def _apply_overlay(row: TelemetryLog, mapped: dict) -> None:
    tier3 = mapped["tier3"]
    row.temp_imputed = mapped["imputed"].temp_c
    row.pres_imputed = mapped["imputed"].pres_hpa
    row.rhum_imputed = mapped["imputed"].rhum_pct
    row.is_anomaly = mapped["is_anomaly"]
    row.pipeline_status = mapped["pipeline_status"].value
    row.label = mapped["label"].value
    row.warming_up = False
    row.mse = mapped["mse"]
    row.explainability_text = mapped["explainability_text"]
    row.imputed_interval = dump_json(mapped["imputed_interval"])
    row.thermo = dump_json(mapped["thermo"])
    row.tier2_score = mapped["tier2"].score
    row.tier3_method = tier3.method
    row.tier3_mix = dump_json(tier3.mix)
    row.tier3_corr = dump_json(tier3.corr)


def _page(
    notifier: Notifier | None,
    station: Station,
    timestamp: datetime,
    previous_status: str | None,
    alert: AnomalyAlert | None,
) -> None:
    """Queue webhook events. Never raises; never blocks ingest on the network."""
    if notifier is None or not notifier.enabled:
        return
    if should_page_status(previous_status, station.status):
        notifier.notify(
            WebhookEvent(
                event="station_status_changed",
                station_id=station.station_id,
                station_name=station.name,
                timestamp=timestamp,
                status=station.status,
                previous_status=previous_status,
                health_score=station.health_score,
                label=None if alert is None else alert.label,
                fault_type=None if alert is None else alert.fault_type,
                reason=None if alert is None else alert.explainability_text,
            )
        )
    if alert is not None and should_page_alert(alert.label, alert.severity):
        notifier.notify(
            WebhookEvent(
                event="alert_opened",
                station_id=station.station_id,
                station_name=station.name,
                timestamp=timestamp,
                status=station.status,
                health_score=station.health_score,
                label=alert.label,
                fault_type=alert.fault_type,
                severity=alert.severity,
                reason=alert.explainability_text,
                alert_id=alert.alert_id,
            )
        )


def _pipeline_status(value: str | None) -> PipelineStatus | None:
    if not value:
        return None
    return PipelineStatus(value)


def _reject_duplicate(session: Session, station_id: str, timestamp: datetime) -> None:
    already = session.scalar(
        select(TelemetryLog.id).where(
            TelemetryLog.station_id == station_id,
            TelemetryLog.timestamp == timestamp,
        )
    )
    if already is not None:
        raise DuplicateObservation(f"{station_id} {timestamp.isoformat()}")
