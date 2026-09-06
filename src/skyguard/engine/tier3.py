"""Cluster IDW buddy check. Neighbors stay inside one cluster."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from skyguard.config import BUDDY_KM, IDW_POWER
from skyguard.data.catalog import haversine_km
from skyguard.db.models import Station, TelemetryLog
from skyguard.engine.windows import WindowPoint
from skyguard.schemas import Channel

BUDDY_MAX_AGE = timedelta(seconds=3600)
RESIDUAL_CUT = {
    Channel.TEMP_C: 4.0,
    Channel.PRES_HPA: 4.0,
    Channel.RHUM_PCT: 15.0,
}
STORM_MOVE = {
    Channel.TEMP_C: 5.0,
    Channel.PRES_HPA: 5.0,
    Channel.RHUM_PCT: 15.0,
}
CHANNEL_SCALE = {
    Channel.TEMP_C: 1.0,
    Channel.PRES_HPA: 1.0,
    Channel.RHUM_PCT: 1.0,
}
MIN_DISTANCE_KM = 0.001
DRIFT_HOURS = 24
DRIFT_RISE = 3.0


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass
class NeighborReading:
    station_id: str
    latitude: float
    longitude: float
    timestamp: datetime
    temp_c: float
    pres_hpa: float
    rhum_pct: float
    contemporaneous: bool

    def value(self, channel: Channel) -> float:
        return float(getattr(self, channel.value))


@dataclass
class BuddyResult:
    neighbors: list[NeighborReading] = field(default_factory=list)
    contemporaneous: bool = False
    idw: dict[Channel, float] = field(default_factory=dict)
    residual: dict[Channel, float] = field(default_factory=dict)
    spatial_residual: float | None = None
    large: bool = False
    storm_shaped: bool = False
    heat_shaped: bool = False

    @property
    def neighbor_count(self) -> int:
        return len(self.neighbors)

    def one_channel_large(self) -> bool:
        over = [channel for channel, cut in RESIDUAL_CUT.items() if abs(self.residual.get(channel, 0.0)) > cut]
        return len(over) == 1


class ResidualStore:
    """In-memory hourly buddy residuals for drift detection."""

    def __init__(self, size: int = DRIFT_HOURS) -> None:
        self.size = size
        self._hourly: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=size))

    def update(self, station_id: str, residual: float | None) -> None:
        if residual is None:
            return
        self._hourly[station_id].append(float(residual))

    def drift_detected(self, station_id: str) -> bool:
        series = list(self._hourly.get(station_id, ()))
        if len(series) < self.size:
            return False
        rising = all(series[i] <= series[i + 1] + 1e-9 for i in range(len(series) - 1))
        return rising and (series[-1] - series[0]) >= DRIFT_RISE and series[-1] > RESIDUAL_CUT[Channel.TEMP_C]


def storm_shape(current: WindowPoint, previous: WindowPoint | None) -> tuple[bool, bool]:
    if previous is None:
        return False, False
    if None in (
        current.temp_c,
        current.pres_hpa,
        current.rhum_pct,
        previous.temp_c,
        previous.pres_hpa,
        previous.rhum_pct,
    ):
        return False, False
    d_temp = current.temp_c - previous.temp_c
    d_pres = current.pres_hpa - previous.pres_hpa
    d_rhum = current.rhum_pct - previous.rhum_pct
    storm = (
        d_temp <= -STORM_MOVE[Channel.TEMP_C]
        and d_pres <= -STORM_MOVE[Channel.PRES_HPA]
        and d_rhum >= STORM_MOVE[Channel.RHUM_PCT]
    )
    heat = (
        d_temp >= STORM_MOVE[Channel.TEMP_C]
        and d_pres >= STORM_MOVE[Channel.PRES_HPA]
        and d_rhum <= -STORM_MOVE[Channel.RHUM_PCT]
    )
    return storm, heat


def idw_value(values: list[float], distances_km: list[float], power: float = IDW_POWER) -> float:
    weights = []
    for distance in distances_km:
        weights.append(max(distance, MIN_DISTANCE_KM) ** -power)
    total = sum(weights)
    return sum(weight * value for weight, value in zip(weights, values, strict=True)) / total


def load_neighbors(session: Session, station: Station, timestamp: datetime) -> list[NeighborReading]:
    cutoff = timestamp - BUDDY_MAX_AGE
    rows = session.execute(
        select(TelemetryLog, Station)
        .join(Station, Station.station_id == TelemetryLog.station_id)
        .where(Station.cluster_id == station.cluster_id)
        .where(TelemetryLog.station_id != station.station_id)
        .where(TelemetryLog.timestamp >= cutoff)
        .where(TelemetryLog.timestamp <= timestamp)
    ).all()
    latest: dict[str, NeighborReading] = {}
    for log, other in rows:
        if None in (log.temp_observed, log.pres_observed, log.rhum_observed):
            continue
        if haversine_km(station.latitude, station.longitude, other.latitude, other.longitude) > BUDDY_KM:
            continue
        contemporaneous = _utc(log.timestamp) == _utc(timestamp)
        reading = NeighborReading(
            station_id=other.station_id,
            latitude=other.latitude,
            longitude=other.longitude,
            timestamp=log.timestamp,
            temp_c=float(log.temp_observed),
            pres_hpa=float(log.pres_observed),
            rhum_pct=float(log.rhum_observed),
            contemporaneous=contemporaneous,
        )
        existing = latest.get(other.station_id)
        if existing is None or contemporaneous or (not existing.contemporaneous and log.timestamp > existing.timestamp):
            latest[other.station_id] = reading
    return list(latest.values())


def evaluate(
    station: Station,
    current: WindowPoint,
    previous: WindowPoint | None,
    neighbors: list[NeighborReading],
) -> BuddyResult:
    result = BuddyResult(neighbors=neighbors)
    result.storm_shaped, result.heat_shaped = storm_shape(current, previous)
    result.contemporaneous = any(item.contemporaneous for item in neighbors)
    if not neighbors:
        return result
    if None in (current.temp_c, current.pres_hpa, current.rhum_pct):
        return result

    distances = [
        haversine_km(station.latitude, station.longitude, item.latitude, item.longitude) for item in neighbors
    ]
    observed = {
        Channel.TEMP_C: current.temp_c,
        Channel.PRES_HPA: current.pres_hpa,
        Channel.RHUM_PCT: current.rhum_pct,
    }
    for channel in observed:
        estimate = idw_value([item.value(channel) for item in neighbors], distances)
        result.idw[channel] = estimate
        result.residual[channel] = float(observed[channel] - estimate)
        if abs(result.residual[channel]) > RESIDUAL_CUT[channel]:
            result.large = True
    result.spatial_residual = max(
        abs(result.residual[channel]) / CHANNEL_SCALE[channel] for channel in observed
    )
    return result
