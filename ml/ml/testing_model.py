"""
LSTM-only evaluation on held-out 2024.

Does not train. Does not run buddy check. Does not call the simulator
in-process — Roshan's CLI writes the labeled CSV, this file scores it.

    1) Export clean 2024
           python ml/testing_model.py --export-clean

    2) Inject faults (his script)
           python scripts/simulate_corruption_eval.py --clean eval_out/test_2024.csv --out ./eval_out

    3) Score the labeled CSV
           python ml/testing_model.py
           python ml/testing_model.py --labeled eval_out/labeled_eval_seed42.csv

Artifacts needed in ml/artifacts/:
    lstm_autoencoder.pt  (or .zip / .pth)
    scalers.json
    val_error_percentiles.json

Plots and tables land in ml/reports/.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, Dataset
except ImportError:
    torch = None
    nn = None
    DataLoader = None
    Dataset = None


ROOT = Path(__file__).resolve().parents[1]
ML_DIR = Path(__file__).resolve().parent
ARTIFACTS = ML_DIR / "artifacts"
REPORTS = ML_DIR / "reports"
PLOTS = REPORTS / "plots"
RAW_DIR = ROOT / "data" / "raw"
EDGES_PATH = RAW_DIR / "buddy_edges.csv"
CATALOG_PATH = RAW_DIR / "stations.csv"
EVAL_OUT = ROOT / "eval_out"
CLEAN_CSV = EVAL_OUT / "test_2024.csv"
LABELED_CSV = EVAL_OUT / "labeled_eval_seed42.csv"

FEATURES = ["temp", "rhum", "pres"]
WINDOW_HOURS = 24
TEST_START = "2024-01-01"
TEST_END = "2024-12-31 23:00:00"
INTERPOLATE_LIMIT_HOURS = 2
EVAL_STRIDE = 1
BATCH_SIZE = 256
DEFAULT_PERCENTILE = "99"

CLEAN_TOKENS = {
    "",
    "NAN",
    "NONE",
    "NULL",
    "CLEAN",
    "NORMAL",
    "OK",
    "NO_FAULT",
    "NOFAULT",
    "0",
    "FALSE",
}

FAULT_ALIASES = {
    "COMM": "COMMUNICATION",
    "COMMS": "COMMUNICATION",
    "COMMUNICATION_FAILURE": "COMMUNICATION",
    "COMM_FAILURE": "COMMUNICATION",
    "MISSING": "COMMUNICATION",
    "OUTAGE": "COMMUNICATION",
    "STUCK": "FREEZE",
    "FROZEN": "FREEZE",
    "FREEZE_FAULT": "FREEZE",
    "CALIBRATION": "DRIFT",
    "CALIBRATION_DRIFT": "DRIFT",
    "BIAS": "DRIFT",
    "WEATHER": "STORM",
    "GENUINE_WEATHER": "STORM",
    "GENUINE_WEATHER_EVENT": "STORM",
    "STORM_EVENT": "STORM",
    "SPIKE_FAULT": "SPIKE",
}

HARDWARE_FAULTS = {"SPIKE", "FREEZE", "DRIFT", "COMMUNICATION", "UNKNOWN"}
CLASS_ORDER = ["CLEAN", "SPIKE", "FREEZE", "DRIFT", "COMMUNICATION", "STORM"]
FAULT_COLORS = {
    "CLEAN": "#8a8f98",
    "SPIKE": "#e5534b",
    "FREEZE": "#3d8bfd",
    "DRIFT": "#f0a202",
    "COMMUNICATION": "#9b5de5",
    "STORM": "#2a9d8f",
    "UNKNOWN": "#6c757d",
}


if nn is not None:

    class LSTMAutoencoder(nn.Module):
        """Must match ml/notebooks/train_model.ipynb."""

        def __init__(self, n_features=3, hidden=64, latent=32):
            super().__init__()
            self.encoder = nn.LSTM(
                input_size=n_features,
                hidden_size=hidden,
                num_layers=1,
                batch_first=True,
            )
            self.to_latent = nn.Linear(hidden, latent)
            self.decoder = nn.LSTM(
                input_size=latent,
                hidden_size=hidden,
                num_layers=1,
                batch_first=True,
            )
            self.to_output = nn.Linear(hidden, n_features)

        def encode(self, x):
            _, (h_n, _) = self.encoder(x)
            return torch.tanh(self.to_latent(h_n[-1]))

        def decode(self, z, seq_len):
            dec_in = z.unsqueeze(1).repeat(1, seq_len, 1)
            dec_out, _ = self.decoder(dec_in)
            return self.to_output(dec_out)

        def forward(self, x):
            return self.decode(self.encode(x), x.size(1))

    class WindowDataset(Dataset):
        def __init__(self, scaled: dict, index: list, window: int = WINDOW_HOURS):
            self.scaled = scaled
            self.index = index
            self.window = window

        def __len__(self):
            return len(self.index)

        def __getitem__(self, i):
            sid, start = self.index[i]
            x = self.scaled[sid][start : start + self.window]
            return torch.from_numpy(np.nan_to_num(x, nan=0.0))

else:
    LSTMAutoencoder = None
    WindowDataset = None


def normalize_fault_type(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if pd.isna(value):
        return None
    text = str(value).strip().upper().replace(" ", "_").replace("-", "_")
    if text in CLEAN_TOKENS:
        return None
    return FAULT_ALIASES.get(text, text)


def to_naive_series(values) -> pd.Series:
    """Wall-clock hours, no timezone. Simulator tags naive CSV as UTC."""
    s = values if isinstance(values, pd.Series) else pd.Series(values)
    ts = pd.to_datetime(s, utc=True, errors="coerce")
    try:
        out = ts.dt.tz_convert("UTC").dt.tz_localize(None)
    except (TypeError, ValueError, AttributeError):
        try:
            out = ts.dt.tz_localize(None)
        except (TypeError, ValueError, AttributeError):
            out = pd.to_datetime(ts.values)
            out = pd.Series(out, index=s.index)
            return out
    out.index = s.index
    return out


def buddy_cluster_map() -> dict[str, str]:
    if not CATALOG_PATH.exists():
        return {}
    catalog = pd.read_csv(CATALOG_PATH, dtype={"station_id": str})
    parent = {str(s): str(s) for s in catalog["station_id"].astype(str)}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    if EDGES_PATH.exists():
        edges = pd.read_csv(EDGES_PATH, dtype=str)
        exported = set(parent)
        for _, row in edges.iterrows():
            a = str(row["primary_station_id"])
            b = str(row["buddy_station_id"])
            if a in exported and b in exported:
                union(a, b)
    return {sid: find(sid) for sid in parent}


def export_clean_2024(out_path: Path = CLEAN_CSV) -> Path:
    """Write naive 2024 hours for the simulator: station_id, timestamp, T/H/P, cluster_id."""
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(f"Missing catalog {CATALOG_PATH}")
    catalog = pd.read_csv(CATALOG_PATH, dtype={"station_id": str})
    clusters = buddy_cluster_map()
    frames = []
    missing = []
    for sid in catalog["station_id"].astype(str):
        path = RAW_DIR / f"{sid}.csv"
        if not path.exists():
            missing.append(path.name)
            continue
        df = pd.read_csv(path)
        df["station_id"] = str(sid)
        df["timestamp"] = to_naive_series(df["timestamp"])
        df = df.sort_values("timestamp").drop_duplicates("timestamp")
        df = df.set_index("timestamp").loc[TEST_START:TEST_END].reset_index()
        for col in FEATURES:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["cluster_id"] = clusters.get(str(sid), str(sid))
        frames.append(df[["station_id", "timestamp", *FEATURES, "cluster_id"]])
    if not frames:
        raise FileNotFoundError(f"No station CSVs under {RAW_DIR}")
    if missing:
        warnings.warn(f"skipped missing station files: {missing[:8]}...")
    out = pd.concat(frames, ignore_index=True)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"Wrote {len(out)} clean 2024 hours → {out_path}")
    print(f"stations={out['station_id'].nunique()}  clusters={out['cluster_id'].nunique()}")
    print("Next:")
    print(
        "  python scripts/simulate_corruption_eval.py "
        f"--clean {out_path.as_posix()} --out {out_path.parent.as_posix()}"
    )
    return out_path


def load_labeled_eval(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path, dtype={"station_id": str}, low_memory=False)
    df.columns = [str(c).strip() for c in df.columns]
    needed = {
        "station_id",
        "timestamp",
        "fault_type",
        "temp_original",
        "rhum_original",
        "pres_original",
        "temp_corrupted",
        "rhum_corrupted",
        "pres_corrupted",
    }
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(
            f"{path} is missing columns {sorted(missing)}. "
            "Expected the CSV from simulate_corruption_eval.py."
        )
    df["station_id"] = df["station_id"].astype(str)
    df["timestamp"] = to_naive_series(df["timestamp"])
    for col in (
        "temp_original",
        "rhum_original",
        "pres_original",
        "temp_corrupted",
        "rhum_corrupted",
        "pres_corrupted",
    ):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["temp"] = df["temp_corrupted"]
    df["rhum"] = df["rhum_corrupted"]
    df["pres"] = df["pres_corrupted"]
    df["fault_type"] = df["fault_type"].map(normalize_fault_type)
    return (
        df.drop_duplicates(["station_id", "timestamp"], keep="last")
        .sort_values(["station_id", "timestamp"])
        .reset_index(drop=True)
    )


def interpolate_short_gaps(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in FEATURES:
        out[col] = pd.to_numeric(out[col], errors="coerce")
        out[col] = out[col].interpolate(
            method="linear",
            limit=INTERPOLATE_LIMIT_HOURS,
            limit_area="inside",
        )
    return out


def complete_mask(df: pd.DataFrame) -> pd.Series:
    return df[FEATURES].notna().all(axis=1)


def apply_minmax(df: pd.DataFrame, stats: dict) -> np.ndarray:
    arr = df[FEATURES].to_numpy(dtype=np.float64)
    vmin = np.array(stats["min"], dtype=np.float64)
    vr = np.array(stats["range"], dtype=np.float64)
    vr = np.where(vr == 0, 1.0, vr)
    return ((arr - vmin) / vr).astype(np.float32)


def inverse_minmax(arr: np.ndarray, stats: dict) -> np.ndarray:
    vmin = np.array(stats["min"], dtype=np.float64)
    vr = np.array(stats["range"], dtype=np.float64)
    return arr * vr + vmin


def valid_window_starts(complete: np.ndarray, stride: int, window: int = WINDOW_HOURS):
    n = len(complete)
    if n < window:
        return np.array([], dtype=np.int32)
    c = complete.astype(np.int32)
    cs = np.concatenate([[0], np.cumsum(c)])
    starts = []
    for i in range(0, n - window + 1, stride):
        if cs[i + window] - cs[i] == window:
            starts.append(i)
    return np.asarray(starts, dtype=np.int32)


def resolve_weights_path() -> Path | None:
    for name in ("lstm_autoencoder.pt", "lstm_autoencoder.pth", "lstm_autoencoder.zip"):
        candidate = ARTIFACTS / name
        if candidate.is_file():
            return candidate
    return None


def load_artifacts():
    if torch is None:
        raise ImportError("torch is required to score windows. pip install torch")
    weights_path = resolve_weights_path()
    scalers_path = ARTIFACTS / "scalers.json"
    pct_path = ARTIFACTS / "val_error_percentiles.json"
    meta_path = ARTIFACTS / "model_metadata.json"

    required = [p for p in (scalers_path, pct_path) if not p.exists()]
    if weights_path is None:
        required.append(ARTIFACTS / "lstm_autoencoder.pt")
    if required:
        raise FileNotFoundError(
            "Missing artifacts. Copy Kaggle outputs into ml/artifacts/. "
            f"Missing: {[p.name for p in required]}"
        )

    try:
        ckpt = torch.load(weights_path, map_location="cpu", weights_only=False)
    except TypeError:
        ckpt = torch.load(weights_path, map_location="cpu")
    if isinstance(ckpt, dict) and "state_dict" in ckpt:
        state = ckpt["state_dict"]
        hidden = int(ckpt.get("hidden", 64))
        latent = int(ckpt.get("latent", 32))
        n_features = int(ckpt.get("n_features", 3))
    else:
        state = ckpt
        hidden, latent, n_features = 64, 32, 3

    model = LSTMAutoencoder(n_features=n_features, hidden=hidden, latent=latent)
    model.load_state_dict(state)
    model.eval()

    with open(scalers_path, encoding="utf-8") as f:
        scalers = json.load(f)
    scalers = {str(k): v for k, v in scalers.items()}

    with open(pct_path, encoding="utf-8") as f:
        percentiles = json.load(f)

    metadata = {}
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            metadata = json.load(f)

    print(f"loaded weights {weights_path.name}")
    return model, scalers, percentiles, metadata


def score_windows(model, scaled, index, device):
    ds = WindowDataset(scaled, index)
    loader = DataLoader(ds, batch_size=BATCH_SIZE, shuffle=False)
    window_mse = []
    last_mse = []
    model = model.to(device)
    model.eval()
    with torch.no_grad():
        for batch in loader:
            batch = batch.to(device)
            recon = model(batch)
            err = (recon - batch) ** 2
            window_mse.append(err.mean(dim=(1, 2)).cpu().numpy())
            last_mse.append(err[:, -1, :].mean(dim=1).cpu().numpy())
    return np.concatenate(window_mse), np.concatenate(last_mse)


def metrics_from_scores(y_true, scores, threshold):
    y_true = np.asarray(y_true).astype(int)
    scores = np.asarray(scores)
    y_pred = (scores >= threshold).astype(int)
    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    fpr = fp / (fp + tn) if (fp + tn) else float("nan")
    auc = _roc_auc(y_true, scores)
    ap = _pr_auc(y_true, scores)
    return {
        "n": int(len(y_true)),
        "positives": int(y_true.sum()),
        "negatives": int((1 - y_true).sum()),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "fpr": None if math.isnan(fpr) else round(fpr, 4),
        "roc_auc": None if auc is None else round(auc, 4),
        "pr_auc": None if ap is None else round(ap, 4),
        "threshold": float(threshold),
    }


def _trapz(y, x) -> float:
    fn = getattr(np, "trapezoid", None) or np.trapz
    return float(fn(y, x))


def _roc_points(y_true, scores):
    y = np.asarray(y_true).astype(int)
    s = np.asarray(scores, dtype=np.float64)
    if y.min() == y.max() or len(y) == 0:
        return None, None, None
    order = np.argsort(-s, kind="mergesort")
    y = y[order]
    tp = np.cumsum(y)
    fp = np.cumsum(1 - y)
    positives = int(y.sum())
    negatives = int(len(y) - positives)
    if positives == 0 or negatives == 0:
        return None, None, None
    tpr = np.r_[0.0, tp / positives]
    fpr = np.r_[0.0, fp / negatives]
    auc = _trapz(tpr, fpr)
    return fpr, tpr, auc


def _pr_points(y_true, scores):
    y = np.asarray(y_true).astype(int)
    s = np.asarray(scores, dtype=np.float64)
    if y.min() == y.max() or len(y) == 0:
        return None, None, None
    order = np.argsort(-s, kind="mergesort")
    y = y[order]
    tp = np.cumsum(y)
    fp = np.cumsum(1 - y)
    positives = int(y.sum())
    if positives == 0:
        return None, None, None
    recall = tp / positives
    precision = tp / np.maximum(tp + fp, 1)
    recall = np.r_[0.0, recall]
    precision = np.r_[1.0, precision]
    ap = _trapz(precision, recall)
    return recall, precision, ap


def _roc_auc(y_true, scores):
    _, _, auc = _roc_points(y_true, scores)
    return auc


def _pr_auc(y_true, scores):
    _, _, ap = _pr_points(y_true, scores)
    return ap


def print_metrics(title, m):
    print(f"\n{title}")
    print("-" * len(title))
    print(
        f"n={m['n']}  pos={m['positives']}  neg={m['negatives']}  "
        f"th={m['threshold']:.6g}"
    )
    print(
        f"P={m['precision']:.4f}  R={m['recall']:.4f}  F1={m['f1']:.4f}  "
        f"FPR={m['fpr']}  ROC-AUC={m['roc_auc']}  PR-AUC={m['pr_auc']}"
    )
    print(f"TP={m['tp']} FP={m['fp']} TN={m['tn']} FN={m['fn']}")


def _label_name(v) -> str:
    return "CLEAN" if v is None else str(v)


def pick_example_indices(y_fault, window_mse):
    """One window per class: lowest MSE for CLEAN, highest for faults."""
    chosen = {}
    y_fault = np.asarray(y_fault, dtype=object)
    for kind in [None, "SPIKE", "FREEZE", "DRIFT", "COMMUNICATION", "STORM"]:
        mask = np.array([(v is None) if kind is None else (v == kind) for v in y_fault])
        if not mask.any():
            continue
        idxs = np.flatnonzero(mask)
        pick = int(idxs[np.argmin(window_mse[idxs])] if kind is None else idxs[np.argmax(window_mse[idxs])])
        chosen[_label_name(kind)] = pick
    return chosen


def save_plots(
    *,
    y_fault,
    window_mse,
    threshold,
    overall,
    per_fault,
    sweep_rows,
    y_true,
    scores,
    index,
    frames,
    scaled,
    scalers,
    model,
    device,
    storm_rate,
):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    PLOTS.mkdir(parents=True, exist_ok=True)
    y_name = np.array([_label_name(v) for v in y_fault])
    flagged = window_mse >= threshold

    # 1) Score histogram
    fig, ax = plt.subplots(figsize=(9, 5))
    bins = np.linspace(0, np.quantile(window_mse, 0.995), 60)
    for kind in CLASS_ORDER:
        vals = window_mse[y_name == kind]
        if len(vals) == 0:
            continue
        ax.hist(
            vals,
            bins=bins,
            histtype="step",
            density=True,
            linewidth=1.6,
            color=FAULT_COLORS.get(kind, "#444"),
            label=f"{kind} n={len(vals)}",
        )
    ax.axvline(threshold, color="#111", ls="--", lw=1.2, label=f"val p{DEFAULT_PERCENTILE} th")
    ax.set_xlabel("window MSE (scaled)")
    ax.set_ylabel("density")
    ax.set_title("2024 window MSE by last-hour ground truth")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(PLOTS / "score_hist_by_label.png", dpi=140)
    plt.close(fig)

    # 2) Boxplot
    fig, ax = plt.subplots(figsize=(8, 5))
    data, labels, colors = [], [], []
    for kind in CLASS_ORDER:
        vals = window_mse[y_name == kind]
        if len(vals) == 0:
            continue
        data.append(vals)
        labels.append(kind)
        colors.append(FAULT_COLORS[kind])
    if data:
        try:
            bp = ax.boxplot(data, tick_labels=labels, showfliers=False, patch_artist=True)
        except TypeError:
            bp = ax.boxplot(data, labels=labels, showfliers=False, patch_artist=True)
        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.55)
        ax.axhline(threshold, color="#111", ls="--", lw=1.2, label="threshold")
        ax.set_ylabel("window MSE (scaled)")
        ax.set_title("Reconstruction error by injected fault")
        ax.legend(fontsize=8)
        ax.grid(True, axis="y", alpha=0.25)
        fig.tight_layout()
        fig.savefig(PLOTS / "mse_box_by_fault.png", dpi=140)
    plt.close(fig)

    # 3) Per-fault bars
    fig, ax = plt.subplots(figsize=(8, 4.5))
    names, recs, f1s, precs = [], [], [], []
    for fault in ["SPIKE", "FREEZE", "DRIFT", "COMMUNICATION"]:
        m = per_fault.get(fault) or {}
        if "recall" not in m:
            continue
        names.append(fault)
        recs.append(m["recall"])
        f1s.append(m["f1"])
        precs.append(m["precision"])
    if names:
        x = np.arange(len(names))
        w = 0.25
        ax.bar(x - w, precs, w, label="precision", color="#4c5560")
        ax.bar(x, recs, w, label="recall", color="#1f6feb")
        ax.bar(x + w, f1s, w, label="F1", color="#2a9d8f")
        ax.set_xticks(x)
        ax.set_xticklabels(names)
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("score")
        ax.set_title("Hardware faults vs clean (LSTM only, last-hour label)")
        ax.legend()
        ax.grid(True, axis="y", alpha=0.25)
        fig.tight_layout()
        fig.savefig(PLOTS / "per_fault_metrics.png", dpi=140)
    plt.close(fig)

    # 4) Threshold sweep
    if sweep_rows:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        xs = [str(r.get("val_percentile", i)) for i, r in enumerate(sweep_rows)]
        ax.plot(xs, [r["precision"] for r in sweep_rows], marker="o", label="precision")
        ax.plot(xs, [r["recall"] for r in sweep_rows], marker="o", label="recall")
        ax.plot(xs, [r["f1"] for r in sweep_rows], marker="o", label="F1")
        fprs = [r["fpr"] if r["fpr"] is not None else np.nan for r in sweep_rows]
        ax.plot(xs, fprs, marker="o", label="FPR")
        ax.set_xlabel("val window-MSE percentile used as threshold")
        ax.set_ylabel("2024 metric")
        ax.set_title("Threshold sweep (percentiles frozen on 2023 val)")
        ax.set_ylim(0, 1.05)
        ax.legend()
        ax.grid(True, alpha=0.25)
        fig.tight_layout()
        fig.savefig(PLOTS / "threshold_sweep.png", dpi=140)
        plt.close(fig)

    # 5) ROC + PR
    fpr, tpr, auc = _roc_points(y_true, scores)
    rec, prec, ap = _pr_points(y_true, scores)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    if fpr is not None:
        axes[0].plot(fpr, tpr, color="#1f6feb", label=f"AUC={auc:.3f}")
        axes[0].plot([0, 1], [0, 1], color="#888", ls="--", lw=1)
        axes[0].legend()
    axes[0].set_xlabel("FPR")
    axes[0].set_ylabel("TPR")
    axes[0].set_title("ROC — hardware vs clean")
    axes[0].grid(True, alpha=0.25)
    if rec is not None:
        axes[1].plot(rec, prec, color="#e5534b", label=f"AP={ap:.3f}")
        axes[1].legend()
    axes[1].set_xlabel("recall")
    axes[1].set_ylabel("precision")
    axes[1].set_title("PR — hardware vs clean")
    axes[1].grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(PLOTS / "roc_pr.png", dpi=140)
    plt.close(fig)

    # 6) Detection rate by label
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    kinds, rates, counts = [], [], []
    for kind in CLASS_ORDER:
        mask = y_name == kind
        if not mask.any():
            continue
        kinds.append(kind)
        rates.append(float(flagged[mask].mean()))
        counts.append(int(mask.sum()))
    ax.bar(kinds, rates, color=[FAULT_COLORS[k] for k in kinds])
    for i, (rate, n) in enumerate(zip(rates, counts)):
        ax.text(i, min(rate + 0.03, 1.0), f"{rate:.2f}\nn={n}", ha="center", va="bottom", fontsize=8)
    ax.axhline(overall.get("fpr") or 0.0, color="#111", ls=":", lw=1, label="clean FPR")
    if storm_rate is not None:
        ax.axhline(storm_rate, color=FAULT_COLORS["STORM"], ls="--", lw=1, label="storm flag rate")
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("fraction of windows ≥ threshold")
    ax.set_title("LSTM flag rate by ground-truth last hour")
    ax.legend(fontsize=8)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(PLOTS / "flag_rate_by_label.png", dpi=140)
    plt.close(fig)

    # 7) Reconstruction examples (temperature)
    examples = pick_example_indices(y_fault, window_mse)
    if examples and torch is not None and model is not None:
        n = len(examples)
        fig, axes = plt.subplots(n, 1, figsize=(9, 2.2 * n), sharex=True)
        if n == 1:
            axes = [axes]
        hours = np.arange(WINDOW_HOURS)
        model = model.to(device)
        model.eval()
        for ax, (kind, idx) in zip(axes, examples.items()):
            sid, start = index[idx]
            stats = scalers[sid]
            x = scaled[sid][start : start + WINDOW_HOURS]
            xt = torch.from_numpy(np.nan_to_num(x, nan=0.0)).unsqueeze(0).to(device)
            with torch.no_grad():
                recon = model(xt).squeeze(0).cpu().numpy()
            obs = inverse_minmax(x, stats)
            hat = inverse_minmax(recon, stats)
            ax.plot(hours, obs[:, 0], color="#1f6feb", lw=1.8, label="observed (corrupted)")
            ax.plot(hours, hat[:, 0], color="#e5534b", lw=1.6, ls="--", label="LSTM recon")
            orig = frames[sid]
            if "temp_original" in orig.columns:
                orig_t = orig["temp_original"].to_numpy()[start : start + WINDOW_HOURS]
                ax.plot(hours, orig_t, color="#8a8f98", lw=1.1, alpha=0.85, label="original clean")
            mse = window_mse[idx]
            ax.set_ylabel("temp °C")
            ax.set_title(
                f"{kind}  {sid}  mse={mse:.4f}  "
                f"{'FLAGGED' if mse >= threshold else 'below th'}"
            )
            ax.grid(True, alpha=0.25)
            ax.legend(fontsize=7, loc="upper right")
        axes[-1].set_xlabel("hour in 24h window")
        fig.tight_layout()
        fig.savefig(PLOTS / "recon_examples_temp.png", dpi=140)
        plt.close(fig)

        # 8) Full T/H/P for the worst hardware window if any
        hw_idx = [
            i
            for i, v in enumerate(y_fault)
            if v in HARDWARE_FAULTS
        ]
        if hw_idx:
            worst = hw_idx[int(np.argmax(window_mse[hw_idx]))]
            sid, start = index[worst]
            stats = scalers[sid]
            x = scaled[sid][start : start + WINDOW_HOURS]
            xt = torch.from_numpy(np.nan_to_num(x, nan=0.0)).unsqueeze(0).to(device)
            with torch.no_grad():
                recon = model(xt).squeeze(0).cpu().numpy()
            obs = inverse_minmax(x, stats)
            hat = inverse_minmax(recon, stats)
            kind = _label_name(y_fault[worst])
            fig, axes = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
            orig_df = frames[sid]
            for i, (ax, name, unit) in enumerate(
                zip(axes, FEATURES, ("°C", "%", "hPa"))
            ):
                ax.plot(hours, obs[:, i], color="#1f6feb", lw=1.8, label="observed")
                ax.plot(hours, hat[:, i], color="#e5534b", lw=1.6, ls="--", label="reconstructed")
                ocol = f"{name}_original"
                if ocol in orig_df.columns:
                    ax.plot(
                        hours,
                        orig_df[ocol].to_numpy()[start : start + WINDOW_HOURS],
                        color="#8a8f98",
                        lw=1.1,
                        label="original",
                    )
                ax.set_ylabel(f"{name} ({unit})")
                ax.grid(True, alpha=0.25)
                ax.legend(fontsize=7, loc="upper right")
            axes[0].set_title(
                f"Worst hardware window — {kind} {sid}  mse={window_mse[worst]:.4f}"
            )
            axes[-1].set_xlabel("hour in 24h window")
            fig.tight_layout()
            fig.savefig(PLOTS / "recon_worst_hardware.png", dpi=140)
            plt.close(fig)

    print("Wrote plots →", PLOTS)


def build_windows(observed: pd.DataFrame, scalers: dict):
    frames = {}
    labels = {}
    for sid, grp in observed.groupby("station_id"):
        g = grp.sort_values("timestamp").drop_duplicates("timestamp")
        g = g.set_index("timestamp")
        g = interpolate_short_gaps(g)
        frames[str(sid)] = g
        labels[str(sid)] = g["fault_type"]

    scaled = {}
    index = []
    last_labels = []
    skipped_no_scaler = 0
    for sid, df in frames.items():
        if sid not in scalers:
            skipped_no_scaler += 1
            continue
        scaled[sid] = apply_minmax(df, scalers[sid])
        comp = complete_mask(df).to_numpy()
        starts = valid_window_starts(comp, stride=EVAL_STRIDE)
        lab = labels[sid].to_numpy()
        for s in starts:
            index.append((sid, int(s)))
            last_labels.append(lab[s + WINDOW_HOURS - 1])
    return frames, scaled, index, last_labels, skipped_no_scaler


def run_eval(labeled_path: Path):
    REPORTS.mkdir(parents=True, exist_ok=True)
    PLOTS.mkdir(parents=True, exist_ok=True)
    if torch is None:
        raise ImportError("torch is required. pip install torch")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("device:", device)

    model, scalers, percentiles, metadata = load_artifacts()
    print("loaded artifacts from", ARTIFACTS)
    print("kaggle test_used?", metadata.get("test_used_in_this_notebook"))

    threshold = float(percentiles["window_mse"][DEFAULT_PERCENTILE])
    print(
        f"operating threshold = val window MSE p{DEFAULT_PERCENTILE} "
        f"= {threshold:.6g}  (not tuned on 2024)"
    )

    observed = load_labeled_eval(labeled_path)
    print("labeled rows:", len(observed), "stations:", observed["station_id"].nunique())
    print("fault_type counts (hour-level, CLEAN=NaN here):")
    print(observed["fault_type"].value_counts(dropna=False).to_string())

    n_clean = int(observed["fault_type"].isna().sum())
    n_hw = int(observed["fault_type"].isin(HARDWARE_FAULTS).sum())
    if n_clean == 0:
        warnings.warn("No CLEAN hours after simulation. FPR cannot be measured.")
    print(f"clean hours={n_clean}  hardware-fault hours={n_hw}")

    frames, scaled, index, last_labels, skipped_no_scaler = build_windows(
        observed, scalers
    )
    print("windows:", len(index), "| stations missing scaler:", skipped_no_scaler)
    if not index:
        raise RuntimeError("No complete 24h windows on the labeled 2024 series.")

    window_mse, _last_mse = score_windows(model, scaled, index, device)
    y_fault = np.array([normalize_fault_type(v) for v in last_labels], dtype=object)

    hardware_mask = np.array(
        [(v in HARDWARE_FAULTS) if v is not None else False for v in y_fault]
    )
    clean_mask = np.array([v is None for v in y_fault])
    storm_mask = np.array([v == "STORM" for v in y_fault])

    eval_mask = hardware_mask | clean_mask
    y_true = hardware_mask[eval_mask].astype(int)
    scores = window_mse[eval_mask]
    if len(y_true) == 0:
        raise RuntimeError("No clean or hardware-labeled windows to score.")

    overall = metrics_from_scores(y_true, scores, threshold)
    print_metrics("OVERALL (hardware faults vs clean, 2024, last-hour label)", overall)

    per_fault = {}
    for fault in ["SPIKE", "FREEZE", "DRIFT", "COMMUNICATION", "UNKNOWN"]:
        pos = np.array([v == fault for v in y_fault])
        mask = pos | clean_mask
        if pos.sum() == 0:
            per_fault[fault] = {
                "n_positives": 0,
                "note": "no windows with this last-hour label",
            }
            continue
        m = metrics_from_scores(pos[mask].astype(int), window_mse[mask], threshold)
        per_fault[fault] = m
        print_metrics(f"{fault} vs clean", m)

    storm_rate = None
    if storm_mask.any():
        storm_rate = float((window_mse[storm_mask] >= threshold).mean())
        print(
            f"\nSTORM windows={int(storm_mask.sum())}  "
            f"LSTM flagged as unusual={storm_rate:.4f}  "
            "(not counted in overall hardware F1)"
        )

    sweep_rows = []
    for p in ["95", "97.5", "99", "99.5", "99.9"]:
        if p not in percentiles.get("window_mse", {}):
            continue
        th = float(percentiles["window_mse"][p])
        m = metrics_from_scores(y_true, scores, th)
        m["val_percentile"] = p
        sweep_rows.append(m)
        print_metrics(f"val p{p} on 2024", m)

    payload = {
        "labeled_csv": str(labeled_path),
        "split": "2024-01-01/2024-12-31",
        "labeling": "last_hour_of_24h_window",
        "score": "window_mse",
        "default_threshold_source": f"val_window_mse_p{DEFAULT_PERCENTILE}",
        "overall": overall,
        "per_fault": per_fault,
        "storm_flag_rate": storm_rate,
        "val_percentile_sweep_on_2024": sweep_rows,
        "n_windows": len(index),
        "n_clean_windows": int(clean_mask.sum()),
        "n_hardware_windows": int(hardware_mask.sum()),
        "n_storm_windows": int(storm_mask.sum()),
    }

    out_json = REPORTS / "lstm_test_2024_metrics.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    rows = [{"fault": "OVERALL", **overall}]
    for k, v in per_fault.items():
        if "precision" in v:
            rows.append({"fault": k, **v})
    pd.DataFrame(rows).to_csv(REPORTS / "lstm_test_2024_metrics.csv", index=False)
    if sweep_rows:
        pd.DataFrame(sweep_rows).to_csv(
            REPORTS / "lstm_test_2024_threshold_sweep.csv", index=False
        )

    window_table = pd.DataFrame(
        {
            "station_id": [sid for sid, _ in index],
            "start_iloc": [s for _, s in index],
            "fault_last_hour": [_label_name(v) for v in y_fault],
            "window_mse": window_mse,
            "flagged": window_mse >= threshold,
        }
    )
    window_table.to_csv(REPORTS / "lstm_test_2024_windows.csv", index=False)

    save_plots(
        y_fault=y_fault,
        window_mse=window_mse,
        threshold=threshold,
        overall=overall,
        per_fault=per_fault,
        sweep_rows=sweep_rows,
        y_true=y_true,
        scores=scores,
        index=index,
        frames=frames,
        scaled=scaled,
        scalers=scalers,
        model=model,
        device=device,
        storm_rate=storm_rate,
    )

    print("\nWrote", out_json)
    print("Wrote", REPORTS / "lstm_test_2024_metrics.csv")
    print("Wrote", PLOTS)


def _missing_labeled_message(path: Path) -> str:
    return (
        f"Labeled eval CSV not found: {path}\n\n"
        "Run these from the repo root, in order:\n"
        "  python ml/testing_model.py --export-clean\n"
        "  python scripts/simulate_corruption_eval.py "
        "--clean eval_out/test_2024.csv --out ./eval_out\n"
        "  python ml/testing_model.py\n"
    )


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Export clean 2024 or score labeled eval CSV.")
    p.add_argument(
        "--export-clean",
        action="store_true",
        help="Write eval_out/test_2024.csv and exit (no model, no simulator).",
    )
    p.add_argument(
        "--clean-out",
        type=Path,
        default=CLEAN_CSV,
        help="Where --export-clean writes the clean CSV.",
    )
    p.add_argument(
        "--labeled",
        type=Path,
        default=LABELED_CSV,
        help="Labeled CSV from simulate_corruption_eval.py",
    )
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.export_clean:
        export_clean_2024(args.clean_out)
        return 0
    labeled = Path(args.labeled)
    if not labeled.exists():
        print(_missing_labeled_message(labeled), file=sys.stderr)
        return 2
    run_eval(labeled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
