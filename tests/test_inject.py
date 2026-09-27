import numpy as np
import pytest

from skyguard.data.inject import (
    Observation,
    apply_live,
    apply_replay_mutation,
    inject_comm_error,
    inject_drift,
    inject_freeze,
    inject_hardware_reading,
    inject_heat,
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


def test_replay_mutations_are_fixed_readings() -> None:
    reading = inject_hardware_reading()
    assert reading == Observation(55.0, 980.0, 95.0)
    assert inject_heat(26.0) == pytest.approx(34.0)
    hardware, kind = apply_replay_mutation("hardware", Observation(26.0, 1013.0, 65.0))
    assert kind is FaultType.SPIKE
    assert hardware == reading
    heated, weather = apply_replay_mutation("weather", Observation(24.4, 1013.2, 77.0))
    assert weather is FaultType.GENUINE_WEATHER
    assert heated.temp_c == pytest.approx(32.4)
    assert heated.pres_hpa == pytest.approx(1013.2)
    frozen, freeze = apply_replay_mutation("freeze", Observation(30.0, 1013.0, 65.0), freeze_anchor=26.0)
    assert freeze is FaultType.FREEZE
    assert frozen.temp_c == 26.0
    missing, comms = apply_replay_mutation("comms", Observation(26.0, 1013.0, 65.0))
    assert comms is FaultType.COMM_ERROR
    assert missing.temp_c is None
    assert missing.pres_hpa == 1013.0
