"""In-memory 24-hour station windows."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from skyguard.config import WINDOW_HOURS
from skyguard.db.models import Station, TelemetryLog


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class WindowPoint:
    timestamp: datetime
    temp_c: float | None
    pres_hpa: float | None
    rhum_pct: float | None


class WindowStore:
    def __init__(self, size: int = WINDOW_HOURS) -> None:
        self.size = size
        self._windows: dict[str, deque[WindowPoint]] = defaultdict(lambda: deque(maxlen=size))

    def last(self, station_id: str) -> WindowPoint | None:
        window = self._windows.get(station_id)
        if not window:
            return None
        return window[-1]

    def points(self, station_id: str) -> list[WindowPoint]:
        return list(self._windows.get(station_id, ()))

    def append(self, station_id: str, point: WindowPoint) -> None:
        self._windows[station_id].append(point)

    def hydrate(self, session: Session) -> None:
        station_ids = session.scalars(select(Station.station_id)).all()
        for station_id in station_ids:
            rows = session.scalars(
                select(TelemetryLog)
                .where(TelemetryLog.station_id == station_id)
                .order_by(TelemetryLog.timestamp.desc())
                .limit(self.size)
            ).all()
            for row in reversed(list(rows)):
                self.append(
                    station_id,
                    WindowPoint(
                        timestamp=_as_utc(row.timestamp),
                        temp_c=row.temp_observed,
                        pres_hpa=row.pres_observed,
                        rhum_pct=row.rhum_observed,
                    ),
                )
