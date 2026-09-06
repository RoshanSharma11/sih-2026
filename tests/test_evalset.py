from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from skyguard.data.evalset import build_evalset, histogram
from skyguard.schemas import FaultType


def _station_frame(station_id: str, hours: int = 120) -> pd.DataFrame:
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    timestamps = [start + timedelta(hours=i) for i in range(hours)]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "temp_c": 28.0 + np.sin(np.arange(hours) / 8.0),
            "pres_hpa": 1010.0 + np.cos(np.arange(hours) / 10.0),
            "rhum_pct": 55.0 + np.sin(np.arange(hours) / 6.0),
        }
    )


def test_evalset_mix_and_storm_physics() -> None:
    frames = {
        "N1": _station_frame("N1"),
        "N2": _station_frame("N2"),
        "W1": _station_frame("W1"),
        "W2": _station_frame("W2"),
    }
    clusters = {"N1": "NORTH", "N2": "NORTH", "W1": "WEST", "W2": "WEST"}
    table = build_evalset(frames, clusters, rng=np.random.default_rng(26073), target_rows=480)
    counts = histogram(table)
    assert counts.get("CLEAN", 0) > 0
    for kind in (
        FaultType.SPIKE.value,
        FaultType.FREEZE.value,
        FaultType.DRIFT.value,
        FaultType.COMM_ERROR.value,
        FaultType.GENUINE_WEATHER.value,
    ):
        assert counts.get(kind, 0) > 0

    weather = table[table["fault_type"] == FaultType.GENUINE_WEATHER.value]
    assert not bool(weather["is_anomaly"].any())
    sample_ts = weather["timestamp"].iloc[0]
    pair = weather[weather["timestamp"] == sample_ts]
    assert pair["station_id"].nunique() >= 2
    for _, row in pair.iterrows():
        assert row["temp_c"] < row["temp_c_raw"]
        assert row["pres_hpa"] < row["pres_hpa_raw"]
        assert row["rhum_pct"] > row["rhum_pct_raw"]

    freeze = table[table["fault_type"] == FaultType.FREEZE.value]
    channel = freeze["channel"].iloc[0]
    block = freeze[freeze["channel"] == channel].head(12)
    values = block[channel].to_numpy()
    assert np.allclose(values, values[0])

    hardware = table[table["is_anomaly"]]
    assert set(hardware["fault_type"]).issubset(
        {FaultType.SPIKE.value, FaultType.FREEZE.value, FaultType.DRIFT.value, FaultType.COMM_ERROR.value}
    )
