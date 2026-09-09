"""In-memory demo overlays. Fault math stays in skyguard.data.inject."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from skyguard.data.catalog import resolve_view_and_ingest
from skyguard.data.inject import Observation, apply_live, default_rng
from skyguard.errors import InvalidDemoRequest
from skyguard.schemas import (
    Channel,
    DemoInjectRequest,
    DemoKind,
    DemoOverlayStatus,
    DemoStatus,
    FaultType,
    StreamFilterStatus,
)

DEFAULT_DURATION = {
    DemoKind.SPIKE: 1,
    DemoKind.COMM_ERROR: 1,
    DemoKind.FREEZE: 12,
    DemoKind.DRIFT: 48,
    DemoKind.GENUINE_WEATHER: 3,
}


def duration_for(kind: DemoKind, duration_hours: int | None) -> int:
    if duration_hours is None:
        return DEFAULT_DURATION[kind]
    if duration_hours < 1:
        raise InvalidDemoRequest("duration_hours must be >= 1")
    return duration_hours


@dataclass
class Overlay:
    kind: FaultType
    station_ids: list[str]
    channel: Channel | None
    remaining: dict[str, int]
    applied: dict[str, int]
    freeze_anchor: dict[str, float] = field(default_factory=dict)
    seed: int = 0

    @property
    def remaining_hours(self) -> int:
        return max(self.remaining.values(), default=0)

    @property
    def hour_index(self) -> int:
        return min(self.applied.values(), default=0)

    def active(self) -> bool:
        return self.remaining_hours > 0

    def status(self) -> DemoOverlayStatus:
        return DemoOverlayStatus(
            kind=DemoKind(self.kind.value),
            station_ids=list(self.station_ids),
            channel=self.channel,
            remaining_hours=self.remaining_hours,
            hour_index=self.hour_index,
        )


class DemoController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._overlays: list[Overlay] = []
        self._next_seed = 26073

    def arm(self, request: DemoInjectRequest, station_ids: list[str]) -> DemoOverlayStatus:
        if not station_ids:
            raise InvalidDemoRequest("demo inject requires at least one station")
        hours = duration_for(request.kind, request.duration_hours)
        ids = list(dict.fromkeys(station_ids))
        overlay = Overlay(
            kind=FaultType(request.kind.value),
            station_ids=ids,
            channel=request.channel,
            remaining={station_id: hours for station_id in ids},
            applied={station_id: 0 for station_id in ids},
            seed=self._next_seed,
        )
        self._next_seed += 1
        with self._lock:
            self._overlays.append(overlay)
            return overlay.status()

    def reset(self) -> None:
        with self._lock:
            self._overlays.clear()

    def status(self) -> DemoStatus:
        with self._lock:
            self._drop_spent()
            return DemoStatus(overlays=[overlay.status() for overlay in self._overlays])

    def apply(self, station_id: str, observation: Observation) -> tuple[Observation, FaultType | None]:
        injected: FaultType | None = None
        with self._lock:
            for overlay in self._overlays:
                updated, kind = self._apply_one(overlay, station_id, observation)
                if kind is not None:
                    observation = updated
                    injected = kind
            self._drop_spent()
        return observation, injected

    def _drop_spent(self) -> None:
        self._overlays = [overlay for overlay in self._overlays if overlay.active()]

    def _apply_one(
        self,
        overlay: Overlay,
        station_id: str,
        observation: Observation,
    ) -> tuple[Observation, FaultType | None]:
        remaining = overlay.remaining.get(station_id, 0)
        if remaining <= 0:
            return observation, None

        hour_index = overlay.applied[station_id]
        freeze_anchor = overlay.freeze_anchor.get(station_id)
        if (
            overlay.kind is FaultType.FREEZE
            and overlay.channel is not None
            and station_id not in overlay.freeze_anchor
        ):
            current = observation.get(overlay.channel)
            if current is not None:
                overlay.freeze_anchor[station_id] = current
                freeze_anchor = current

        rng = None
        if overlay.kind is FaultType.GENUINE_WEATHER:
            rng = default_rng(overlay.seed + 1_000_003 * hour_index)

        mutated = apply_live(
            overlay.kind,
            observation,
            overlay.channel,
            hour_index,
            rng=rng,
            freeze_anchor=freeze_anchor,
        )
        overlay.remaining[station_id] = remaining - 1
        overlay.applied[station_id] = hour_index + 1
        return mutated, overlay.kind


class StreamFilterController:
    """In-memory view/ingest sets. Empty view means the full catalog."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._station_ids: list[str] = []
        self._include_buddies = True

    def set(self, station_ids: list[str], include_buddies: bool) -> None:
        with self._lock:
            self._station_ids = list(dict.fromkeys(station_ids))
            self._include_buddies = include_buddies

    def snapshot(
        self,
        known_ids: list[str],
        buddy_map: dict[str, list[str]],
    ) -> StreamFilterStatus:
        with self._lock:
            view, ingest = resolve_view_and_ingest(
                self._station_ids,
                self._include_buddies,
                known_ids,
                buddy_map,
            )
            return StreamFilterStatus(
                view=view,
                ingest=ingest,
                include_buddies=self._include_buddies,
            )
