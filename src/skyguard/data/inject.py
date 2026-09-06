"""Pure fault-injection math. No I/O, no FastAPI."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from skyguard.schemas import Channel, FaultType

DEFAULT_STD = {
    Channel.TEMP_C: 2.0,
    Channel.PRES_HPA: 2.0,
    Channel.RHUM_PCT: 5.0,
}
DRIFT_SLOPE = 0.1


@dataclass(frozen=True)
class Observation:
    temp_c: float | None
    pres_hpa: float | None
    rhum_pct: float | None

    def get(self, channel: Channel) -> float | None:
        return getattr(self, channel.value)

    def set(self, channel: Channel, value: float | None) -> Observation:
        return replace(self, **{channel.value: value})


def default_rng(seed: int | None = None) -> np.random.Generator:
    return np.random.default_rng(seed)


def _as_channel(channel: Channel | str) -> Channel:
    return channel if isinstance(channel, Channel) else Channel(channel)


def _as_fault(kind: FaultType | str) -> FaultType:
    return kind if isinstance(kind, FaultType) else FaultType(kind)


def inject_spike(value: float, std_dev: float, rng: np.random.Generator | None = None) -> float:
    rng = rng or default_rng()
    sign = float(rng.choice([-1.0, 1.0]))
    return float(value + sign * rng.uniform(4.0, 8.0) * std_dev)


def inject_freeze(series: np.ndarray, start: int, duration: int = 12) -> np.ndarray:
    out = np.array(series, dtype=float, copy=True)
    stop = min(start + duration, len(out))
    out[start:stop] = out[start]
    return out


def inject_drift(
    series: np.ndarray,
    start: int,
    duration: int = 48,
    slope: float = DRIFT_SLOPE,
) -> np.ndarray:
    out = np.array(series, dtype=float, copy=True)
    stop = min(start + duration, len(out))
    for offset, idx in enumerate(range(start, stop)):
        out[idx] += slope * offset
    return out


def inject_comm_error() -> None:
    return None


def inject_storm(
    temp_c: float,
    pres_hpa: float,
    rhum_pct: float,
    rng: np.random.Generator | None = None,
) -> tuple[float, float, float]:
    rng = rng or default_rng()
    return (
        float(temp_c - rng.uniform(8.0, 15.0)),
        float(pres_hpa - rng.uniform(10.0, 25.0)),
        float(min(100.0, rhum_pct + rng.uniform(30.0, 50.0))),
    )


def apply_live(
    kind: FaultType | str,
    observation: Observation,
    channel: Channel | str | None,
    hour_index: int,
    std_dev: dict[Channel, float] | None = None,
    rng: np.random.Generator | None = None,
    freeze_anchor: float | None = None,
    slope: float = DRIFT_SLOPE,
) -> Observation:
    fault = _as_fault(kind)
    scales = std_dev or DEFAULT_STD
    rng = rng or default_rng()

    if fault is FaultType.COMM_ERROR:
        if channel is None:
            return Observation(None, None, None)
        return observation.set(_as_channel(channel), inject_comm_error())

    if fault is FaultType.GENUINE_WEATHER:
        if None in (observation.temp_c, observation.pres_hpa, observation.rhum_pct):
            return observation
        temp_c, pres_hpa, rhum_pct = inject_storm(
            observation.temp_c, observation.pres_hpa, observation.rhum_pct, rng
        )
        return Observation(temp_c, pres_hpa, rhum_pct)

    if channel is None:
        raise ValueError(f"{fault.value} requires a channel")
    target = _as_channel(channel)
    current = observation.get(target)
    if current is None:
        return observation

    if fault is FaultType.SPIKE:
        return observation.set(target, inject_spike(current, scales.get(target, DEFAULT_STD[target]), rng))
    if fault is FaultType.FREEZE:
        anchor = current if freeze_anchor is None else freeze_anchor
        return observation.set(target, float(anchor))
    if fault is FaultType.DRIFT:
        return observation.set(target, float(current) + slope * hour_index)
    raise ValueError(f"Unsupported live fault: {fault}")
