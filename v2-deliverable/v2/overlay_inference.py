"""Slice C — last-hour Gaussian overlay. One forward pass, no DDIM.

Loads overlay.pt only when overlay_metadata.json has gates_passed.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

try:
    import torch
    import torch.nn as nn
except ImportError:
    torch = None
    nn = None

from .config import ARTIFACTS_DIR, FEATURES, WINDOW_HOURS
from .lstm_inference import apply_minmax, inverse_minmax

Z90 = 1.64


if nn is not None:

    class LastStepGaussian(nn.Module):
        def __init__(self, n_features=3, hidden=64):
            super().__init__()
            self.encoder = nn.LSTM(n_features, hidden, num_layers=1, batch_first=True)
            self.head = nn.Linear(hidden + 2 * n_features, 2 * n_features)

        def forward(self, context, mix, last_obs):
            _, (h_n, _) = self.encoder(context)
            h = h_n[-1]
            out = self.head(torch.cat([h, mix, last_obs], dim=-1))
            mu = torch.sigmoid(out[:, :3])
            log_std = out[:, 3:].clamp(-6.0, 2.0)
            return mu, log_std

else:

    class LastStepGaussian:  # type: ignore[no-redef]
        pass


class OverlayInference:
    def __init__(self, artifacts_dir: Path | None = None, scalers: dict | None = None):
        self.artifacts_dir = Path(artifacts_dir or ARTIFACTS_DIR)
        self.scalers = scalers or {}
        self.model = None
        self.hidden = 64
        self.metadata: dict = {}
        self.loaded = False
        self._load()

    def _load(self) -> None:
        if torch is None:
            return
        weights = self.artifacts_dir / "overlay.pt"
        meta_path = self.artifacts_dir / "overlay_metadata.json"
        if not weights.is_file() or not meta_path.is_file():
            return
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not meta.get("gates_passed"):
            self.metadata = meta
            return
        try:
            ckpt = torch.load(weights, map_location="cpu", weights_only=False)
        except TypeError:
            ckpt = torch.load(weights, map_location="cpu")
        if isinstance(ckpt, dict) and "state_dict" in ckpt:
            state = ckpt["state_dict"]
            hidden = int(ckpt.get("hidden", meta.get("hidden", 64)))
        else:
            state = ckpt
            hidden = int(meta.get("hidden", 64))
        model = LastStepGaussian(n_features=len(FEATURES), hidden=hidden)
        model.load_state_dict(state)
        model.eval()
        self.model = model
        self.hidden = hidden
        self.metadata = meta
        self.loaded = True

    def infer(self, station_id: str, window_phys: np.ndarray, mix_phys: dict | None) -> dict | None:
        if not self.loaded or torch is None or self.model is None:
            return None
        if station_id not in self.scalers:
            return None
        arr = np.asarray(window_phys, dtype=np.float64)
        if arr.shape != (WINDOW_HOURS, 3):
            return None
        stats = self.scalers[station_id]
        scaled = apply_minmax(np.nan_to_num(arr, nan=0.0), stats)
        context = scaled[:-1]
        last_obs = scaled[-2]
        mix_vec = last_obs.copy()
        if mix_phys:
            mix_arr = np.array([mix_phys.get(f) for f in FEATURES], dtype=np.float64)
            if np.isfinite(mix_arr).all():
                mix_vec = apply_minmax(mix_arr.reshape(1, 3), stats)[0]
        with torch.no_grad():
            mu_s, log_std = self.model(
                torch.from_numpy(context).unsqueeze(0),
                torch.from_numpy(mix_vec.astype(np.float32)).unsqueeze(0),
                torch.from_numpy(last_obs.astype(np.float32)).unsqueeze(0),
            )
            mu_s = mu_s[0].cpu().numpy()
            std = np.exp(log_std[0].cpu().numpy())
        lo_s = np.clip(mu_s - Z90 * std, 0.0, 1.0)
        hi_s = np.clip(mu_s + Z90 * std, 0.0, 1.0)
        mu = inverse_minmax(mu_s, stats)
        lo = inverse_minmax(lo_s, stats)
        hi = inverse_minmax(hi_s, stats)
        return {
            "predicted": {f: float(mu[i]) for i, f in enumerate(FEATURES)},
            "imputed_interval": {f: [float(lo[i]), float(hi[i])] for i, f in enumerate(FEATURES)},
        }
