"""Slow calibration drift from the residual against the CW-IDW neighbour blend.

The LSTM autoencoder reconstructs a slow bias, so last-hour score stays under the frozen
p99 and `infer_fault_type`'s 12-hour heuristic never sees an anomalous hour. This monitor
does not use the AE. For each hour in the primary window it asks the same blend Tier 3
uses, then runs a clipped two-sided CUSUM on `observed − mix`. A genuine storm keeps the
residual small (neighbours moved too). A spike is clipped to 1.5× the agree band, which
is below the decision threshold. No weights are updated.
"""

from __future__ import annotations

from datetime import datetime

from .buddy_check import AGREE_BANDS, neighbor_estimate
from .config import (
    DRIFT_CLIP_FRACTION,
    DRIFT_CUSUM_H_FRACTION,
    DRIFT_CUSUM_K_FRACTION,
    DRIFT_LAST_FRACTION,
    DRIFT_MIN_HOURS,
    FEATURES,
    MIN_USABLE_BUDDIES,
)
from .lstm_inference import _to_naive


def _obs_at(window: list, timestamp: datetime) -> dict | None:
    target = _to_naive(timestamp)
    best = None
    best_dt = None
    for raw in window or []:
        row = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        ts = _to_naive(row["timestamp"])
        dt = abs((ts - target).total_seconds())
        if dt > 90:
            continue
        if best_dt is None or dt < best_dt:
            best_dt = dt
            best = {
                "temp": row.get("temp"),
                "rhum": row.get("rhum"),
                "pres": row.get("pres"),
                "timestamp": ts,
            }
    return best


def _hour_stamps(window: list, end: datetime) -> list[datetime]:
    target = _to_naive(end)
    stamps = []
    seen: set[datetime] = set()
    for raw in window or []:
        row = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        ts = _to_naive(row["timestamp"])
        if ts > target:
            continue
        key = ts.replace(minute=0, second=0, microsecond=0)
        if key in seen:
            continue
        seen.add(key)
        stamps.append(key)
    stamps.sort()
    return stamps


def residual_history(
    timestamp: datetime,
    primary_window: list,
    buddies: list[dict],
) -> dict[str, list[float]]:
    """Per-channel residual series, oldest → newest, skipping hours with no blend."""
    series: dict[str, list[float]] = {feat: [] for feat in FEATURES}
    for ts in _hour_stamps(primary_window, timestamp):
        observed = _obs_at(primary_window, ts)
        if observed is None:
            continue
        est = neighbor_estimate(ts, observed, buddies, primary_window)
        if sum(1 for u in est["usable"]) < MIN_USABLE_BUDDIES:
            continue
        for feat in FEATURES:
            value = est["residual"].get(feat)
            if value is not None:
                series[feat].append(float(value))
    return series


def _cusum_peak(values: list[float], k: float, clip: float) -> float:
    sp = sm = 0.0
    peak = 0.0
    for raw in values:
        rc = max(-clip, min(clip, raw))
        sp = max(0.0, sp + rc - k)
        sm = max(0.0, sm - rc - k)
        peak = max(peak, sp, sm)
    return peak


def detect_drift(
    timestamp: datetime,
    primary_window: list,
    buddies: list[dict],
) -> dict:
    """CUSUM of the neighbour residual. `fired` is True when any channel crosses h.

    Returns the loudest channel, its last residual, CUSUM peak, hours used, and the
    agree-band fractions that produced k / h / clip. Empty / isolate windows do not fire.
    """
    empty = {
        "fired": False,
        "channel": None,
        "hours": 0,
        "last": None,
        "cusum": None,
        "k": None,
        "h": None,
    }
    if not buddies or not primary_window:
        return empty
    history = residual_history(timestamp, primary_window, buddies)
    best: dict | None = None
    for feat in FEATURES:
        values = history.get(feat) or []
        n = len(values)
        if n < DRIFT_MIN_HOURS:
            continue
        band = AGREE_BANDS[feat]
        k = DRIFT_CUSUM_K_FRACTION * band
        h = DRIFT_CUSUM_H_FRACTION * band
        clip = DRIFT_CLIP_FRACTION * band
        peak = _cusum_peak(values, k, clip)
        last = values[-1]
        row = {
            "fired": peak >= h and abs(last) >= DRIFT_LAST_FRACTION * band,
            "channel": feat,
            "hours": n,
            "last": round(last, 4),
            "cusum": round(peak, 4),
            "k": round(k, 4),
            "h": round(h, 4),
        }
        if best is None or row["cusum"] > (best["cusum"] or 0):
            best = row
    return best if best is not None else empty
