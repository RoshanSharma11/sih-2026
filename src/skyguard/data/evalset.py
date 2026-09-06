"""Build a labeled eval set from clean station parquet using inject.py."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from skyguard.config import DATA_DIR, PROCESSED_DIR, STATIONS_PATH
from skyguard.data.catalog import read_catalog
from skyguard.data.inject import DEFAULT_STD, inject_comm_error, inject_drift, inject_freeze, inject_spike, inject_storm
from skyguard.schemas import Channel, FaultType

EVAL_PATH = DATA_DIR / "eval" / "labeled.parquet"
HARDWARE = {FaultType.SPIKE, FaultType.FREEZE, FaultType.DRIFT, FaultType.COMM_ERROR}
CHANNELS = (Channel.TEMP_C, Channel.PRES_HPA, Channel.RHUM_PCT)
MIX = {
    FaultType.SPIKE: 0.25,
    FaultType.FREEZE: 0.20,
    FaultType.DRIFT: 0.15,
    FaultType.COMM_ERROR: 0.15,
    FaultType.GENUINE_WEATHER: 0.25,
}
SEED = 26073


def _allocate(n_anom: int) -> dict[FaultType, int]:
    counts = {kind: int(round(share * n_anom)) for kind, share in MIX.items()}
    counts[FaultType.SPIKE] += n_anom - sum(counts.values())
    return counts


def _std(series: pd.Series, channel: Channel) -> float:
    value = pd.to_numeric(series, errors="coerce").std()
    if pd.isna(value) or value < 0.5:
        return DEFAULT_STD[channel]
    return float(value)


def _slice_to_target(frames: dict[str, pd.DataFrame], target_rows: int) -> pd.DataFrame:
    pieces = []
    for station_id, frame in frames.items():
        piece = frame.copy()
        if "timestamp" not in piece.columns:
            piece = piece.reset_index()
        piece["timestamp"] = pd.to_datetime(piece["timestamp"], utc=True)
        piece["station_id"] = station_id
        for channel in ("temp_c", "pres_hpa", "rhum_pct"):
            piece[channel] = pd.to_numeric(piece[channel], errors="coerce").astype("float64")
        pieces.append(piece[["station_id", "timestamp", "temp_c", "pres_hpa", "rhum_pct"]])
    table = pd.concat(pieces, ignore_index=True).sort_values(["timestamp", "station_id"])
    if len(table) <= target_rows:
        return table.reset_index(drop=True)
    n_stations = table["station_id"].nunique()
    n_hours = int(np.ceil(target_rows / max(n_stations, 1)))
    times = np.sort(table["timestamp"].unique())[-n_hours:]
    return table[table["timestamp"].isin(times)].reset_index(drop=True)


def _mark(table: pd.DataFrame, idx: int, fault: FaultType, channel: Channel | None) -> None:
    table.at[idx, "fault_type"] = fault.value
    table.at[idx, "channel"] = None if channel is None else channel.value
    table.at[idx, "is_anomaly"] = fault in HARDWARE


def _contiguous_starts(table: pd.DataFrame, station_id: str, length: int, used: set[int]) -> list[list[int]]:
    sub = table.index[table["station_id"] == station_id].tolist()
    sub = [i for i in sub if i not in used]
    blocks: list[list[int]] = []
    i = 0
    while i + length <= len(sub):
        idxs = sub[i : i + length]
        times = table.loc[idxs, "timestamp"].tolist()
        deltas = pd.Series(times).diff().iloc[1:]
        if not idxs:
            i += 1
            continue
        if all(delta == pd.Timedelta(hours=1) for delta in deltas) and all(
            table.loc[idxs, ["temp_c", "pres_hpa", "rhum_pct"]].notna().all(axis=1)
        ):
            blocks.append(idxs)
            i += length
        else:
            i += 1
    return blocks


def build_evalset(
    frames: dict[str, pd.DataFrame],
    clusters: dict[str, str],
    rng: np.random.Generator | None = None,
    target_rows: int = 10_000,
) -> pd.DataFrame:
    rng = rng or np.random.default_rng(SEED)
    table = _slice_to_target(frames, target_rows)
    table["temp_c_raw"] = table["temp_c"]
    table["pres_hpa_raw"] = table["pres_hpa"]
    table["rhum_pct_raw"] = table["rhum_pct"]
    table["fault_type"] = pd.Series([pd.NA] * len(table), dtype="object")
    table["channel"] = pd.Series([pd.NA] * len(table), dtype="object")
    table["is_anomaly"] = False

    used: set[int] = set()
    counts = _allocate(int(round(0.15 * len(table))))
    by_cluster: dict[str, list[str]] = {}
    for station_id, cluster_id in clusters.items():
        by_cluster.setdefault(cluster_id, []).append(station_id)

    def _free_complete() -> list[int]:
        mask = table[["temp_c_raw", "pres_hpa_raw", "rhum_pct_raw"]].notna().all(axis=1)
        return [int(i) for i in table.index[mask] if int(i) not in used]

    # Storms first so a cluster shares the same hour.
    placed_weather = 0
    timestamps = list(table["timestamp"].unique())
    rng.shuffle(timestamps)
    for ts in timestamps:
        if placed_weather >= counts[FaultType.GENUINE_WEATHER]:
            break
        for _cluster_id, members in by_cluster.items():
            rows = table.index[(table["timestamp"] == ts) & (table["station_id"].isin(members))].tolist()
            if len(rows) < 2:
                continue
            if any(i in used for i in rows):
                continue
            if not table.loc[rows, ["temp_c", "pres_hpa", "rhum_pct"]].notna().all(axis=None):
                continue
            if placed_weather + len(rows) > counts[FaultType.GENUINE_WEATHER] + 1:
                continue
            delta_t, delta_p, delta_h = inject_storm(0.0, 0.0, 0.0, rng)
            # inject_storm(0,0,0) returns (-U, -U, +U); apply the same offset to every neighbor.
            for idx in rows:
                table.at[idx, "temp_c"] = float(table.at[idx, "temp_c"]) + delta_t
                table.at[idx, "pres_hpa"] = float(table.at[idx, "pres_hpa"]) + delta_p
                table.at[idx, "rhum_pct"] = min(100.0, float(table.at[idx, "rhum_pct"]) + delta_h)
                _mark(table, idx, FaultType.GENUINE_WEATHER, None)
                used.add(idx)
                placed_weather += 1
            break

    def _place_blocks(fault: FaultType, length: int, mutate) -> int:
        placed = 0
        stations = list(frames)
        rng.shuffle(stations)
        for station_id in stations:
            if placed >= counts[fault]:
                break
            for block in _contiguous_starts(table, station_id, length, used):
                if placed + length > counts[fault] + length - 1:
                    break
                channel = CHANNELS[int(rng.integers(0, len(CHANNELS)))]
                mutate(table, block, station_id, channel)
                for idx in block:
                    _mark(table, idx, fault, channel)
                    used.add(idx)
                    placed += 1
                if placed >= counts[fault]:
                    break
        return placed

    def _freeze(table: pd.DataFrame, block: list[int], station_id: str, channel: Channel) -> None:
        series = table.loc[block, channel.value].to_numpy(dtype=float)
        frozen = inject_freeze(series, 0, duration=len(block))
        table.loc[block, channel.value] = frozen

    def _drift(table: pd.DataFrame, block: list[int], station_id: str, channel: Channel) -> None:
        series = table.loc[block, channel.value].to_numpy(dtype=float)
        drifted = inject_drift(series, 0, duration=len(block))
        table.loc[block, channel.value] = drifted

    _place_blocks(FaultType.DRIFT, 48, _drift)
    _place_blocks(FaultType.FREEZE, 12, _freeze)

    for idx in _free_complete():
        if sum(1 for i in used if table.at[i, "fault_type"] == FaultType.SPIKE.value) >= counts[FaultType.SPIKE]:
            break
        channel = CHANNELS[int(rng.integers(0, len(CHANNELS)))]
        std = _std(table.loc[table["station_id"] == table.at[idx, "station_id"], f"{channel.value}_raw"], channel)
        table.at[idx, channel.value] = inject_spike(float(table.at[idx, channel.value]), std, rng)
        _mark(table, idx, FaultType.SPIKE, channel)
        used.add(idx)

    for idx in _free_complete():
        if sum(1 for i in used if table.at[i, "fault_type"] == FaultType.COMM_ERROR.value) >= counts[FaultType.COMM_ERROR]:
            break
        if int(rng.integers(0, 2)) == 0:
            table.at[idx, "temp_c"] = inject_comm_error()
            table.at[idx, "pres_hpa"] = inject_comm_error()
            table.at[idx, "rhum_pct"] = inject_comm_error()
            _mark(table, idx, FaultType.COMM_ERROR, None)
        else:
            channel = CHANNELS[int(rng.integers(0, len(CHANNELS)))]
            table.at[idx, channel.value] = inject_comm_error()
            _mark(table, idx, FaultType.COMM_ERROR, channel)
        used.add(idx)

    return table[
        [
            "station_id",
            "timestamp",
            "temp_c",
            "pres_hpa",
            "rhum_pct",
            "temp_c_raw",
            "pres_hpa_raw",
            "rhum_pct_raw",
            "fault_type",
            "channel",
            "is_anomaly",
        ]
    ]


def histogram(table: pd.DataFrame) -> dict[str, int]:
    filled = table["fault_type"].fillna("CLEAN")
    return filled.value_counts(dropna=False).to_dict()


def load_processed_frames(processed_dir: Path | None = None, catalog_path: Path | None = None) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    document = read_catalog(catalog_path)
    frames: dict[str, pd.DataFrame] = {}
    clusters: dict[str, str] = {}
    root = processed_dir or PROCESSED_DIR
    for station in document["stations"]:
        path = root / f"{station['station_id']}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Missing {path}; run python -m skyguard.data.fetch")
        frames[station["station_id"]] = pd.read_parquet(path)
        clusters[station["station_id"]] = station["cluster_id"]
    return frames, clusters


def run(output: Path | None = None, target_rows: int = 10_000) -> Path:
    frames, clusters = load_processed_frames()
    table = build_evalset(frames, clusters, rng=np.random.default_rng(SEED), target_rows=target_rows)
    path = output or EVAL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(path, index=False)
    print(f"Wrote {len(table)} rows to {path}")
    print(histogram(table))
    print(f"anomaly_rate={table['is_anomaly'].mean():.3f}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the labeled SkyGuard eval set.")
    parser.add_argument("--rows", type=int, default=10_000)
    parser.add_argument("--output", type=Path, default=EVAL_PATH)
    args = parser.parse_args()
    run(output=args.output, target_rows=args.rows)


if __name__ == "__main__":
    main()
