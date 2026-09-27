"""Play demo_windows.json through ingest. Mutations arm before QC, then clear."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from skyguard.config import DEMO_WINDOWS_PATH
from skyguard.db.models import AnomalyAlert, Station, TelemetryLog
from skyguard.engine.demo import DemoController
from skyguard.engine.pipeline import as_utc, hold_station_locks, ingest_observation, seed_station
from skyguard.engine.windows import WindowStore
from skyguard.errors import InvalidDemoRequest, StationNotFound
from skyguard.schemas import IngestPayload, ReplayResult, ReplayStory, SeedObservation

REPLAY_END = datetime(2024, 12, 31, 23, 0, tzinfo=timezone.utc)
REPLAY_FREEZE_HOURS = 12
DEMO_IDS = ("43003", "43057", "43002", "43058", "42182")
SANTA_CRUZ = "43003"
# Buddies first so Santa Cruz is scored with full neighbor windows.
MUMBAI_FOUR = ("43057", "43002", "43058", SANTA_CRUZ)
# +8 °C on Santa Cruz, Colaba, and Juhu. Alibag is ingested on the fixture hour.
HEAT_IDS = (SANTA_CRUZ, "43057", "43002")

STORY_ORDER: dict[ReplayStory, tuple[str, ...]] = {
    ReplayStory.CLEAN: (*MUMBAI_FOUR, "42182"),
    ReplayStory.HARDWARE: MUMBAI_FOUR,
    ReplayStory.WEATHER: MUMBAI_FOUR,
    ReplayStory.FREEZE: (SANTA_CRUZ,),
    ReplayStory.COMMS: (SANTA_CRUZ,),
}
MUTATED: dict[ReplayStory, tuple[str, ...]] = {
    ReplayStory.HARDWARE: (SANTA_CRUZ,),
    ReplayStory.WEATHER: HEAT_IDS,
    ReplayStory.FREEZE: (SANTA_CRUZ,),
    ReplayStory.COMMS: (SANTA_CRUZ,),
}


@dataclass(frozen=True)
class ReplayHour:
    timestamp: datetime
    temp_c: float
    pres_hpa: float
    rhum_pct: float


def load_demo_windows(path: Path | None = None) -> dict[str, list[ReplayHour]]:
    target = path or DEMO_WINDOWS_PATH
    if not target.exists():
        raise InvalidDemoRequest("demo windows file is missing")
    blob = json.loads(target.read_text(encoding="utf-8"))
    stations = blob.get("stations") or {}
    loaded: dict[str, list[ReplayHour]] = {}
    for station_id in DEMO_IDS:
        raw = stations.get(station_id)
        if not raw:
            raise InvalidDemoRequest(f"{station_id} is missing from demo windows")
        hours = [_hour(station_id, row) for row in raw]
        hours.sort(key=lambda item: item.timestamp)
        if len(hours) < 24:
            raise InvalidDemoRequest(f"{station_id} demo window has {len(hours)} hours")
        hours = hours[-24:]
        if hours[-1].timestamp != REPLAY_END:
            raise InvalidDemoRequest(f"{station_id} demo window does not end at 2024-12-31T23:00:00Z")
        for previous, nxt in zip(hours, hours[1:]):
            if nxt.timestamp - previous.timestamp != timedelta(hours=1):
                raise InvalidDemoRequest(f"{station_id} demo window is not hourly")
        loaded[station_id] = hours
    return loaded


def play_replay(
    session: Session,
    story: ReplayStory,
    *,
    catalog_ready: bool,
    windows: WindowStore,
    demo: DemoController,
    qc_engine=None,
    fixture: Path | None = None,
) -> ReplayResult:
    hours = load_demo_windows(fixture)
    station_ids = list(STORY_ORDER[story])
    for station_id in station_ids:
        if session.get(Station, station_id) is None:
            raise StationNotFound(station_id)

    ingest_count = REPLAY_FREEZE_HOURS if story is ReplayStory.FREEZE else 1
    end = hours[SANTA_CRUZ][-1].timestamp
    with hold_station_locks(station_ids):
        saved = {station_id: windows.points(station_id) for station_id in station_ids}
        live = {
            station_id: points
            for station_id, points in saved.items()
            if any(point.timestamp > end for point in points)
        }
        try:
            _delete_span(session, hours, station_ids)
            for station_id in station_ids:
                windows.clear(station_id)
            for station_id in station_ids:
                prefix, _scored = _split(hours[station_id], ingest_count)
                seed_station(
                    session,
                    station_id,
                    _seed_rows(prefix),
                    catalog_ready,
                    windows,
                )
            mutated = MUTATED.get(story, ())
            if mutated:
                anchor = hours[SANTA_CRUZ][-1].temp_c if story is ReplayStory.FREEZE else None
                demo.arm_replay(story, list(mutated), ingest_count, anchor)
            results = []
            for station_id in station_ids:
                _prefix, scored = _split(hours[station_id], ingest_count)
                last = None
                for hour in scored:
                    last = ingest_observation(
                        session,
                        IngestPayload(
                            station_id=station_id,
                            timestamp=hour.timestamp,
                            temp_c=hour.temp_c,
                            pres_hpa=hour.pres_hpa,
                            rhum_pct=hour.rhum_pct,
                        ),
                        catalog_ready,
                        windows,
                        demo=demo,
                        qc_engine=qc_engine,
                    )
                if last is None:
                    raise InvalidDemoRequest(f"{station_id} replay ingested no hours")
                results.append(last)
        except Exception:
            for station_id, points in saved.items():
                windows.replace(station_id, points)
            raise
        finally:
            demo.clear_replay()
            for station_id, points in live.items():
                windows.replace(station_id, points)

    return ReplayResult(story=story, end=end, station_ids=station_ids, results=results)


def _hour(station_id: str, row: dict) -> ReplayHour:
    try:
        return ReplayHour(
            timestamp=_as_utc(row["timestamp"]),
            temp_c=float(row["temp"]),
            pres_hpa=float(row["pres"]),
            rhum_pct=float(row["rhum"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidDemoRequest(f"{station_id} demo window has a bad hour") from exc


def _as_utc(value: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _split(hours: list[ReplayHour], ingest_count: int) -> tuple[list[ReplayHour], list[ReplayHour]]:
    if ingest_count >= len(hours):
        raise InvalidDemoRequest("replay ingest is longer than the demo window")
    return hours[:-ingest_count], hours[-ingest_count:]


def _seed_rows(hours: list[ReplayHour]) -> list[SeedObservation]:
    return [
        SeedObservation(
            timestamp=hour.timestamp,
            temp_c=hour.temp_c,
            pres_hpa=hour.pres_hpa,
            rhum_pct=hour.rhum_pct,
        )
        for hour in hours
    ]


def _delete_span(session: Session, hours: dict[str, list[ReplayHour]], station_ids: list[str]) -> None:
    """Drop a previous play of this fixture. Compare instants in Python so SQLite's tz form still matches."""
    for station_id in station_ids:
        stamps = {hour.timestamp for hour in hours[station_id]}
        logs = session.scalars(select(TelemetryLog).where(TelemetryLog.station_id == station_id)).all()
        for row in logs:
            if as_utc(row.timestamp) in stamps:
                session.delete(row)
        alerts = session.scalars(select(AnomalyAlert).where(AnomalyAlert.station_id == station_id)).all()
        for row in alerts:
            if as_utc(row.timestamp) in stamps:
                session.delete(row)
    session.flush()
