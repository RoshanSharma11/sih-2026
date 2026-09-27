"""Tier 3 — correlation-weighted IDW (CW-IDW)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from .config import (
    AGREE_PRES,
    AGREE_RHUM,
    AGREE_TEMP,
    BUDDY_TIME_TOLERANCE_HOURS,
    CORR_TAU,
    FEATURES,
    IDW_POWER,
    MIN_USABLE_BUDDIES,
    WINDOW_HOURS,
)
from .lstm_inference import _to_naive


def _value_at(window: list, timestamp: datetime, feature: str, tolerance_hours: float = BUDDY_TIME_TOLERANCE_HOURS):
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


def _temp_series(window: list, end: datetime) -> np.ndarray | None:
    rows = []
    for raw in window or []:
        row = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        t = row.get("temp")
        if t is None or (isinstance(t, float) and pd.isna(t)):
            continue
        rows.append((_to_naive(row["timestamp"]), float(t)))
    if not rows:
        return None
    rows.sort(key=lambda x: x[0])
    target = _to_naive(end)
    keep = [(ts, v) for ts, v in rows if ts <= target][-WINDOW_HOURS:]
    if len(keep) < 8:
        return None
    return np.array([v for _, v in keep], dtype=np.float64)


def _corr(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None:
        return 0.0
    n = min(len(a), len(b))
    if n < 8:
        return 0.0
    x, y = a[-n:], b[-n:]
    if float(x.std()) < 1e-6 or float(y.std()) < 1e-6:
        return 0.0
    c = float(np.corrcoef(x, y)[0, 1])
    if c != c:
        return 0.0
    return max(-1.0, min(1.0, c))


def evaluate_tier3(
    timestamp: datetime,
    observed: dict,
    buddies: list[dict],
    affected: list[str],
    isolate: bool,
    primary_window: list | None = None,
) -> dict:
    empty = {
        "performed": False,
        "method": "cw_idw",
        "buddy_ids": [],
        "mix": {f: None for f in FEATURES},
        "idw_estimate": {f: None for f in FEATURES},
        "residual": {f: None for f in FEATURES},
        "corr": {},
        "neighbors_agree": None,
        "usable_count": 0,
        "reason_skip": None,
    }
    if isolate:
        empty["reason_skip"] = "isolate_station"
        return empty

    prim_t = _temp_series(primary_window or [], timestamp)
    usable = []
    corrs = {}
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
        c = _corr(prim_t, _temp_series(window, timestamp))
        corrs[bid] = round(c, 4)
        w = math_weight(c, dkm)
        usable.append({"station_id": bid, "distance_km": dkm, "w": w, **sample})

    if len(usable) < MIN_USABLE_BUDDIES:
        empty["usable_count"] = len(usable)
        empty["buddy_ids"] = [u["station_id"] for u in usable]
        empty["corr"] = corrs
        empty["reason_skip"] = "fewer_than_2_usable_buddies"
        return empty

    wsum = sum(u["w"] for u in usable)
    mix = {}
    residual = {}
    check_feats = affected if affected else list(FEATURES)
    agree = True
    bands = {"temp": AGREE_TEMP, "rhum": AGREE_RHUM, "pres": AGREE_PRES}
    for feat in FEATURES:
        est = sum(u[feat] * u["w"] for u in usable) / wsum if wsum > 0 else None
        mix[feat] = None if est is None else float(est)
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
        "method": "cw_idw",
        "buddy_ids": [u["station_id"] for u in usable],
        "mix": mix,
        "idw_estimate": mix,
        "residual": residual,
        "corr": corrs,
        "neighbors_agree": agree,
        "usable_count": len(usable),
        "reason_skip": None,
    }


def math_weight(corr: float, distance_km: float) -> float:
    d = max(float(distance_km), 1e-3)
    return float(np.exp(corr / CORR_TAU) / (d ** IDW_POWER))
