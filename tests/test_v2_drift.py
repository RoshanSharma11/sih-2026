"""Residual CUSUM drift: slow bias vs neighbours, not a spike, not a shared storm."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "v2-deliverable"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2.config import AGREE_TEMP, DRIFT_CUSUM_H_FRACTION, DRIFT_MIN_HOURS  # noqa: E402
from v2.drift import detect_drift, residual_history  # noqa: E402
from v2.root_cause import infer_fault_type  # noqa: E402

T0 = datetime(2024, 7, 2, 12)
HOURS = 24


def _rows(base: float, ramp: float = 0.0, last_jump: float = 0.0) -> list[dict]:
    rows = []
    for i in range(HOURS):
        ts = T0 - timedelta(hours=HOURS - 1 - i)
        value = base + ramp * i + (last_jump if i == HOURS - 1 else 0.0)
        rows.append({"timestamp": ts, "temp": value, "rhum": 70.0, "pres": 1010.0})
    return rows


def _buddies() -> list[dict]:
    return [
        {"station_id": "A", "distance_km": 5.0, "window": _rows(30.0)},
        {"station_id": "B", "distance_km": 8.0, "window": _rows(30.2)},
    ]


def test_official_slope_over_24h_fires_on_temperature() -> None:
    # Seed-42 injector: +0.1 °C/h. Neighbours stay put.
    primary = _rows(30.1, ramp=0.1)
    out = detect_drift(T0, primary, _buddies())
    assert out["fired"] is True
    assert out["channel"] == "temp"
    assert out["hours"] >= DRIFT_MIN_HOURS
    assert out["cusum"] >= DRIFT_CUSUM_H_FRACTION * AGREE_TEMP
    assert abs(out["last"]) >= 2.0


def test_a_lone_spike_does_not_fire() -> None:
    primary = _rows(30.1, last_jump=25.0)
    out = detect_drift(T0, primary, _buddies())
    assert out["fired"] is False


def test_shared_weather_ramp_does_not_fire() -> None:
    # Neighbours climb with the primary: residual stays ~0.
    ramp = 0.4
    buddies = [
        {"station_id": "A", "distance_km": 5.0, "window": _rows(30.0, ramp=ramp)},
        {"station_id": "B", "distance_km": 8.0, "window": _rows(30.2, ramp=ramp)},
    ]
    out = detect_drift(T0, _rows(30.1, ramp=ramp), buddies)
    assert out["fired"] is False
    history = residual_history(T0, _rows(30.1, ramp=ramp), buddies)
    assert history["temp"]
    assert max(abs(v) for v in history["temp"]) < 1.0


def test_too_few_hours_or_no_buddies_does_not_fire() -> None:
    short = _rows(30.1, ramp=0.1)[-10:]
    assert detect_drift(T0, short, _buddies())["fired"] is False
    assert detect_drift(T0, _rows(30.1, ramp=0.1), [])["fired"] is False
    assert detect_drift(T0, [], _buddies())["fired"] is False


def _fault(**kwargs):
    base = dict(
        communication=False,
        tier1_violations=[],
        window_df=None,
        affected=["temp"],
        observed={"temp": 32.0},
        predicted=None,
        neighbors_agree=None,
        drift_fired=False,
    )
    base.update(kwargs)
    return infer_fault_type(**base)


def test_infer_fault_type_cusum_is_drift_after_hard_rules() -> None:
    assert _fault(drift_fired=True) == "DRIFT"
    assert _fault(communication=True, drift_fired=True) == "COMMUNICATION"
    assert _fault(tier1_violations=["STEP:temp"], drift_fired=True) == "SPIKE"
