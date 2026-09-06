from datetime import datetime

import pandas as pd

from skyguard.data.catalog import (
    StationRecord,
    completeness,
    haversine_km,
    nearest_cluster,
    passes_threshold,
    select_keepers,
)
from skyguard.data.fetch import METEOSTAT_TO_OURS, _year_windows, normalize_hourly, persist_station
from skyguard.schemas import ClusterId


def _record(station_id: str, lat: float, lon: float, cluster: str, score: float) -> StationRecord:
    return StationRecord(
        station_id=station_id,
        name=station_id,
        latitude=lat,
        longitude=lon,
        elevation_m=200,
        cluster_id=cluster,
        completeness={"temp_c": score, "pres_hpa": score, "rhum_pct": score},
    )


def test_year_windows_cover_fetch_range() -> None:
    windows = _year_windows(datetime(2018, 1, 1), datetime(2024, 12, 31, 23))
    assert len(windows) == 7
    assert windows[0][0] == datetime(2018, 1, 1)
    assert windows[-1][1] == datetime(2024, 12, 31, 23)


def test_haversine_delhi_to_self_is_zero() -> None:
    assert haversine_km(28.57, 77.12, 28.57, 77.12) < 0.01


def test_nearest_cluster_delhi_and_mumbai() -> None:
    assert nearest_cluster(28.57, 77.12) == ClusterId.NORTH.value
    assert nearest_cluster(19.09, 72.87) == ClusterId.WEST.value


def test_completeness_uses_calendar_hours() -> None:
    start = datetime(2024, 1, 1)
    end = datetime(2024, 1, 1, 3)
    df = pd.DataFrame(
        {"temp_c": [20.0, None, 21.0], "pres_hpa": [1000.0, 1001.0, 1002.0], "rhum_pct": [50.0, 51.0, None]},
        index=pd.date_range(start, periods=3, freq="h"),
    )
    scores = completeness(df, start, end)
    assert scores["temp_c"] == 0.5
    assert scores["pres_hpa"] == 0.75
    assert scores["rhum_pct"] == 0.5
    assert passes_threshold(scores) is False
    assert passes_threshold({"temp_c": 0.9, "pres_hpa": 0.9, "rhum_pct": 0.9}) is True


def test_normalize_hourly_maps_meteostat_columns(tmp_path) -> None:
    start = datetime(2024, 1, 1)
    end = datetime(2024, 1, 1, 2)
    raw = pd.DataFrame(
        {"temp": [30.0, 31.0], "pres": [1005.0, 1006.0], "rhum": [60.0, 61.0]},
        index=pd.to_datetime(["2024-01-01T00:00:00", "2024-01-01T01:00:00"]),
    )
    out = normalize_hourly(raw, start, end)
    assert list(out.columns) == ["temp_c", "pres_hpa", "rhum_pct"]
    assert len(out) == 3
    assert pd.isna(out.loc[pd.Timestamp("2024-01-01T02:00:00", tz="UTC"), "temp_c"])
    persist_station("42181", out, processed_dir=tmp_path)
    loaded = pd.read_parquet(tmp_path / "42181.parquet")
    assert set(METEOSTAT_TO_OURS.values()) <= set(loaded.columns)
    assert len(pd.read_parquet(tmp_path / "42181.clean.parquet")) == 2


def test_select_keepers_falls_back_to_north_without_west_pair() -> None:
    candidates = [
        _record("N1", 28.57, 77.12, "NORTH", 0.99),
        _record("N2", 28.58, 77.20, "NORTH", 0.98),
        _record("N3", 28.60, 77.10, "NORTH", 0.97),
        _record("N4", 28.55, 77.05, "NORTH", 0.96),
        _record("N5", 28.50, 77.00, "NORTH", 0.95),
        _record("W1", 19.09, 72.87, "WEST", 0.94),
    ]
    keepers, notes = select_keepers(candidates)
    assert len(keepers) == 5
    assert all(k.cluster_id == "NORTH" for k in keepers)
    assert "WEST lacked" in notes


def test_select_keepers_does_not_steal_west_when_north_is_short() -> None:
    candidates = [
        _record("N1", 28.57, 77.12, "NORTH", 0.99),
        _record("N2", 28.58, 77.20, "NORTH", 0.98),
        _record("W1", 19.09, 72.87, "WEST", 0.96),
        _record("W2", 19.15, 72.95, "WEST", 0.95),
    ]
    keepers, _notes = select_keepers(candidates)
    assert len(keepers) == 4
    assert sum(k.cluster_id == "WEST" for k in keepers) == 2
    assert sum(k.cluster_id == "NORTH" for k in keepers) == 2


def test_select_keepers_keeps_two_clusters() -> None:
    candidates = [
        _record("N1", 28.57, 77.12, "NORTH", 0.99),
        _record("N2", 28.58, 77.20, "NORTH", 0.98),
        _record("N3", 28.60, 77.10, "NORTH", 0.97),
        _record("W1", 19.09, 72.87, "WEST", 0.96),
        _record("W2", 19.15, 72.95, "WEST", 0.95),
    ]
    keepers, notes = select_keepers(candidates)
    clusters = {k.cluster_id for k in keepers}
    assert clusters == {"NORTH", "WEST"}
    assert sum(k.cluster_id == "NORTH" for k in keepers) == 3
    assert sum(k.cluster_id == "WEST" for k in keepers) == 2
    assert notes == ""
