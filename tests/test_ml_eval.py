from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from skyguard.data.ml_eval import (
    OUTPUT_COLS,
    plot_eval_results,
    simulate_corruption,
)


def test_standalone_script_does_not_import_skyguard() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts" / "simulate_corruption_eval.py").read_text()
    assert "import skyguard" not in source
    assert "from skyguard" not in source
    assert "import fastapi" not in source.lower()


def _station_frame(station_id: str, hours: int = 160) -> pd.DataFrame:
    start = datetime(2024, 7, 1, tzinfo=timezone.utc)
    timestamps = [start + timedelta(hours=i) for i in range(hours)]
    return pd.DataFrame(
        {
            "station_id": station_id,
            "timestamp": timestamps,
            "temp": 28.0 + np.sin(np.arange(hours) / 8.0),
            "rhum": 55.0 + np.sin(np.arange(hours) / 6.0),
            "pres": 1010.0 + np.cos(np.arange(hours) / 10.0),
        }
    )


def _clean_grid() -> tuple[pd.DataFrame, dict[str, str]]:
    frame = pd.concat(
        [_station_frame("N1"), _station_frame("N2"), _station_frame("W1"), _station_frame("W2")],
        ignore_index=True,
    )
    clusters = {"N1": "NORTH", "N2": "NORTH", "W1": "WEST", "W2": "WEST"}
    return frame, clusters


def test_simulate_corruption_is_seeded_and_raw() -> None:
    clean, clusters = _clean_grid()
    clean["rhum"] = clean["rhum"].round().astype("uint8")
    first = simulate_corruption(clean, seed=42, clusters=clusters)
    second = simulate_corruption(clean, seed=42, clusters=clusters)
    other = simulate_corruption(clean, seed=43, clusters=clusters)
    pd.testing.assert_frame_equal(first, second)
    assert not first["temp_corrupted"].equals(other["temp_corrupted"])
    assert list(first.columns) == OUTPUT_COLS
    assert len(first) == len(clean)
    assert set(first["timestamp"]) == set(pd.to_datetime(clean["timestamp"], utc=True))
    assert float(first["temp_original"].mean()) > 10
    assert float(first["pres_original"].mean()) > 900
    assert (first["fault_type"] == "CLEAN").mean() > 0.7
    assert set(first["fault_type"]).issuperset({"SPIKE", "FREEZE", "DRIFT", "COMMUNICATION", "STORM", "CLEAN"})

    comm = first[first["fault_type"] == "COMMUNICATION"]
    assert comm[["temp_corrupted", "rhum_corrupted", "pres_corrupted"]].isna().any(axis=1).all()
    storms = first[first["fault_type"] == "STORM"]
    assert not storms[["temp_corrupted", "rhum_corrupted", "pres_corrupted"]].isna().any(axis=None)
    hardware = first[first["fault_type"].isin({"SPIKE", "FREEZE", "DRIFT", "COMMUNICATION"})]
    assert len(hardware) > 0
    assert len(storms) > 0


def test_plot_eval_results_writes_png(tmp_path) -> None:
    clean, clusters = _clean_grid()
    labeled = simulate_corruption(clean, seed=42, clusters=clusters)
    path = plot_eval_results(labeled, out_path=tmp_path / "report.png")
    assert path.exists()
    assert path.stat().st_size > 1000


def test_run_writes_eval_csv_not_for_training(tmp_path) -> None:
    clean, _clusters = _clean_grid()
    clean_path = tmp_path / "clean.csv"
    clean.to_csv(clean_path, index=False)
    from skyguard.data.ml_eval import run

    written = run(clean_path=clean_path, out_dir=tmp_path, seed=42, start="2024-07-01", end="2024-07-10")
    table = pd.read_csv(written["labeled"])
    assert written["labeled"].suffix == ".csv"
    assert "fault_type" in table.columns
    assert "temp_corrupted" in table.columns
    assert written["plot"].exists()


def test_storms_follow_cluster_column_not_all_stations() -> None:
    clean, _ = _clean_grid()
    clean = clean.copy()
    clean["cluster_id"] = clean["station_id"].map({"N1": "NORTH", "N2": "NORTH", "W1": "WEST", "W2": "WEST"})
    labeled = simulate_corruption(clean, seed=42)
    storms = labeled[labeled["fault_type"] == "STORM"]
    assert not storms.empty
    for _, group in storms.groupby("timestamp"):
        ids = set(group["station_id"])
        assert ids <= {"N1", "N2"} or ids <= {"W1", "W2"}


def test_unclustered_foreign_stations_do_not_share_storms() -> None:
    start = datetime(2024, 7, 1, tzinfo=timezone.utc)
    hours = 160
    timestamps = [start + timedelta(hours=i) for i in range(hours)]
    def one(sid: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "station_id": sid,
                "timestamp": timestamps,
                "temp": 28.0,
                "rhum": 55.0,
                "pres": 1010.0,
            }
        )
    clean = pd.concat([one("DELHI"), one("CHENNAI")], ignore_index=True)
    labeled = simulate_corruption(clean, seed=42)
    storms = labeled[labeled["fault_type"] == "STORM"]
    assert storms.empty
