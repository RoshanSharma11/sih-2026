import numpy as np
import pytest

from skyguard.data.inject import (
    Observation,
    apply_live,
    inject_comm_error,
    inject_drift,
    inject_freeze,
    inject_spike,
    inject_storm,
)
from skyguard.schemas import Channel, FaultType


def test_spike_moves_by_at_least_four_std() -> None:
    rng = np.random.default_rng(0)
    value = inject_spike(20.0, 2.0, rng)
    assert abs(value - 20.0) >= 8.0
    assert abs(value - 20.0) <= 16.0


def test_freeze_holds_the_start_value() -> None:
    series = np.arange(20, dtype=float)
    frozen = inject_freeze(series, start=3, duration=12)
    assert np.all(frozen[3:15] == 3.0)
    assert frozen[2] == 2.0
    assert frozen[15] == 15.0


def test_drift_adds_linear_slope() -> None:
    series = np.zeros(10)
    drifted = inject_drift(series, start=2, duration=5, slope=0.1)
    assert drifted[2] == pytest.approx(0.0)
    assert drifted[6] == pytest.approx(0.4)
    assert drifted[7] == pytest.approx(0.0)


def test_comm_error_is_none() -> None:
    assert inject_comm_error() is None


def test_storm_preserves_physics() -> None:
    rng = np.random.default_rng(26073)
    temp_c, pres_hpa, rhum_pct = inject_storm(32.0, 1010.0, 40.0, rng)
    assert temp_c < 32.0 - 7.9
    assert pres_hpa < 1010.0 - 9.9
    assert rhum_pct > 40.0 + 29.9
    assert rhum_pct <= 100.0


def test_apply_live_spike_and_freeze_and_storm() -> None:
    rng = np.random.default_rng(1)
    clean = Observation(30.0, 1005.0, 60.0)
    spiked = apply_live(FaultType.SPIKE, clean, Channel.TEMP_C, 0, rng=rng)
    assert spiked.temp_c != 30.0
    assert spiked.pres_hpa == 1005.0

    frozen = apply_live(FaultType.FREEZE, Observation(31.0, 1005.0, 60.0), Channel.TEMP_C, 3, freeze_anchor=30.0)
    assert frozen.temp_c == 30.0

    drifted = apply_live(FaultType.DRIFT, clean, Channel.TEMP_C, 5)
    assert drifted.temp_c == pytest.approx(30.5)

    storm = apply_live(FaultType.GENUINE_WEATHER, clean, None, 0, rng=rng)
    assert storm.temp_c < clean.temp_c
    assert storm.pres_hpa < clean.pres_hpa
    assert storm.rhum_pct > clean.rhum_pct

    missing = apply_live(FaultType.COMM_ERROR, clean, None, 0)
    assert missing == Observation(None, None, None)
