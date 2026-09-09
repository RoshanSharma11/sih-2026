"""Fault-type heuristic, reason sentence, 7-day station health."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta

import pandas as pd

from .config import (
    DEGRADED_MIN,
    DRIFT_BIAS,
    DRIFT_HOURS,
    FEATURES,
    FREEZE_HOURS,
    HEALTH_MAX_HOURS,
    HEALTHY_MIN,
)
from .lstm_inference import _to_naive


def infer_fault_type(
    *,
    communication: bool,
    tier1_violations: list[str],
    window_df: pd.DataFrame | None,
    affected: list[str],
    observed: dict,
    predicted: dict | None,
) -> str | None:
    if communication:
        return "COMMUNICATION"
    if any(v.startswith("RANGE:") or v.startswith("STEP:") for v in tier1_violations):
        return "SPIKE"
    if window_df is None or window_df.empty:
        return None

    feats = affected or list(FEATURES)
    # Freeze: last N hours identical on a flagged channel
    tail = window_df.tail(FREEZE_HOURS)
    if len(tail) >= FREEZE_HOURS:
        for feat in feats:
            series = pd.to_numeric(tail[feat], errors="coerce")
            if series.notna().all() and series.nunique(dropna=True) == 1:
                return "FREEZE"

    # Drift: reconstructed last step vs a slowly shifting observed mean
    if predicted:
        hist = window_df.tail(DRIFT_HOURS)
        if len(hist) >= DRIFT_HOURS:
            for feat in feats:
                obs = observed.get(feat)
                pred = predicted.get(feat)
                if obs is None or pred is None:
                    continue
                mean_obs = float(pd.to_numeric(hist[feat], errors="coerce").mean())
                if abs(obs - pred) >= DRIFT_BIAS and abs(obs - mean_obs) < abs(obs - pred) * 0.5:
                    return "DRIFT"

    if any(v.startswith("STEP:") for v in tier1_violations):
        return "SPIKE"
    return None


def affected_from_contributions(contrib: dict | None, min_share: float = 0.40) -> list[str]:
    if not contrib:
        return []
    numeric = {
        k: float(v)
        for k, v in contrib.items()
        if isinstance(v, (int, float)) and v == v
    }
    if not numeric:
        return []
    picked = [k for k, v in numeric.items() if v >= min_share]
    if picked:
        return picked
    best = max(numeric, key=numeric.get)
    return [best]


def build_reason(
    *,
    label: str,
    fault_type: str | None,
    observed: dict,
    predicted: dict | None,
    affected: list[str],
    tier1: dict,
    tier2: dict,
    tier3: dict,
    window_error: str | None,
) -> str:
    if label == "PHYSICAL_FAULT":
        return "Tier 1 physical rule failed: " + "; ".join(tier1.get("violations") or [])
    if window_error and "INSUFFICIENT_WINDOW" in window_error:
        return window_error
    if label == "CLEAN":
        return "Reconstruction error within the normal threshold."
    pred = predicted or {}
    feat = (affected or ["temp"])[0]
    obs_v = observed.get(feat)
    pred_v = pred.get(feat)
    bit = ""
    if obs_v is not None and pred_v is not None:
        bit = f"{feat} observed {obs_v:.2f} vs predicted {pred_v:.2f}. "
    if label == "GENUINE_WEATHER_EVENT":
        return bit + "Neighbors agree on IDW; treated as a genuine weather event."
    if label == "HARDWARE_ANOMALY":
        res = (tier3.get("residual") or {}).get(feat)
        extra = f" IDW residual {res:.2f}." if isinstance(res, (int, float)) else ""
        return bit + "Neighbors disagree;" + extra + " treated as hardware anomaly."
    if label == "UNCONFIRMED_ANOMALY":
        skip = tier3.get("reason_skip") or "tier3_not_performed"
        return bit + f"LSTM flagged unusual behavior; spatial check skipped ({skip})."
    return bit + label


class HealthTracker:
    def __init__(self, max_hours: int = HEALTH_MAX_HOURS):
        self.max_hours = max_hours
        self._events: dict[str, deque] = defaultdict(deque)

    def update(self, station_id: str, timestamp: datetime, flagged: bool) -> dict:
        ts = _to_naive(timestamp)
        q = self._events[str(station_id)]
        q.append((ts, bool(flagged)))
        cutoff = ts - timedelta(hours=self.max_hours)
        while q and q[0][0] < cutoff:
            q.popleft()
        n = len(q)
        flagged_n = sum(1 for _, f in q if f)
        index = 1.0 - (flagged_n / n) if n else 1.0
        if index >= HEALTHY_MIN:
            state = "HEALTHY"
        elif index >= DEGRADED_MIN:
            state = "DEGRADED"
        else:
            state = "CRITICAL"
        return {
            "index_7d": round(index, 4),
            "state": state,
            "window_hours": n,
        }
