"""Tier 3 — correlation-weighted IDW (CW-IDW)."""

from __future__ import annotations

from datetime import datetime, timedelta

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
    SHOCK_BASELINE_FRACTION,
    SHOCK_BASELINE_MIN_HOURS,
    SHOCK_STEP_FRACTION,
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


AGREE_BANDS = {"temp": AGREE_TEMP, "rhum": AGREE_RHUM, "pres": AGREE_PRES}


def _feature_mean(window: list, end: datetime, feature: str, hours: int = WINDOW_HOURS) -> float | None:
    """Mean of a buddy's last `hours` values strictly before `end`. None under SHOCK_BASELINE_MIN_HOURS."""
    target = _to_naive(end)
    vals = []
    for raw in window or []:
        row = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        ts = _to_naive(row["timestamp"])
        if ts >= target or (target - ts).total_seconds() > hours * 3600.0:
            continue
        v = row.get(feature)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        vals.append(float(v))
    if len(vals) < SHOCK_BASELINE_MIN_HOURS:
        return None
    return float(np.mean(vals))


def shared_shock(
    timestamp: datetime,
    usable: list[dict],
    buddies: list[dict],
    wsum: float,
    check_feats: list[str],
) -> dict:
    """Did the neighbour blend itself move on the checked channels?

    Returns `blend_shift` (blend now − blend one hour ago), `blend_baseline_delta`
    (blend now − mean of the buddies' previous 24 h) and `neighbor_shock`: True when
    either exceeds its fraction of the agree band on any checked channel, False when
    both are available and calm, None when the buddies' history cannot say.
    """
    by_id = {str(b.get("station_id", "")): b.get("window") or [] for b in buddies or []}
    shift: dict[str, float | None] = {}
    baseline: dict[str, float | None] = {}
    verdicts: list[bool] = []
    for feat in FEATURES:
        prev_parts = []
        base_parts = []
        for u in usable:
            window = by_id.get(u["station_id"], [])
            prev = _value_at(window, timestamp - timedelta(hours=1), feat, tolerance_hours=0.5)
            base = _feature_mean(window, timestamp, feat)
            prev_parts.append(None if prev is None else prev * u["w"])
            base_parts.append(None if base is None else base * u["w"])
        now = sum(u[feat] * u["w"] for u in usable) / wsum
        shift[feat] = None if any(p is None for p in prev_parts) or wsum <= 0 else float(now - sum(prev_parts) / wsum)
        baseline[feat] = None if any(b is None for b in base_parts) or wsum <= 0 else float(now - sum(base_parts) / wsum)
        if feat not in check_feats:
            continue
        band = AGREE_BANDS[feat]
        step_hit = shift[feat] is not None and abs(shift[feat]) >= SHOCK_STEP_FRACTION * band
        base_hit = baseline[feat] is not None and abs(baseline[feat]) >= SHOCK_BASELINE_FRACTION * band
        if step_hit or base_hit:
            verdicts.append(True)
        elif shift[feat] is not None or baseline[feat] is not None:
            verdicts.append(False)
    shock: bool | None
    if any(verdicts):
        shock = True
    elif verdicts:
        shock = False
    else:
        shock = None
    return {"neighbor_shock": shock, "blend_shift": shift, "blend_baseline_delta": baseline}


def neighbor_estimate(
    timestamp: datetime,
    observed: dict,
    buddies: list[dict],
    primary_window: list | None = None,
) -> dict:
    """CW-IDW blend of the usable buddies at `timestamp` and the primary's residual against it.

    A buddy is usable when it has all three channels within BUDDY_TIME_TOLERANCE_HOURS and a
    distance. Returns `usable` (with weights), `wsum`, `corr`, `mix` and `residual`
    (observed − mix, None where either side is missing). `mix`/`residual` are all-None when
    fewer than MIN_USABLE_BUDDIES are usable. Shared by Tier 3 and the drift monitor.
    """
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

    mix: dict[str, float | None] = {f: None for f in FEATURES}
    residual: dict[str, float | None] = {f: None for f in FEATURES}
    wsum = sum(u["w"] for u in usable)
    if len(usable) >= MIN_USABLE_BUDDIES and wsum > 0:
        for feat in FEATURES:
            est = sum(u[feat] * u["w"] for u in usable) / wsum
            mix[feat] = float(est)
            obs = observed.get(feat)
            if obs is not None and not (isinstance(obs, float) and pd.isna(obs)):
                residual[feat] = float(obs - est)
    return {"usable": usable, "wsum": wsum, "corr": corrs, "mix": mix, "residual": residual}


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
        "neighbor_shock": None,
        "blend_shift": {f: None for f in FEATURES},
        "blend_baseline_delta": {f: None for f in FEATURES},
        "usable_count": 0,
        "reason_skip": None,
    }
    if isolate:
        empty["reason_skip"] = "isolate_station"
        return empty

    est = neighbor_estimate(timestamp, observed, buddies, primary_window)
    usable, corrs = est["usable"], est["corr"]
    if len(usable) < MIN_USABLE_BUDDIES:
        empty["usable_count"] = len(usable)
        empty["buddy_ids"] = [u["station_id"] for u in usable]
        empty["corr"] = corrs
        empty["reason_skip"] = "fewer_than_2_usable_buddies"
        return empty

    wsum, mix, residual = est["wsum"], est["mix"], est["residual"]
    check_feats = affected if affected else list(FEATURES)
    agree = True
    bands = AGREE_BANDS
    for feat in check_feats:
        if residual.get(feat) is None or abs(residual[feat]) >= bands[feat]:
            agree = False

    shock = shared_shock(timestamp, usable, buddies or [], wsum, check_feats) if wsum > 0 else {
        "neighbor_shock": None,
        "blend_shift": {f: None for f in FEATURES},
        "blend_baseline_delta": {f: None for f in FEATURES},
    }
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
        **shock,
    }


def math_weight(corr: float, distance_km: float) -> float:
    d = max(float(distance_km), 1e-3)
    return float(np.exp(corr / CORR_TAU) / (d ** IDW_POWER))
