"""Fault-type heuristic, reason sentence, 7-day station health."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta

import pandas as pd

from .config import DEGRADED_MIN, DRIFT_BIAS, DRIFT_HOURS, FEATURES, FREEZE_HOURS, HEALTH_MAX_HOURS, HEALTHY_MIN
from .lstm_inference import _to_naive


def infer_fault_type(
    *,
    communication: bool,
    tier1_violations: list[str],
    window_df: pd.DataFrame | None,
    affected: list[str],
    observed: dict,
    predicted: dict | None,
    neighbors_agree: bool | None,
    drift_fired: bool = False,
) -> str | None:
    if communication:
        return "COMMUNICATION"
    if any(v.startswith("THERMO:") for v in tier1_violations):
        return "THERMO"
    if any(v.startswith("FREEZE:") for v in tier1_violations):
        return "FREEZE"
    if any(v.startswith("RANGE:") or v.startswith("STEP:") for v in tier1_violations):
        return "SPIKE"
    if drift_fired:
        return "DRIFT"
    if window_df is None or window_df.empty:
        return None
    feats = affected or list(FEATURES)
    tail = window_df.tail(FREEZE_HOURS)
    if len(tail) >= FREEZE_HOURS:
        for feat in feats:
            series = pd.to_numeric(tail[feat], errors="coerce")
            if series.notna().all() and series.nunique(dropna=True) == 1:
                return "FREEZE"
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
    if neighbors_agree:
        return "STORM"
    return None


def affected_from_contributions(contrib: dict | None, min_share: float = 0.40) -> list[str]:
    if not contrib:
        return []
    numeric = {k: float(v) for k, v in contrib.items() if isinstance(v, (int, float)) and v == v}
    if not numeric:
        return []
    picked = [k for k, v in numeric.items() if v >= min_share]
    if picked:
        return picked
    return [max(numeric, key=numeric.get)]


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
    corroborated: bool = False,
) -> str:
    if label == "PHYSICAL_FAULT":
        return "Tier 1 physical rule failed: " + "; ".join(tier1.get("violations") or [])
    if window_error and "INSUFFICIENT_WINDOW" in window_error:
        return window_error
    if label == "CLEAN" and corroborated:
        feat = (affected or ["temp"])[0]
        mix = (tier3.get("mix") or {}).get(feat)
        n = tier3.get("usable_count") or 0
        obs_v = observed.get(feat)
        bit = ""
        if obs_v is not None and mix is not None:
            bit = f"{feat} observed {obs_v:.2f}, neighbor mix {mix:.2f} (n={n}). "
        return (
            bit
            + "LSTM score above threshold, but neighbors agree and did not move themselves "
            "(no shared shock). Corroborated by neighbors; treated as clean."
        )
    if label == "CLEAN":
        return "Last-hour-weighted reconstruction within the frozen 2023 threshold."
    pred = predicted or {}
    feat = (affected or ["temp"])[0]
    obs_v = observed.get(feat)
    pred_v = pred.get(feat)
    bit = ""
    if obs_v is not None and pred_v is not None:
        bit = f"{feat} observed {obs_v:.2f} vs predicted {pred_v:.2f}. "
    mix = (tier3.get("mix") or {}).get(feat)
    n = tier3.get("usable_count") or 0
    if mix is not None:
        bit += f"Neighbor mix {mix:.2f} (n={n}). "
    if label == "GENUINE_WEATHER_EVENT":
        extra = ""
        if any(v.startswith(("STEP:", "RANGE:")) for v in (tier1.get("violations") or [])):
            extra = "Step/range fired but "
        return bit + extra + "neighbors agree on CW-IDW; treated as a genuine weather event."
    if label == "HARDWARE_ANOMALY":
        if fault_type == "DRIFT":
            drift = tier3.get("drift") if isinstance(tier3.get("drift"), dict) else {}
            hours = drift.get("hours")
            last = drift.get("last")
            extra = ""
            if hours and last is not None:
                extra = f" Residual vs neighbors {last:+.2f} over {hours} h."
            return bit + "Slow bias against the neighbour blend; treated as calibration drift." + extra
        return bit + "Neighbors disagree; treated as hardware anomaly."
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
        return {"index_7d": round(index, 4), "state": state, "window_hours": n}
