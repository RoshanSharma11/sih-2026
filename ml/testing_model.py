"""
LSTM-only evaluation on held-out 2024.

Does not train. Does not run buddy check.

    RAW 2024 (clean)
        -> simulate_corruption(df, seed=42)
        -> same preprocess as Kaggle (short interpolate, 24h windows)
        -> station-wise MinMax from ml/artifacts/scalers.json
        -> bottleneck LSTM-AE
        -> Precision / Recall / F1 / FPR / AUC
        -> per-fault breakdown

Put Kaggle outputs in ml/artifacts/ first:
    lstm_autoencoder.pt
    scalers.json
    val_error_percentiles.json
    model_metadata.json

Drop your friend's simulator in one of:
    ml/simulator.py
    simulator.py          (repo root)

Expected function:

    simulate_corruption(clean_df, seed=42) -> DataFrame

See ASSUMPTIONS in the module docstring below, and the comment block
in import_simulate_corruption().

Run from repo root:

    python ml/testing_model.py
"""

from __future__ import annotations

import importlib
import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset


# =============================================================================
# ASSUMPTIONS ABOUT simulate_corruption
# =============================================================================
#
# 1. Signature
#       simulate_corruption(clean_df: pd.DataFrame, seed: int = 42) -> object
#    `seed` is honored; seed=42 always yields the same corruptions.
#
# 2. Input clean_df (we pass this)
#       columns: station_id, timestamp, temp, rhum, pres
#       units: raw °C, %, hPa  — NOT scaled
#       2024 hours only
#       may contain source-missing NaNs (the 80% completeness holes)
#
# 3. Return value — one of:
#       a) DataFrame with the columns you specified:
#            station_id, timestamp, fault_type,
#            temp_original, rhum_original, pres_original,
#            temp_corrupted, rhum_corrupted, pres_corrupted
#       b) Same idea, alternate names we also accept:
#            clean_temp / observed_temp, temp_clean / temp_obs, etc.
#       c) Tuple (corrupted_df, labels_df) or dict with a DataFrame inside
#          — we take the first DataFrame we can find.
#
# 4. Row coverage
#       Preferred: one row per input timestamp (full series).
#       Also accepted: only corrupted rows. We left-join back onto 2024;
#       unmatched hours are treated as CLEAN with original==corrupted.
#
# 5. fault_type
#       Clean hours: NaN / "" / CLEAN / NONE / NORMAL / OK
#       Fault hours (case-insensitive):
#            SPIKE, FREEZE, DRIFT, COMMUNICATION (aliases: COMM, COMM_FAILURE,
#            MISSING), STORM (aliases: WEATHER, GENUINE_WEATHER)
#       If fault_type is empty but original != corrupted, we label UNKNOWN.
#
# 6. Communication failure
#       Corrupted T/H/P are NaN. We then apply the same ≤2h interpolate as
#       training, so a 1–2 hour outage can be filled and the LSTM may not
#       see it. Outages longer than 2h break the window and cannot be scored
#       by the LSTM. That is expected; comms is a Tier-1 problem.
#
# 7. The simulator does NOT normalize, drop timestamps, or fit a scaler.
#
# 8. Mix of clean + faulty hours
#       We need CLEAN negatives to measure FPR. If every hour is a fault,
#       overall FPR is undefined and we warn.
#
# 9. Window label = fault_type of the LAST hour in the 24h window
#       Matches hourly ingest (score the new observation). Storms are
#       reported separately and excluded from overall hardware F1.
#
# =============================================================================

ROOT = Path(__file__).resolve().parents[1]
ML_DIR = Path(__file__).resolve().parent
ARTIFACTS = ML_DIR / "artifacts"
REPORTS = ML_DIR / "reports"
RAW_DIR = ROOT / "data" / "raw"

FEATURES = ["temp", "rhum", "pres"]
WINDOW_HOURS = 24
TEST_START = "2024-01-01"
TEST_END = "2024-12-31 23:00:00"
INTERPOLATE_LIMIT_HOURS = 2
EVAL_STRIDE = 1
BATCH_SIZE = 256
SEED = 42
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


