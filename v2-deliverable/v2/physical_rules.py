"""Tier 1 — range, step, missing, freeze, Magnus Td > T."""

from __future__ import annotations

import math

import pandas as pd

from .config import (
    FEATURES,
    FREEZE_EPS_BY_FEATURE,
    FREEZE_HOURS,
    FREEZE_HOURS_MULTI,
    MAGNUS_A,
    MAGNUS_B,
    PRES_MAX,
    PRES_MIN,
    RHUM_MAX,
    RHUM_MIN,
    STEP_PRES,
    STEP_RHUM,
    STEP_TEMP,
    TEMP_MAX,
    TEMP_MIN,
    THERMO_EPS_C,
)


def _ok(value) -> bool:
    return value is not None and value == value


def magnus_dewpoint_c(temp_c: float, rhum: float) -> float:
    rh = min(max(float(rhum), 1e-3), 100.0)
    t = float(temp_c)
    den_t = MAGNUS_B + t
    if abs(den_t) < 1e-6:
        den_t = 1e-6
    alpha = MAGNUS_A * t / den_t + math.log(rh / 100.0)
    den = MAGNUS_A - alpha
    if abs(den) < 1e-6:
        den = 1e-6
    return MAGNUS_B * alpha / den


def _channel_frozen(series: pd.Series, eps: float) -> bool:
    s = pd.to_numeric(series, errors="coerce")
    return bool(len(s) > 0 and s.notna().all() and (float(s.max()) - float(s.min())) <= eps)


def freeze_violations(window_df: pd.DataFrame | None) -> list[str]:
    """Stuck sensor, not a night of integer-degree calm.

    Two channels flat for 6 h, or one channel flat for 12 h.
    """
    if window_df is None or len(window_df) < FREEZE_HOURS_MULTI:
        return []
    frozen_short = []
    tail_short = window_df.tail(FREEZE_HOURS_MULTI)
    for feat in FEATURES:
        if _channel_frozen(tail_short[feat], FREEZE_EPS_BY_FEATURE[feat]):
            frozen_short.append(feat)
    if len(frozen_short) >= 2:
        return [f"FREEZE:{','.join(frozen_short)} constant {FREEZE_HOURS_MULTI}h"]
    if len(window_df) < FREEZE_HOURS:
        return []
    tail_long = window_df.tail(FREEZE_HOURS)
    for feat in FEATURES:
        if _channel_frozen(tail_long[feat], FREEZE_EPS_BY_FEATURE[feat]):
            return [f"FREEZE:{feat} constant {FREEZE_HOURS}h"]
    return []


def is_soft_t1(violations: list[str], communication: bool) -> bool:
    """STEP/RANGE can be a neighborhood storm; freeze/comms/thermo cannot."""
    if communication or not violations:
        return False
    if any(v.startswith(("THERMO:", "FREEZE:", "COMMUNICATION:")) for v in violations):
        return False
    return all(v.startswith(("STEP:", "RANGE:")) for v in violations)


def channels_from_violations(violations: list[str]) -> list[str]:
    found: list[str] = []
    for v in violations or []:
        low = v.lower()
        if "temp" in low or "dt" in low:
            found.append("temp")
        if "rhum" in low or "drh" in low:
            found.append("rhum")
        if "pres" in low or "dp" in low:
            found.append("pres")
    out = []
    for feat in FEATURES:
        if feat in found:
            out.append(feat)
    return out


def evaluate_tier1(
    temp,
    rhum,
    pres,
    prev_temp=None,
    prev_rhum=None,
    prev_pres=None,
    window_df: pd.DataFrame | None = None,
) -> dict:
    violations: list[str] = []
    thermo = {"dewpoint_c": None, "td_minus_t": None, "passed": True}

    missing = [name for name, v in (("temp", temp), ("rhum", rhum), ("pres", pres)) if not _ok(v)]
    if missing:
        return {
            "passed": False,
            "violations": ["COMMUNICATION:" + ",".join(missing)],
            "communication": True,
            "thermo": thermo,
            "soft": False,
        }

    td = magnus_dewpoint_c(temp, rhum)
    td_minus_t = td - float(temp)
    thermo = {"dewpoint_c": round(td, 3), "td_minus_t": round(td_minus_t, 3), "passed": td_minus_t <= THERMO_EPS_C}
    if not thermo["passed"]:
        violations.append(f"THERMO:Td>T td={td:.2f} t={temp:.2f}")

    if temp < TEMP_MIN or temp > TEMP_MAX:
        violations.append(f"RANGE:temp={temp:.2f} not in [{TEMP_MIN}, {TEMP_MAX}]")
    if rhum < RHUM_MIN or rhum > RHUM_MAX:
        violations.append(f"RANGE:rhum={rhum:.2f} not in [{RHUM_MIN}, {RHUM_MAX}]")
    if pres < PRES_MIN or pres > PRES_MAX:
        violations.append(f"RANGE:pres={pres:.2f} not in [{PRES_MIN}, {PRES_MAX}]")

    if _ok(prev_temp) and abs(temp - prev_temp) >= STEP_TEMP:
        violations.append(f"STEP:|dT|={abs(temp - prev_temp):.2f}>={STEP_TEMP}")
    if _ok(prev_rhum) and abs(rhum - prev_rhum) >= STEP_RHUM:
        violations.append(f"STEP:|dRH|={abs(rhum - prev_rhum):.2f}>={STEP_RHUM}")
    if _ok(prev_pres) and abs(pres - prev_pres) >= STEP_PRES:
        violations.append(f"STEP:|dP|={abs(pres - prev_pres):.2f}>={STEP_PRES}")

    violations.extend(freeze_violations(window_df))

    communication = False
    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "communication": communication,
        "thermo": thermo,
        "soft": is_soft_t1(violations, communication),
    }
