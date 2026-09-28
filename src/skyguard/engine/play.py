"""Score armed overlays immediately, one after another, on 1 June 2024.

The December replay only mutates its last hour. Live inject waits for the next
IMD hour. This canvas seeds 23 clean hours from the demo diurnal cycle, then
ingests each armed overlay for its full duration so every one of those hours
is scored and a hardware hour can carry a prediction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from skyguard.config import WINDOW_HOURS
from skyguard.db.catalog import neighborhood_ids
from skyguard.db.models import AnomalyAlert, TelemetryLog
from skyguard.engine.demo import DemoController
from skyguard.engine.pipeline import as_utc, hold_station_locks, ingest_observation, seed_station
from skyguard.engine.replay import ReplayHour, load_demo_windows
from skyguard.engine.windows import WindowStore
from skyguard.errors import InvalidDemoRequest
from skyguard.schemas import (
    Channel,
    DemoInjectRequest,
    DemoKind,
    IngestPayload,
    IngestResult,
    PlayResult,
    SeedObservation,
)

# Away from the 31 Dec replay and from the live 2026 hours, so the chart is its own run.
PLAY_START = datetime(2024, 6, 1, 0, tzinfo=timezone.utc)
PLAY_SPAN = timedelta(days=14)
MAX_SCORED_HOURS = 48
SEED_HOURS = WINDOW_HOURS - 1


@dataclass(frozen=True)
class Segment:
    kind: DemoKind
    station_ids: list[str]
    channel: Channel | None
    hours: int


def play_overlays(
    session: Session,
    *,
    catalog_ready: bool,
    windows: WindowStore,
    demo: DemoController,
    qc_engine=None,
) -> PlayResult:
    segments = _segments(demo)
    if not segments:
        raise InvalidDemoRequest("Arm an event before playing it")
    scored = sum(segment.hours for segment in segments)
    if scored > MAX_SCORED_HOURS:
        raise InvalidDemoRequest(
            f"Armed overlays cover {scored} hours. Shorten them to {MAX_SCORED_HOURS} or fewer, then play."
        )

    templates = load_demo_windows()
    station_ids = _play_stations(session, segments, templates)
    primary = segments[0].station_ids[0]
    start = PLAY_START + timedelta(hours=SEED_HOURS)
    end = start + timedelta(hours=scored - 1)

    with hold_station_locks(station_ids):
        saved = {station_id: windows.points(station_id) for station_id in station_ids}
        live = {
            station_id: points
            for station_id, points in saved.items()
            if any(point.timestamp > end for point in points)
        }
        try:
            demo.reset()
            _delete_span(session, station_ids)
            for station_id in station_ids:
                windows.clear(station_id)
            for station_id in station_ids:
                seed_station(
                    session,
                    station_id,
                    _seed_rows(templates[station_id]),
                    catalog_ready,
                    windows,
                )
            last: dict[str, IngestResult] = {}
            cursor = SEED_HOURS
            for segment in segments:
                _arm(demo, segment)
                for _step in range(segment.hours):
                    for station_id in _hour_order(station_ids, segment, primary):
                        hour = _value(templates[station_id], cursor)
                        last[station_id] = ingest_observation(
                            session,
                            IngestPayload(
                                station_id=station_id,
                                timestamp=PLAY_START + timedelta(hours=cursor),
                                temp_c=hour.temp_c,
                                pres_hpa=hour.pres_hpa,
                                rhum_pct=hour.rhum_pct,
                            ),
                            catalog_ready,
                            windows,
                            demo=demo,
                            qc_engine=qc_engine,
                        )
                    cursor += 1
            demo.reset()
        except Exception:
            for station_id, points in saved.items():
                windows.replace(station_id, points)
            raise
        finally:
            for station_id, points in live.items():
                windows.replace(station_id, points)

    ordered = [station_id for station_id in station_ids if station_id != primary] + [primary]
    results = [last[station_id] for station_id in ordered if station_id in last]
    return PlayResult(
        start=start,
        end=end,
        station_ids=ordered,
        scored_hours=scored,
        results=results,
    )


def _segments(demo: DemoController) -> list[Segment]:
    rows: list[Segment] = []
    for overlay in demo.status().overlays:
        if overlay.remaining_hours < 1 or not overlay.station_ids:
            continue
        rows.append(
            Segment(
                kind=overlay.kind,
                station_ids=list(overlay.station_ids),
                channel=overlay.channel,
                hours=overlay.remaining_hours,
            )
        )
    return rows


def _arm(demo: DemoController, segment: Segment) -> None:
    if segment.kind is DemoKind.GENUINE_WEATHER:
        request = DemoInjectRequest(
            target="neighborhood",
            station_id=segment.station_ids[0],
            kind=segment.kind,
            duration_hours=segment.hours,
        )
    else:
        request = DemoInjectRequest(
            target="station",
            station_id=segment.station_ids[0],
            kind=segment.kind,
            channel=segment.channel,
            duration_hours=segment.hours,
        )
    demo.arm(request, segment.station_ids)


def _play_stations(session: Session, segments: list[Segment], templates: dict[str, list[ReplayHour]]) -> list[str]:
    ordered: list[str] = []
    for segment in segments:
        for station_id in segment.station_ids:
            if station_id not in ordered:
                ordered.append(station_id)
        for station_id in segment.station_ids:
            for buddy_id in neighborhood_ids(session, station_id)[1:]:
                if buddy_id not in ordered and buddy_id in templates:
                    ordered.append(buddy_id)
    missing = [station_id for station_id in ordered if station_id not in templates]
    if missing:
        raise InvalidDemoRequest(
            "Play uses the June demo cycle. These stations are not in it: " + ", ".join(missing)
        )
    return ordered


def _hour_order(station_ids: list[str], segment: Segment, primary: str) -> list[str]:
    mutated = set(segment.station_ids)
    clean = [station_id for station_id in station_ids if station_id not in mutated]
    touched = [station_id for station_id in segment.station_ids if station_id != primary]
    if primary in mutated:
        touched.append(primary)
    return clean + touched


def _value(hours: list[ReplayHour], index: int) -> ReplayHour:
    return hours[index % len(hours)]


def _seed_rows(hours: list[ReplayHour]) -> list[SeedObservation]:
    return [
        SeedObservation(
            timestamp=PLAY_START + timedelta(hours=index),
            temp_c=_value(hours, index).temp_c,
            pres_hpa=_value(hours, index).pres_hpa,
            rhum_pct=_value(hours, index).rhum_pct,
        )
        for index in range(SEED_HOURS)
    ]


def _delete_span(session: Session, station_ids: list[str]) -> None:
    """Drop a previous play of this canvas. Compare instants in Python so SQLite's tz form still matches."""
    stop = PLAY_START + PLAY_SPAN
    for station_id in station_ids:
        logs = session.scalars(select(TelemetryLog).where(TelemetryLog.station_id == station_id)).all()
        for row in logs:
            if PLAY_START <= as_utc(row.timestamp) < stop:
                session.delete(row)
        alerts = session.scalars(select(AnomalyAlert).where(AnomalyAlert.station_id == station_id)).all()
        for row in alerts:
            if PLAY_START <= as_utc(row.timestamp) < stop:
                session.delete(row)
    session.flush()
