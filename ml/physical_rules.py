"""Tier 1 — hard range and step rules."""

from __future__ import annotations

from .config import (
    PRES_MAX,
    PRES_MIN,
    RHUM_MAX,
    RHUM_MIN,
    STEP_PRES,
    STEP_RHUM,
    STEP_TEMP,
    TEMP_MAX,
    TEMP_MIN,
)


def _ok(value) -> bool:
    return value is not None and value == value  # not None, not NaN


def evaluate_tier1(
    temp,
    rhum,
    pres,
    prev_temp=None,
    prev_rhum=None,
    prev_pres=None,
) -> dict:
    violations: list[str] = []

    missing = [name for name, v in (("temp", temp), ("rhum", rhum), ("pres", pres)) if not _ok(v)]
    if missing:
        violations.append("COMMUNICATION:" + ",".join(missing))
        return {
            "passed": False,
            "violations": violations,
            "communication": True,
        }

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

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "communication": False,
    }
