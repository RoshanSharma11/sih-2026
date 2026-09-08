"""Tier 3 — spatial IDW buddy check."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from .config import (
    AGREE_PRES,
    AGREE_RHUM,
    AGREE_TEMP,
    BUDDY_TIME_TOLERANCE_HOURS,
    FEATURES,
    IDW_POWER,
    MIN_USABLE_BUDDIES,
)
from .lstm_inference import _to_naive


def _value_at(
    window: list[dict],
    timestamp: datetime,
    feature: str,
    tolerance_hours: float = BUDDY_TIME_TOLERANCE_HOURS,
):
    if not window:
        return None
    target = _to_naive(timestamp)
    best = None
    best_dt = None
    for raw in window:
        row = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        ts = _to_naive(row["timestamp"])
        dt_h = abs((ts - target).total_seconds()) / 3600.0
        if dt_h > tolerance_hours:
            continue
        val = row.get(feature)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        if best_dt is None or dt_h < best_dt:
            best_dt = dt_h
            best = float(val)
    return best


def idw_estimate(values: list[float], distances: list[float]) -> float | None:
    if not values:
        return None
    weights = []
    for d in distances:
        d = max(float(d), 1e-3)
        weights.append(1.0 / (d ** IDW_POWER))
    wsum = sum(weights)
    if wsum <= 0:
        return None
    return float(sum(v * w for v, w in zip(values, weights)) / wsum)


def evaluate_tier3(
    timestamp: datetime,
    observed: dict,
    buddies: list[dict],
    affected: list[str],
    isolate: bool,
) -> dict:
    empty = {
        "performed": False,
        "buddy_ids": [],
        "idw_estimate": {f: None for f in FEATURES},
        "residual": {f: None for f in FEATURES},
        "neighbors_agree": None,
        "usable_count": 0,
        "reason_skip": None,
    }

    if isolate:
        empty["reason_skip"] = "isolate_station"
        return empty

    usable = []
    for buddy in buddies or []:
        bid = str(buddy.get("station_id", ""))
        dist = buddy.get("distance_km")
        window = buddy.get("window") or []
        sample = {}
        ok = True
        for feat in FEATURES:
            sample[feat] = _value_at(window, timestamp, feat)
            if sample[feat] is None:
                ok = False
        if not ok or dist is None:
            continue
        try:
            dkm = float(dist)
        except (TypeError, ValueError):
            continue
        usable.append({"station_id": bid, "distance_km": dkm, **sample})

    if len(usable) < MIN_USABLE_BUDDIES:
        empty["usable_count"] = len(usable)
        empty["buddy_ids"] = [u["station_id"] for u in usable]
        empty["reason_skip"] = "fewer_than_2_usable_buddies"
        return empty

    estimate = {}
    residual = {}
    check_feats = affected if affected else list(FEATURES)
    agree = True
    bands = {"temp": AGREE_TEMP, "rhum": AGREE_RHUM, "pres": AGREE_PRES}

    for feat in FEATURES:
        vals = [u[feat] for u in usable]
        dists = [u["distance_km"] for u in usable]
        est = idw_estimate(vals, dists)
        estimate[feat] = est
        obs = observed.get(feat)
        if est is None or obs is None:
            residual[feat] = None
            if feat in check_feats:
                agree = False
            continue
        residual[feat] = float(obs - est)
        if feat in check_feats and abs(residual[feat]) >= bands[feat]:
            agree = False

    return {
        "performed": True,
        "buddy_ids": [u["station_id"] for u in usable],
        "idw_estimate": estimate,
        "residual": residual,
        "neighbors_agree": agree,
        "usable_count": len(usable),
        "reason_skip": None,
    }
