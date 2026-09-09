#!/usr/bin/env python3
"""SkyGuard labeled EVAL set — standalone. Send this one file.

Does not change the live SkyGuard simulator. No SkyGuard install.
Needs: pandas, numpy, matplotlib.

This is NOT a training set.
Train the LSTM on clean hours only.
This script builds a labeled eval file:

    clean CSV  →  inject faults (seed=42)  →  labeled CSV + graph

CLI::

    python simulate_corruption_eval.py --clean test_2024.csv --out ./eval_out

Notebook::

    from simulate_corruption_eval import simulate_corruption
    labeled = simulate_corruption(test_clean, seed=42)

Input columns: station_id, timestamp, and either temp/rhum/pres
or temp_c/rhum_pct/pres_hpa. Raw units, not scaled.
Optional cluster_id column: storms hit every station in that cluster
at the same hour. Without it, known SkyGuard ids use NORTH/WEST;
any other station is its own cluster (no cross-region storms).

Output CSV columns:
    station_id, timestamp, fault_type,
    temp_original, rhum_original, pres_original,
    temp_corrupted, rhum_corrupted, pres_corrupted

fault_type: CLEAN | SPIKE | FREEZE | DRIFT | COMMUNICATION | STORM
Communication is NaN. Storms are labeled STORM (not hardware).
seed=42 is deterministic. Does not normalize or drop timestamps.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_SEED = 42
ANOMALY_RATE = 0.15
DRIFT_SLOPE = 0.1

DEFAULT_CLUSTERS = {
    "42181": "NORTH",
    "42182": "NORTH",
    "43003": "WEST",
    "43057": "WEST",
}
CHANNELS = ("temp_c", "pres_hpa", "rhum_pct")
DEFAULT_STD = {"temp_c": 2.0, "pres_hpa": 2.0, "rhum_pct": 5.0}
MIX = {
    "SPIKE": 0.25,
    "FREEZE": 0.20,
    "DRIFT": 0.15,
    "COMMUNICATION": 0.15,
    "STORM": 0.25,
}
INPUT_ALIASES = {
    "temp": "temp_c",
    "temp_c": "temp_c",
    "rhum": "rhum_pct",
    "rhum_pct": "rhum_pct",
    "pres": "pres_hpa",
    "pres_hpa": "pres_hpa",
}
OUTPUT_COLS = [
    "station_id",
    "timestamp",
    "fault_type",
    "temp_original",
    "rhum_original",
    "pres_original",
    "temp_corrupted",
    "rhum_corrupted",
    "pres_corrupted",
]
CLASS_ORDER = ["CLEAN", "SPIKE", "FREEZE", "DRIFT", "COMMUNICATION", "STORM"]
FAULT_COLORS = {
    "CLEAN": "#8a8f98",
    "SPIKE": "#e5534b",
    "FREEZE": "#3d8bfd",
    "DRIFT": "#f0a202",
    "COMMUNICATION": "#9b5de5",
    "STORM": "#2a9d8f",
}


def inject_spike(value: float, std_dev: float, rng: np.random.Generator) -> float:
    sign = float(rng.choice([-1.0, 1.0]))
    return float(value + sign * rng.uniform(4.0, 8.0) * std_dev)


def inject_freeze(series: np.ndarray, start: int, duration: int = 12) -> np.ndarray:
    out = np.array(series, dtype=float, copy=True)
    stop = min(start + duration, len(out))
    out[start:stop] = out[start]
    return out


def inject_drift(series: np.ndarray, start: int, duration: int = 48, slope: float = DRIFT_SLOPE) -> np.ndarray:
    out = np.array(series, dtype=float, copy=True)
    stop = min(start + duration, len(out))
    for offset, idx in enumerate(range(start, stop)):
        out[idx] += slope * offset
    return out


def inject_comm_error() -> None:
    return None


def inject_storm(
    temp_c: float,
    pres_hpa: float,
    rhum_pct: float,
    rng: np.random.Generator,
) -> tuple[float, float, float]:
    return (
        float(temp_c - rng.uniform(8.0, 15.0)),
        float(pres_hpa - rng.uniform(10.0, 25.0)),
        float(min(100.0, rhum_pct + rng.uniform(30.0, 50.0))),
    )


def _allocate(n_anom: int) -> dict[str, int]:
    counts = {kind: int(round(share * n_anom)) for kind, share in MIX.items()}
    counts["SPIKE"] += n_anom - sum(counts.values())
    return counts


def _std(series: pd.Series, channel: str) -> float:
    value = pd.to_numeric(series, errors="coerce").std()
    if pd.isna(value) or value < 0.5:
        return DEFAULT_STD[channel]
    return float(value)


def _require_channel(frame: pd.DataFrame, ours: str) -> str:
    for name, mapped in INPUT_ALIASES.items():
        if mapped == ours and name in frame.columns:
            return name
    raise ValueError(f"clean_df must include {ours} (or an alias: temp/rhum/pres)")


def _as_clean_table(clean_df: pd.DataFrame) -> pd.DataFrame:
    if "station_id" not in clean_df.columns or "timestamp" not in clean_df.columns:
        raise ValueError("clean_df must include station_id and timestamp")
    table = pd.DataFrame(
        {
            "station_id": clean_df["station_id"].astype(str),
            "timestamp": pd.to_datetime(clean_df["timestamp"], utc=True),
            "temp_c": pd.to_numeric(clean_df[_require_channel(clean_df, "temp_c")], errors="coerce").astype("float64"),
            "pres_hpa": pd.to_numeric(clean_df[_require_channel(clean_df, "pres_hpa")], errors="coerce").astype("float64"),
            "rhum_pct": pd.to_numeric(clean_df[_require_channel(clean_df, "rhum_pct")], errors="coerce").astype("float64"),
        }
    )
    if "cluster_id" in clean_df.columns:
        table["cluster_id"] = pd.Series(clean_df["cluster_id"].to_numpy(), index=table.index, dtype="object")
    return table.sort_values(["timestamp", "station_id"]).reset_index(drop=True)


def _contiguous_starts(table: pd.DataFrame, station_id: str, length: int, used: set[int]) -> list[list[int]]:
    sub = [i for i in table.index[table["station_id"] == station_id].tolist() if i not in used]
    blocks: list[list[int]] = []
    i = 0
    while i + length <= len(sub):
        idxs = sub[i : i + length]
        times = table.loc[idxs, "timestamp"].tolist()
        deltas = pd.Series(times).diff().iloc[1:]
        complete = table.loc[idxs, list(CHANNELS)].notna().all(axis=1)
        if all(delta == pd.Timedelta(hours=1) for delta in deltas) and bool(complete.all()):
            blocks.append(idxs)
            i += length
        else:
            i += 1
    return blocks


def _resolve_clusters(table: pd.DataFrame, clusters: dict[str, str] | None) -> dict[str, str]:
    resolved: dict[str, str] = dict(DEFAULT_CLUSTERS)
    if "cluster_id" in table.columns:
        pairs = table.dropna(subset=["cluster_id"])[["station_id", "cluster_id"]].drop_duplicates("station_id")
        for station_id, cluster_id in pairs.itertuples(index=False):
            label = str(cluster_id).strip()
            if not label or label.lower() in {"nan", "none", "unknown"}:
                continue
            resolved[str(station_id)] = label
    if clusters:
        resolved.update({str(k): str(v) for k, v in clusters.items()})
    for station_id in table["station_id"].astype(str).unique():
        resolved.setdefault(station_id, station_id)
    return resolved


def simulate_corruption(
    clean_df: pd.DataFrame,
    seed: int = DEFAULT_SEED,
    clusters: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Corrupt raw T/P/H with a seeded 15% mix. Does not scale or drop timestamps."""
    rng = np.random.default_rng(seed)
    table = _as_clean_table(clean_df)
    resolved = _resolve_clusters(table, clusters)

    frames = {sid: table.loc[table["station_id"] == sid] for sid in table["station_id"].unique()}
    table["temp_c_raw"] = table["temp_c"]
    table["pres_hpa_raw"] = table["pres_hpa"]
    table["rhum_pct_raw"] = table["rhum_pct"]
    table["fault_type"] = pd.Series([pd.NA] * len(table), dtype="object")
    table["channel"] = pd.Series([pd.NA] * len(table), dtype="object")

    used: set[int] = set()
    counts = _allocate(int(round(ANOMALY_RATE * len(table))))
    by_cluster: dict[str, list[str]] = {}
    for station_id, cluster_id in resolved.items():
        if station_id in frames:
            by_cluster.setdefault(cluster_id, []).append(station_id)

    def _mark(idx: int, fault: str, channel: str | None) -> None:
        table.at[idx, "fault_type"] = fault
        table.at[idx, "channel"] = channel

    def _free_complete() -> list[int]:
        mask = table[["temp_c_raw", "pres_hpa_raw", "rhum_pct_raw"]].notna().all(axis=1)
        return [int(i) for i in table.index[mask] if int(i) not in used]

    placed_weather = 0
    timestamps = list(table["timestamp"].unique())
    rng.shuffle(timestamps)
    for ts in timestamps:
        if placed_weather >= counts["STORM"]:
            break
        for _cluster_id, members in by_cluster.items():
            rows = table.index[(table["timestamp"] == ts) & (table["station_id"].isin(members))].tolist()
            if len(rows) < 2 or any(i in used for i in rows):
                continue
            if not table.loc[rows, list(CHANNELS)].notna().all(axis=None):
                continue
            if placed_weather + len(rows) > counts["STORM"] + 1:
                continue
            delta_t, delta_p, delta_h = inject_storm(0.0, 0.0, 0.0, rng)
            for idx in rows:
                table.at[idx, "temp_c"] = float(table.at[idx, "temp_c"]) + delta_t
                table.at[idx, "pres_hpa"] = float(table.at[idx, "pres_hpa"]) + delta_p
                table.at[idx, "rhum_pct"] = min(100.0, float(table.at[idx, "rhum_pct"]) + delta_h)
                _mark(idx, "STORM", None)
                used.add(idx)
                placed_weather += 1
            break

    def _place_blocks(fault: str, length: int, mutate) -> None:
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
                mutate(table, block, channel)
                for idx in block:
                    _mark(idx, fault, channel)
                    used.add(idx)
                    placed += 1
                if placed >= counts[fault]:
                    break

    def _freeze(working: pd.DataFrame, block: list[int], channel: str) -> None:
        working.loc[block, channel] = inject_freeze(working.loc[block, channel].to_numpy(dtype=float), 0, duration=len(block))

    def _drift(working: pd.DataFrame, block: list[int], channel: str) -> None:
        working.loc[block, channel] = inject_drift(working.loc[block, channel].to_numpy(dtype=float), 0, duration=len(block))

    _place_blocks("DRIFT", 48, _drift)
    _place_blocks("FREEZE", 12, _freeze)

    free = _free_complete()
    rng.shuffle(free)
    spike_budget = counts["SPIKE"]
    for idx in free:
        if spike_budget <= 0:
            break
        channel = CHANNELS[int(rng.integers(0, len(CHANNELS)))]
        std = _std(table.loc[table["station_id"] == table.at[idx, "station_id"], f"{channel}_raw"], channel)
        table.at[idx, channel] = inject_spike(float(table.at[idx, channel]), std, rng)
        _mark(idx, "SPIKE", channel)
        used.add(idx)
        spike_budget -= 1

    free = _free_complete()
    rng.shuffle(free)
    comm_budget = counts["COMMUNICATION"]
    for idx in free:
        if comm_budget <= 0:
            break
        if int(rng.integers(0, 2)) == 0:
            table.at[idx, "temp_c"] = inject_comm_error()
            table.at[idx, "pres_hpa"] = inject_comm_error()
            table.at[idx, "rhum_pct"] = inject_comm_error()
            _mark(idx, "COMMUNICATION", None)
        else:
            channel = CHANNELS[int(rng.integers(0, len(CHANNELS)))]
            table.at[idx, channel] = inject_comm_error()
            _mark(idx, "COMMUNICATION", channel)
        used.add(idx)
        comm_budget -= 1

    exported = pd.DataFrame(
        {
            "station_id": table["station_id"],
            "timestamp": table["timestamp"],
            "fault_type": table["fault_type"].map(lambda value: value if pd.notna(value) else "CLEAN"),
            "temp_original": pd.to_numeric(table["temp_c_raw"], errors="coerce"),
            "rhum_original": pd.to_numeric(table["rhum_pct_raw"], errors="coerce"),
            "pres_original": pd.to_numeric(table["pres_hpa_raw"], errors="coerce"),
            "temp_corrupted": pd.to_numeric(table["temp_c"], errors="coerce"),
            "rhum_corrupted": pd.to_numeric(table["rhum_pct"], errors="coerce"),
            "pres_corrupted": pd.to_numeric(table["pres_hpa"], errors="coerce"),
        }
    )
    return exported[OUTPUT_COLS]


