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
    PRES_MAX,
    PRES_MIN,
    RHUM_MAX,
    RHUM_MIN,
    TEMP_MAX,
    TEMP_MIN,
)
from .lstm_inference import _to_naive

FEATURE_NAME = {
    "temp": "temperature",
    "rhum": "humidity",
    "pres": "pressure",
}
FEATURE_UNIT = {
    "temp": "°C",
    "rhum": "%",
    "pres": " hPa",
}
FAULT_CLOSE = {
    "SPIKE": "Treated as a hardware spike.",
    "FREEZE": "Treated as a frozen sensor.",
    "DRIFT": "Treated as slow calibration drift.",
    "COMMUNICATION": "Treated as a communication or sensor gap.",
}
SKIP_WHY = {
    "isolate_station": "this station has fewer than two neighbors on the buddy graph",
    "fewer_than_2_usable_buddies": "fewer than two neighbors reported the same hour",
    "tier1_failed": "a physical-range check already failed",
    "lstm_not_run": "the 24-hour reconstruction window is not ready",
    "not_required": "the reconstruction looked normal",
    "INSUFFICIENT_WINDOW": "the 24-hour reconstruction window is still filling",
}


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
    feat = (affected or ["temp"])[0]
    compare = _compare_bit(feat, observed, predicted)
    close = FAULT_CLOSE.get(fault_type or "", "Treated as a hardware anomaly.")

    if label == "PHYSICAL_FAULT":
        detail = _plain_violations(tier1.get("violations") or [])
        extra = f" {detail}." if detail else ""
        return f"A physical check failed.{extra} {close}".strip()
    if window_error and "INSUFFICIENT_WINDOW" in window_error:
        return (
            "Not enough recent hours to reconstruct this station yet. "
            "Waiting for a 24-hour window before calling hardware or weather."
        )
    if label == "CLEAN":
        if compare:
            return (
                f"{compare} Reconstruction error is within the normal band. "
                "This hour is trustworthy."
            )
        return "Reconstruction error is within the normal band. This hour is trustworthy."
    if label == "GENUINE_WEATHER_EVENT":
        n = int(tier3.get("usable_count") or 0)
        neighbor = (
            f"{n} nearby stations agree"
            if n
            else "Nearby stations agree"
        )
        prefix = f"{compare} " if compare else ""
        return (
            f"{prefix}{neighbor} on the buddy check, so this is treated as genuine weather, "
            "not a broken sensor."
        )
    if label == "HARDWARE_ANOMALY":
        residual = (tier3.get("residual") or {}).get(feat)
        extra = ""
        if isinstance(residual, (int, float)):
            unit = FEATURE_UNIT.get(feat, "")
            extra = f" Neighbor residual {residual:+.1f}{unit}."
        prefix = f"{compare} " if compare else ""
        return f"{prefix}Nearby stations did not agree.{extra} {close}".strip()
    if label == "UNCONFIRMED_ANOMALY":
        skip = tier3.get("reason_skip") or "tier3_not_performed"
        why = SKIP_WHY.get(skip, skip.replace("_", " "))
        prefix = f"{compare} " if compare else ""
        return (
            f"{prefix}The reconstruction looked unusual, but the spatial check was skipped "
            f"({why}). Marked unconfirmed rather than calling it hardware."
        )
    prefix = f"{compare} " if compare else ""
    return f"{prefix}{label}."


def _compare_bit(feat: str, observed: dict, predicted: dict | None) -> str:
    obs_v = observed.get(feat)
    pred_v = (predicted or {}).get(feat)
    name = FEATURE_NAME.get(feat, feat)
    unit = FEATURE_UNIT.get(feat, "")
    if obs_v is None:
        return ""
    if pred_v is None:
        return f"{name.capitalize()} {obs_v:.1f}{unit}."
    delta = obs_v - pred_v
    direction = "above" if delta > 0 else "below"
    return (
        f"{name.capitalize()} {obs_v:.1f}{unit} is {abs(delta):.1f}{unit} {direction} "
        f"the predicted {pred_v:.1f}{unit}."
    )


def _plain_violations(violations: list[str]) -> str:
    parts: list[str] = []
    bounds = {
        "temp": (TEMP_MIN, TEMP_MAX, "°C"),
        "rhum": (RHUM_MIN, RHUM_MAX, "%"),
        "pres": (PRES_MIN, PRES_MAX, " hPa"),
    }
    for raw in violations:
        if raw.startswith("COMMUNICATION:"):
            names = [
                FEATURE_NAME.get(part, part)
                for part in raw.split(":", 1)[1].split(",")
                if part
            ]
            joined = " and ".join(names) if names else "a channel"
            parts.append(f"{joined} was missing")
            continue
        if raw.startswith("RANGE:"):
            body = raw.split(":", 1)[1]
            feat = body.split("=", 1)[0]
            name = FEATURE_NAME.get(feat, feat)
            low, high, unit = bounds.get(feat, (None, None, ""))
            if low is not None:
                parts.append(f"{name} is outside the valid range ({low:g} to {high:g}{unit})")
            else:
                parts.append(body)
            continue
        if raw.startswith("STEP:"):
            if "dT" in raw:
                parts.append("temperature jumped more than 10 °C in one hour")
            elif "dRH" in raw:
                parts.append("humidity jumped more than 30 points in one hour")
            elif "dP" in raw:
                parts.append("pressure jumped more than 10 hPa in one hour")
            else:
                parts.append("a channel jumped faster than the physical step limit")
            continue
        parts.append(raw)
    return "; ".join(parts)


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
