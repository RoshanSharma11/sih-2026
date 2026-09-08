"""Tier 2 — bottleneck LSTM autoencoder + per-station 24h buffer."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import torch
    import torch.nn as nn
except ImportError:  # training still on Kaggle; runtime can start without weights
    torch = None
    nn = None

from .config import (
    ARTIFACTS_DIR,
    DEFAULT_PERCENTILE,
    FEATURES,
    GAP_RESET_HOURS,
    HOUR_TOLERANCE_SECONDS,
    INTERPOLATE_LIMIT_HOURS,
    WINDOW_HOURS,
    resolve_weights_path,
)


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

else:

    class LSTMAutoencoder:  # type: ignore[no-redef]
        pass


def apply_minmax(arr: np.ndarray, stats: dict) -> np.ndarray:
    vmin = np.array(stats["min"], dtype=np.float64)
    vr = np.array(stats["range"], dtype=np.float64)
    return ((arr - vmin) / vr).astype(np.float32)


def inverse_minmax(arr: np.ndarray, stats: dict) -> np.ndarray:
    vmin = np.array(stats["min"], dtype=np.float64)
    vr = np.array(stats["range"], dtype=np.float64)
    return arr * vr + vmin


def _to_naive(ts) -> datetime:
    t = pd.Timestamp(ts).to_pydatetime()
    return t.replace(tzinfo=None)


class StationBuffer:
    """Fallback 24h history when the request has no `window`."""

    def __init__(self):
        self._rows: dict[str, pd.DataFrame] = {}

    def update(self, station_id: str, timestamp: datetime, temp, rhum, pres):
        ts = _to_naive(timestamp)
        row = pd.DataFrame(
            [{"timestamp": ts, "temp": temp, "rhum": rhum, "pres": pres}]
        )
        prev = self._rows.get(station_id)
        if prev is None or prev.empty:
            self._rows[station_id] = row
            return
        last = prev["timestamp"].max()
        gap_h = (ts - last).total_seconds() / 3600.0
        if gap_h < 0:
            combined = pd.concat([prev, row], ignore_index=True)
        elif gap_h > GAP_RESET_HOURS + 0.05:
            combined = row
        else:
            combined = pd.concat([prev, row], ignore_index=True)
        combined = combined.drop_duplicates("timestamp", keep="last").sort_values(
            "timestamp"
        )
        cutoff = ts - timedelta(hours=WINDOW_HOURS + 2)
        self._rows[station_id] = combined[combined["timestamp"] >= cutoff].copy()

    def window_ending_at(self, station_id: str, timestamp: datetime) -> pd.DataFrame | None:
        df = self._rows.get(station_id)
        if df is None or df.empty:
            return None
        ts = _to_naive(timestamp)
        end = ts
        start = ts - timedelta(hours=WINDOW_HOURS - 1)
        slice_ = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)].copy()
        return slice_ if not slice_.empty else None


class LSTMInference:
    def __init__(self, artifacts_dir: Path | None = None, device: str | None = None):
        self.artifacts_dir = Path(artifacts_dir or ARTIFACTS_DIR)
        self.device = None
        if torch is not None:
            self.device = torch.device(
                device or ("cuda" if torch.cuda.is_available() else "cpu")
            )
        self.model: LSTMAutoencoder | None = None
        self.scalers: dict = {}
        self.threshold: float | None = None
        self.metadata: dict = {}
        self.loaded = False
        self.buffer = StationBuffer()
        self._load()

    def _load(self):
        if torch is None:
            self.loaded = False
            return

        weights = resolve_weights_path(self.artifacts_dir)
        scalers_path = self.artifacts_dir / "scalers.json"
        pct_path = self.artifacts_dir / "val_error_percentiles.json"
        meta_path = self.artifacts_dir / "model_metadata.json"
        thr_path = self.artifacts_dir / "threshold.json"

        if weights is None or not scalers_path.exists():
            self.loaded = False
            return

        try:
            ckpt = torch.load(weights, map_location="cpu", weights_only=False)
        except TypeError:
            ckpt = torch.load(weights, map_location="cpu")

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
        model.to(self.device)
        model.eval()
        self.model = model

        with open(scalers_path, encoding="utf-8") as f:
            self.scalers = json.load(f)

        if thr_path.exists():
            with open(thr_path, encoding="utf-8") as f:
                self.threshold = float(json.load(f)["threshold"])
        elif pct_path.exists():
            with open(pct_path, encoding="utf-8") as f:
                pct = json.load(f)
            self.threshold = float(pct["window_mse"][DEFAULT_PERCENTILE])
        else:
            self.threshold = None

        if meta_path.exists():
            with open(meta_path, encoding="utf-8") as f:
                self.metadata = json.load(f)

        self.loaded = True

    def has_scaler(self, station_id: str) -> bool:
        return str(station_id) in self.scalers

    def interpolate_window(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy().sort_values("timestamp")
        for col in FEATURES:
            out[col] = pd.to_numeric(out[col], errors="coerce")
            out[col] = out[col].interpolate(
                method="linear",
                limit=INTERPOLATE_LIMIT_HOURS,
                limit_area="inside",
            )
        return out

    def validate_hourly_window(
        self,
        df: pd.DataFrame,
        timestamp: datetime,
        temp,
        rhum,
        pres,
    ) -> tuple[pd.DataFrame | None, str | None]:
        """Return (24-row frame, error_reason)."""
        if df is None or df.empty:
            return None, "INSUFFICIENT_WINDOW: no history"

        work = df.copy()
        work["timestamp"] = work["timestamp"].map(_to_naive)
        work = work.drop_duplicates("timestamp", keep="last").sort_values("timestamp")
        ts = _to_naive(timestamp)

        expected = pd.date_range(end=pd.Timestamp(ts), periods=WINDOW_HOURS, freq="h")
        work = work.set_index("timestamp").reindex(expected).reset_index()
        work = work.rename(columns={"index": "timestamp"})
        work["timestamp"] = work["timestamp"].map(_to_naive)

        last = work.iloc[-1]
        last_ts = _to_naive(last["timestamp"])
        if abs((last_ts - ts).total_seconds()) > HOUR_TOLERANCE_SECONDS:
            return None, "INSUFFICIENT_WINDOW: window does not end at ingest timestamp"

        # Align last row to the request values (source of truth for this hour).
        work.loc[work.index[-1], "temp"] = temp
        work.loc[work.index[-1], "rhum"] = rhum
        work.loc[work.index[-1], "pres"] = pres

        work = self.interpolate_window(work)
        complete = work[FEATURES].notna().all(axis=1)
        if not bool(complete.all()):
            n_ok = int(complete.sum())
            return None, (
                f"INSUFFICIENT_WINDOW: need {WINDOW_HOURS} hourly rows "
                f"(have {n_ok} after interpolate)"
            )

        diffs = work["timestamp"].diff().dt.total_seconds().iloc[1:]
        if (diffs - 3600).abs().max() > HOUR_TOLERANCE_SECONDS:
            return None, "INSUFFICIENT_WINDOW: timestamps are not hourly"

        return work, None

    def infer(self, station_id: str, window_df: pd.DataFrame) -> dict:
        if torch is None or self.model is None:
            raise RuntimeError("LSTM artifacts are not loaded")
        stats = self.scalers[str(station_id)]
        raw = window_df[FEATURES].to_numpy(dtype=np.float64)
        scaled = apply_minmax(raw, stats)
        with torch.no_grad():
            x = torch.from_numpy(np.nan_to_num(scaled, nan=0.0)).unsqueeze(0).to(self.device)
            recon = self.model(x).squeeze(0).cpu().numpy()
        err = (recon - scaled) ** 2
        window_mse = float(err.mean())
        last_feat = err[-1]
        last_sum = float(last_feat.sum()) + 1e-12
        contributions = {
            feat: float(last_feat[i] / last_sum) for i, feat in enumerate(FEATURES)
        }
        predicted_last = inverse_minmax(recon[-1], stats)
        predicted = {
            feat: float(predicted_last[i]) for i, feat in enumerate(FEATURES)
        }
        return {
            "ran": True,
            "window_mse": window_mse,
            "threshold": float(self.threshold) if self.threshold is not None else None,
            "feature_contributions": contributions,
            "predicted": predicted,
            "is_suspicious": (
                self.threshold is not None and window_mse > self.threshold
            ),
        }