def _slice_for_plot(labeled: pd.DataFrame, hours: int = 120) -> pd.DataFrame:
    dirty = labeled[labeled["fault_type"] != "CLEAN"]
    station_id = dirty["station_id"].value_counts().index[0] if len(dirty) else labeled["station_id"].iloc[0]
    piece = labeled[labeled["station_id"] == station_id].sort_values("timestamp")
    station_faults = dirty[dirty["station_id"] == station_id]
    if station_faults.empty:
        return piece.head(hours)
    start = pd.to_datetime(station_faults["timestamp"].min(), utc=True) - pd.Timedelta(hours=12)
    window = piece[(piece["timestamp"] >= start) & (piece["timestamp"] < start + pd.Timedelta(hours=hours))]
    return window if len(window) >= 24 else piece.head(hours)


def plot_eval_results(labeled: pd.DataFrame, out_path: Path | str | None = None) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    out = Path(out_path or "labeled_eval.png")
    out.parent.mkdir(parents=True, exist_ok=True)

    mix = labeled["fault_type"].value_counts().reindex(CLASS_ORDER, fill_value=0)
    sample = _slice_for_plot(labeled)
    station_id = sample["station_id"].iloc[0]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8.5), constrained_layout=True)

    ax = axes[0, 0]
    ax.bar(mix.index, mix.values, color=[FAULT_COLORS[name] for name in mix.index])
    ax.set_title("Ground-truth mix (all hours)")
    ax.set_ylabel("hours")
    ax.tick_params(axis="x", rotation=25)
    ax.text(0.02, 0.95, f"clean={float((labeled['fault_type']=='CLEAN').mean()):.0%}", transform=ax.transAxes, va="top")

    series_axes = [axes[0, 1], axes[1, 0], axes[1, 1]]
    times = pd.to_datetime(sample["timestamp"], utc=True)
    for ax, (name, unit) in zip(series_axes, (("temp", "°C"), ("pres", "hPa"), ("rhum", "%"))):
        ax.plot(times, sample[f"{name}_original"], color="#4c5560", linewidth=1.2, label="original")
        ax.plot(times, sample[f"{name}_corrupted"], color="#1f6feb", linewidth=1.0, alpha=0.85, label="corrupted")
        for fault, color in FAULT_COLORS.items():
            if fault == "CLEAN":
                continue
            mask = sample["fault_type"] == fault
            if mask.any():
                ax.scatter(times[mask], sample[f"{name}_corrupted"][mask], s=18, color=color, zorder=3, label=fault)
        ax.set_title(f"{station_id} {name} ({unit})")
        ax.grid(True, alpha=0.25)

    handles = [Line2D([0], [0], color="#4c5560", label="original"), Line2D([0], [0], color="#1f6feb", label="corrupted")]
    handles.extend(Line2D([0], [0], marker="o", color="none", markerfacecolor=FAULT_COLORS[k], label=k) for k in CLASS_ORDER if k != "CLEAN")
    series_axes[0].legend(handles=handles, fontsize=8, loc="best")

    fig.suptitle("Labeled eval set — original vs injected faults (do not train on this file)", fontsize=12)
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return out


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _write_table(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        frame.to_csv(path, index=False)
        return path
    try:
        frame.to_parquet(path, index=False)
        return path
    except ImportError:
        csv_path = path.with_suffix(".csv")
        frame.to_csv(csv_path, index=False)
        return csv_path


def filter_eval_range(table: pd.DataFrame, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    frame = table.copy()
    if "timestamp" not in frame.columns:
        frame = frame.reset_index()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if "station_id" in frame.columns:
        frame["station_id"] = frame["station_id"].astype(str)
    if start:
        start_ts = pd.Timestamp(start)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize("UTC")
        frame = frame[frame["timestamp"] >= start_ts]
    if end:
        end_ts = pd.Timestamp(end)
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize("UTC")
        frame = frame[frame["timestamp"] <= end_ts]
    out = frame.copy()
    if out.empty:
        raise ValueError("No rows in the requested range")
    return out


def load_clean(path: Path, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    return filter_eval_range(_read_table(path), start=start, end=end)


def load_processed_dir(processed_dir: Path, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    files = sorted(p for p in processed_dir.glob("*.parquet") if not p.name.endswith(".clean.parquet"))
    if not files:
        raise FileNotFoundError(f"No station parquet in {processed_dir}")
    pieces = []
    for path in files:
        piece = pd.read_parquet(path)
        if "timestamp" not in piece.columns:
            piece = piece.reset_index()
        piece["station_id"] = path.stem
        pieces.append(piece)
    return filter_eval_range(pd.concat(pieces, ignore_index=True), start=start, end=end)


def run(
    clean_path: Path | None = None,
    processed_dir: Path | None = None,
    out_dir: Path | None = None,
    seed: int = DEFAULT_SEED,
    start: str | None = None,
    end: str | None = None,
    clusters: dict[str, str] | None = None,
) -> dict[str, Path]:
    if clean_path is not None:
        clean = load_clean(clean_path, start=start, end=end)
    elif processed_dir is not None:
        clean = load_processed_dir(processed_dir, start=start, end=end)
    else:
        raise ValueError("Pass --clean CSV/parquet")

    labeled = simulate_corruption(clean, seed=seed, clusters=clusters)
    out = Path(out_dir or ".")
    labeled_path = _write_table(labeled, out / f"labeled_eval_seed{seed}.csv")
    plot_path = plot_eval_results(labeled, out_path=out / f"labeled_eval_seed{seed}.png")
    print("EVAL set only — do not train on this file. Train on clean hours.")
    print(f"Wrote {len(labeled)} labeled hours to {labeled_path}")
    print(f"mix={labeled['fault_type'].value_counts().to_dict()}")
    print(f"clean_rate={float((labeled['fault_type']=='CLEAN').mean()):.3f}")
    print(f"plot: {plot_path}")
    return {"labeled": labeled_path, "plot": plot_path}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean AWS hours → labeled eval CSV with injected faults + graph. Not a training set."
    )
    parser.add_argument("--clean", type=Path, default=None, help="Clean CSV/parquet: station_id,timestamp,temp,rhum,pres")
    parser.add_argument("--processed-dir", type=Path, default=None, help="Folder of {station_id}.parquet (optional)")
    parser.add_argument("--out", type=Path, default=Path("."))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--start", default=None, help="Optional ISO start; default is all rows in --clean")
    parser.add_argument("--end", default=None, help="Optional ISO end")
    args = parser.parse_args()
    if args.clean is None and args.processed_dir is None:
        parser.error("pass --clean CSV of clean hours")
    run(
        clean_path=args.clean,
        processed_dir=args.processed_dir,
        out_dir=args.out,
        seed=args.seed,
        start=args.start,
        end=args.end,
    )


if __name__ == "__main__":
    main()