def import_simulate_corruption():
    """
    Load simulate_corruption from the friend's module.

    We try, in order:
        ml.simulator
        simulator
        simulate_corruption   (module of the same name)
    """
    sys.path.insert(0, str(ML_DIR))
    sys.path.insert(0, str(ROOT))

    errors = []
    for mod_name in ("simulator", "ml.simulator", "simulate_corruption"):
        try:
            mod = importlib.import_module(mod_name)
        except ImportError as exc:
            errors.append(f"{mod_name}: {exc}")
            continue
        fn = getattr(mod, "simulate_corruption", None)
        if callable(fn):
            print(f"Loaded simulate_corruption from {mod_name}")
            return fn
        errors.append(f"{mod_name}: no simulate_corruption()")

    raise ImportError(
        "Could not import simulate_corruption.\n"
        "Put your friend's file at ml/simulator.py (or repo-root simulator.py) "
        "with:\n\n"
        "    def simulate_corruption(clean_df, seed=42):\n"
        "        ...\n"
        "        return dataframe  # columns listed in this file's docstring\n\n"
        "Tried:\n  " + "\n  ".join(errors)
    )


def normalize_fault_type(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if pd.isna(value):
        return None
    text = str(value).strip().upper().replace(" ", "_").replace("-", "_")
    if text in CLEAN_TOKENS:
        return None
    return FAULT_ALIASES.get(text, text)


def _pick_col(df: pd.DataFrame, names: list[str]):
    lower = {c.lower(): c for c in df.columns}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _first_dataframe(obj):
    if isinstance(obj, pd.DataFrame):
        return obj
    if isinstance(obj, (tuple, list)):
        for item in obj:
            if isinstance(item, pd.DataFrame):
                return item
    if isinstance(obj, dict):
        for key in (
            "result",
            "data",
            "corrupted",
            "df",
            "labels",
            "ground_truth",
        ):
            if key in obj and isinstance(obj[key], pd.DataFrame):
                return obj[key]
        for val in obj.values():
            if isinstance(val, pd.DataFrame):
                return val
    raise TypeError(
        "simulate_corruption must return a DataFrame, or a tuple/dict "
        "containing one. Got: " + type(obj).__name__
    )


def canonicalize_simulator_output(raw_obj, clean_df: pd.DataFrame) -> pd.DataFrame:
    """
    Start from full clean 2024, overlay simulator rows.

    Output columns:
        station_id, timestamp, fault_type,
        temp, rhum, pres                         (observed / corrupted)
        temp_original, rhum_original, pres_original
    """
    sim = _first_dataframe(raw_obj).copy()
    sim.columns = [str(c).strip() for c in sim.columns]

    sid_col = _pick_col(sim, ["station_id", "station", "id"])
    ts_col = _pick_col(sim, ["timestamp", "time", "datetime"])
    if sid_col is None or ts_col is None:
        raise ValueError(
            "Simulator output needs station_id and timestamp. "
            f"Got: {list(sim.columns)}"
        )

    fault_col = _pick_col(sim, ["fault_type", "fault", "label", "anomaly_type", "type"])
    orig_map = {
        "temp": ["temp_original", "clean_temp", "temp_clean", "temp_true"],
        "rhum": ["rhum_original", "clean_rhum", "rhum_clean", "rhum_true", "rh_original"],
        "pres": ["pres_original", "clean_pres", "pres_clean", "pres_true", "pressure_original"],
    }
    obs_map = {
        "temp": ["temp_corrupted", "observed_temp", "temp_obs"],
        "rhum": ["rhum_corrupted", "observed_rhum", "rhum_obs", "rh_corrupted"],
        "pres": ["pres_corrupted", "observed_pres", "pres_obs"],
    }

    overlay = pd.DataFrame(
        {
            "station_id": sim[sid_col].astype(str),
            "timestamp": pd.to_datetime(sim[ts_col]),
        }
    )
    overlay["fault_type"] = (
        sim[fault_col].map(normalize_fault_type) if fault_col else None
    )
    for feat in FEATURES:
        ocol = _pick_col(sim, orig_map[feat])
        ccol = _pick_col(sim, obs_map[feat])
        if ccol is None:
            ccol = _pick_col(sim, [feat])
        overlay[f"{feat}_original"] = (
            pd.to_numeric(sim[ocol], errors="coerce") if ocol else np.nan
        )
        overlay[f"{feat}_obs"] = (
            pd.to_numeric(sim[ccol], errors="coerce") if ccol else np.nan
        )

    mismatch = False
    for feat in FEATURES:
        a = overlay[f"{feat}_original"]
        b = overlay[f"{feat}_obs"]
        mismatch = mismatch | (a.fillna(np.inf) != b.fillna(np.inf))
    if "fault_type" in overlay.columns:
        overlay.loc[overlay["fault_type"].isna() & mismatch, "fault_type"] = "UNKNOWN"

    overlay = overlay.drop_duplicates(["station_id", "timestamp"], keep="last")

    base = clean_df.copy()
    base["station_id"] = base["station_id"].astype(str)
    base["timestamp"] = pd.to_datetime(base["timestamp"])
    for feat in FEATURES:
        base[f"{feat}_original"] = base[feat]
    base["fault_type"] = pd.Series([None] * len(base), dtype=object)

    merged = base.merge(overlay, on=["station_id", "timestamp"], how="left", suffixes=("", "_ov"))

    if "fault_type_ov" in merged.columns:
        merged["fault_type"] = merged["fault_type_ov"].combine_first(merged["fault_type"])

    for feat in FEATURES:
        orig_ov = f"{feat}_original_ov"
        obs_ov = f"{feat}_obs"
        if orig_ov in merged.columns:
            merged[f"{feat}_original"] = merged[orig_ov].combine_first(
                merged[f"{feat}_original"]
            )
        if obs_ov in merged.columns:
            merged[feat] = merged[obs_ov].combine_first(merged[feat])

    merged["fault_type"] = merged["fault_type"].map(normalize_fault_type)
    return (
        merged[
            [
                "station_id",
                "timestamp",
                "fault_type",
                "temp_original",
                "rhum_original",
                "pres_original",
                *FEATURES,
            ]
        ]
        .sort_values(["station_id", "timestamp"])
        .reset_index(drop=True)
    )


def interpolate_short_gaps(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in FEATURES:
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
    return ((arr - vmin) / vr).astype(np.float32)


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


def load_artifacts():
    weights_path = None
    for name in ("lstm_autoencoder.pt", "lstm_autoencoder.pth", "lstm_autoencoder.zip"):
        candidate = ARTIFACTS / name
        if candidate.is_file():
            weights_path = candidate
            break
    scalers_path = ARTIFACTS / "scalers.json"
    pct_path = ARTIFACTS / "val_error_percentiles.json"
    meta_path = ARTIFACTS / "model_metadata.json"

    required = [p for p in (scalers_path, pct_path) if not p.exists()]
    if weights_path is None:
        required.append(ARTIFACTS / "lstm_autoencoder.pt")
    if required:
        raise FileNotFoundError(
            "Missing artifacts. Copy Kaggle /kaggle/working/artifacts/ into "
            f"ml/artifacts/. Missing: {[p.name for p in required]}"
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

    with open(pct_path, encoding="utf-8") as f:
        percentiles = json.load(f)

    metadata = {}
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            metadata = json.load(f)

    return model, scalers, percentiles, metadata


def load_clean_2024() -> pd.DataFrame:
    catalog = pd.read_csv(RAW_DIR / "stations.csv", dtype={"station_id": str})
    frames = []
    for sid in catalog["station_id"].astype(str):
        path = RAW_DIR / f"{sid}.csv"
        if not path.exists():
            warnings.warn(f"missing {path.name}")
            continue
        df = pd.read_csv(path, parse_dates=["timestamp"])
        df["station_id"] = sid
        df = df.sort_values("timestamp").drop_duplicates("timestamp")
        df = df.set_index("timestamp").loc[TEST_START:TEST_END].reset_index()
        frames.append(df[["station_id", "timestamp", *FEATURES]])
    if not frames:
        raise FileNotFoundError(f"No station CSVs under {RAW_DIR}")
    return pd.concat(frames, ignore_index=True)


@torch.no_grad()
def score_windows(model, scaled, index, device):
    ds = WindowDataset(scaled, index)
    loader = DataLoader(ds, batch_size=BATCH_SIZE, shuffle=False)
    window_mse = []
    last_mse = []
    feat_last = []
    model = model.to(device)
    model.eval()
    for batch in loader:
        batch = batch.to(device)
        recon = model(batch)
        err = (recon - batch) ** 2
        window_mse.append(err.mean(dim=(1, 2)).cpu().numpy())
        last_mse.append(err[:, -1, :].mean(dim=1).cpu().numpy())
        feat_last.append(err[:, -1, :].cpu().numpy())
    return (
        np.concatenate(window_mse),
        np.concatenate(last_mse),
        np.concatenate(feat_last, axis=0),
    )


def metrics_from_scores(y_true, scores, threshold):
    y_true = np.asarray(y_true).astype(int)
    y_pred = (np.asarray(scores) >= threshold).astype(int)
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
    auc = float("nan")
    ap = float("nan")
    if y_true.min() != y_true.max():
        try:
            from sklearn.metrics import average_precision_score, roc_auc_score

            auc = float(roc_auc_score(y_true, scores))
            ap = float(average_precision_score(y_true, scores))
        except Exception:
            auc = float("nan")
            ap = float("nan")
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
        "roc_auc": None if math.isnan(auc) else round(auc, 4),
        "pr_auc": None if math.isnan(ap) else round(ap, 4),
        "threshold": float(threshold),
    }


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


def run():
    REPORTS.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("device:", device)

    model, scalers, percentiles, metadata = load_artifacts()
    print("loaded artifacts from", ARTIFACTS)
    print("kaggle test_used?", metadata.get("test_used_in_this_notebook"))

    threshold = float(
        percentiles["window_mse"][DEFAULT_PERCENTILE]
    )
    print(
        f"operating threshold = val window MSE p{DEFAULT_PERCENTILE} "
        f"= {threshold:.6g}  (not tuned on 2024)"
    )

    simulate_corruption = import_simulate_corruption()

    clean = load_clean_2024()
    print("clean 2024 rows:", len(clean), "stations:", clean["station_id"].nunique())

    raw_sim = simulate_corruption(clean.copy(), seed=SEED)
    observed = canonicalize_simulator_output(raw_sim, clean)
    print("after simulator rows:", len(observed))
    print("fault_type counts:")
    print(observed["fault_type"].value_counts(dropna=False).to_string())

    n_clean = int(observed["fault_type"].isna().sum())
    n_hw = int(observed["fault_type"].isin(HARDWARE_FAULTS).sum())
    if n_clean == 0:
        warnings.warn(
            "No CLEAN hours after simulation. FPR cannot be measured. "
            "The simulator should leave a large clean majority."
        )
    print(f"clean hours={n_clean}  hardware-fault hours={n_hw}")

    # Preprocess OBSERVED (corrupted) series the same way as training.
    frames = {}
    labels = {}
    for sid, grp in observed.groupby("station_id"):
        g = grp.sort_values("timestamp").drop_duplicates("timestamp")
        g = g.set_index("timestamp")
        g = interpolate_short_gaps(g)
        frames[sid] = g
        labels[sid] = g["fault_type"]

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

    print("windows:", len(index), "| stations missing scaler:", skipped_no_scaler)
    if not index:
        raise RuntimeError("No complete 24h windows on 2024 observed series.")

    window_mse, last_mse, _feat_last = score_windows(model, scaled, index, device)

    y_fault = np.array([normalize_fault_type(v) for v in last_labels], dtype=object)

    hardware_mask = np.array(
        [(v in HARDWARE_FAULTS) if v is not None else False for v in y_fault]
    )
    clean_mask = np.array([v is None for v in y_fault])
    storm_mask = np.array([v == "STORM" for v in y_fault])

    eval_mask = hardware_mask | clean_mask
    y_true = hardware_mask[eval_mask].astype(int)
    scores = window_mse[eval_mask]

    overall = metrics_from_scores(y_true, scores, threshold)
    print_metrics("OVERALL (hardware faults vs clean, 2024, last-hour label)", overall)

    per_fault = {}
    for fault in ["SPIKE", "FREEZE", "DRIFT", "COMMUNICATION", "UNKNOWN"]:
        pos = np.array([v == fault for v in y_fault])
        mask = pos | clean_mask
        if pos.sum() == 0:
            per_fault[fault] = {"n_positives": 0, "note": "no windows with this last-hour label"}
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

    # Val-percentile operating points applied to 2024 (not selected using 2024).
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
        "seed": SEED,
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
        "assumptions_file": "ml/testing_model.py module docstring",
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    out_json = REPORTS / "lstm_test_2024_metrics.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    rows = [{"fault": "OVERALL", **overall}]
    for k, v in per_fault.items():
        if "precision" in v:
            rows.append({"fault": k, **v})
    pd.DataFrame(rows).to_csv(REPORTS / "lstm_test_2024_metrics.csv", index=False)
    pd.DataFrame(sweep_rows).to_csv(
        REPORTS / "lstm_test_2024_threshold_sweep.csv", index=False
    )

    print("\nWrote", out_json)
    print("Wrote", REPORTS / "lstm_test_2024_metrics.csv")


if __name__ == "__main__":
    run()
