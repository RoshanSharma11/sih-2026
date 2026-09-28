"""Tier 3 shared-shock rule: agreeing neighbours must have moved for 'weather'."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "v2-deliverable"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2.buddy_check import evaluate_tier3, shared_shock  # noqa: E402
from v2.config import AGREE_TEMP, SHOCK_BASELINE_FRACTION, SHOCK_STEP_FRACTION  # noqa: E402

T0 = datetime(2024, 7, 1, 12)


def _window(base: float, last_shift: float = 0.0, hours: int = 25, ramp: float = 0.0) -> list[dict]:
    rows = []
    for i in range(hours):
        ts = T0 - timedelta(hours=hours - 1 - i)
        value = base + ramp * i + (last_shift if i == hours - 1 else 0.0)
        rows.append({"timestamp": ts, "temp": value, "rhum": 70.0, "pres": 1010.0})
    return rows


def _buddies(last_shift: float = 0.0, hours: int = 25, ramp: float = 0.0) -> list[dict]:
    return [
        {"station_id": "A", "distance_km": 5.0, "window": _window(30.0, last_shift, hours, ramp)},
        {"station_id": "B", "distance_km": 8.0, "window": _window(30.5, last_shift, hours, ramp)},
    ]


def _t3(observed_temp: float, buddies: list[dict]) -> dict:
    observed = {"temp": observed_temp, "rhum": 70.0, "pres": 1010.0}
    return evaluate_tier3(T0, observed, buddies, ["temp"], isolate=False, primary_window=_window(30.2))


def test_calm_agreeing_neighbours_are_not_a_shock() -> None:
    out = _t3(30.4, _buddies())
    assert out["performed"] and out["neighbors_agree"] is True
    assert out["neighbor_shock"] is False
    assert abs(out["blend_shift"]["temp"]) < 1e-9
    assert abs(out["blend_baseline_delta"]["temp"]) < 1e-9


def test_neighbours_that_jump_together_are_a_shock() -> None:
    drop = -(SHOCK_STEP_FRACTION * AGREE_TEMP + 0.5)
    out = _t3(30.2 + drop, _buddies(last_shift=drop))
    assert out["neighbors_agree"] is True
    assert out["neighbor_shock"] is True
    assert out["blend_shift"]["temp"] < -SHOCK_STEP_FRACTION * AGREE_TEMP


def test_slow_shared_departure_from_baseline_is_a_shock() -> None:
    # neighbours climb 0.4 °C/h for a day: no single-hour step (< 3 °C), but the blend sits
    # 5 °C above its own 24 h mean
    out = _t3(40.0, _buddies(ramp=0.4))
    assert out["neighbors_agree"] is True
    assert out["blend_baseline_delta"]["temp"] >= SHOCK_BASELINE_FRACTION * AGREE_TEMP
    assert out["neighbor_shock"] is True


def test_disagreement_is_unchanged_by_the_rule() -> None:
    out = _t3(55.0, _buddies())
    assert out["neighbors_agree"] is False
    assert out["neighbor_shock"] is False


def test_no_history_means_unknown_not_false() -> None:
    out = _t3(30.4, _buddies(hours=1))
    assert out["neighbors_agree"] is True
    assert out["neighbor_shock"] is None
    assert out["blend_shift"]["temp"] is None


def test_shared_shock_only_judges_checked_channels() -> None:
    usable = [
        {"station_id": "A", "distance_km": 5.0, "w": 1.0, "temp": 30.0, "rhum": 70.0, "pres": 1010.0},
        {"station_id": "B", "distance_km": 8.0, "w": 1.0, "temp": 30.5, "rhum": 70.0, "pres": 1010.0},
    ]
    windows = _buddies()
    for buddy in windows:
        for row in buddy["window"][:-1]:
            row["rhum"] = 40.0  # humidity jumped 30 points this hour; temperature calm
    calm_temp = shared_shock(T0, usable, windows, 2.0, ["temp"])
    assert calm_temp["neighbor_shock"] is False
    humid = shared_shock(T0, usable, windows, 2.0, ["rhum"])
    assert humid["neighbor_shock"] is True
