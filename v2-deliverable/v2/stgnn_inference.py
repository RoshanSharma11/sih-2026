"""Slice B GAT: neighbors_agree from task-trained SpatialAgreeGAT.

Loads v2/artifacts/stgnn.pt only when metadata.gates_passed is true.
Otherwise ingest stays on CW-IDW.
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

from .config import ARTIFACTS_DIR, FEATURES, K_MAX_GAT, MIN_USABLE_BUDDIES, WINDOW_HOURS
from .lstm_inference import apply_minmax, inverse_minmax


if nn is not None:

    class SpatialAgreeGAT(nn.Module):
        def __init__(self, n_features=3, hidden=32):
            super().__init__()
            self.encoder = nn.LSTM(n_features, hidden, num_layers=1, batch_first=True)
            self.W = nn.Linear(hidden, hidden, bias=False)
            self.attn = nn.Linear(2 * hidden + 1, 1, bias=False)
            self.leaky = nn.LeakyReLU(0.2)
            self.head = nn.Sequential(
                nn.Linear(hidden * 2 + 6, hidden),
                nn.ReLU(),
                nn.Linear(hidden, 1),
            )

        def encode(self, x):
            _, (h_n, _) = self.encoder(x)
            return h_n[-1]

        def forward(self, primary, neighbors, neighbor_last, dist, mask):
            b, k, t, f = neighbors.shape
            z_i = self.encode(primary)
            z_n = self.encode(neighbors.reshape(b * k, t, f)).reshape(b, k, -1)
            z_n = z_n * mask.unsqueeze(-1)
            zi = z_i.unsqueeze(1).expand_as(z_n)
            logd = torch.log(dist.clamp(min=0.1)).unsqueeze(-1)
            e = self.leaky(self.attn(torch.cat([self.W(zi), self.W(z_n), logd], dim=-1)).squeeze(-1))
            e = e.masked_fill(mask < 0.5, -1e9)
            alpha = torch.softmax(e, dim=1) * mask
            alpha = alpha / alpha.sum(dim=1, keepdim=True).clamp(min=1e-6)
            mix_last = (alpha.unsqueeze(-1) * neighbor_last).sum(dim=1)
            mix_z = (alpha.unsqueeze(-1) * z_n).sum(dim=1)
            last = primary[:, -1, :]
            resid = last - mix_last
            logit = self.head(torch.cat([z_i, mix_z, resid, resid.abs()], dim=-1)).squeeze(-1)
            return logit, mix_last, alpha

else:

    class SpatialAgreeGAT:  # type: ignore[no-redef]
        pass


class STGNNInference:
    def __init__(self, artifacts_dir: Path | None = None, scalers: dict | None = None):
        self.artifacts_dir = Path(artifacts_dir or ARTIFACTS_DIR)
        self.scalers = scalers or {}
        self.model = None
        self.threshold = 0.5
        self.hidden = 32
        self.metadata: dict = {}
        self.loaded = False
        self._load()

    def _load(self) -> None:
        if torch is None:
            return
        weights = self.artifacts_dir / "stgnn.pt"
        meta_path = self.artifacts_dir / "stgnn_metadata.json"
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
            hidden = int(ckpt.get("hidden", meta.get("hidden", 32)))
        else:
            state = ckpt
            hidden = int(meta.get("hidden", 32))
        model = SpatialAgreeGAT(n_features=len(FEATURES), hidden=hidden)
        model.load_state_dict(state)
        model.eval()
        self.model = model
        self.hidden = hidden
        self.threshold = float(meta.get("agree_threshold", 0.5))
        self.metadata = meta
        self.loaded = True

    def infer(
        self,
        station_id: str,
        primary_phys: np.ndarray,
        neighbor_phys: list[np.ndarray],
        distances_km: list[float],
        neighbor_ids: list[str],
    ) -> dict | None:
        if not self.loaded or torch is None or self.model is None:
            return None
        if station_id not in self.scalers or len(neighbor_phys) < MIN_USABLE_BUDDIES:
            return None
        stats = self.scalers[station_id]
        prim = apply_minmax(np.asarray(primary_phys, dtype=np.float64), stats)
        if prim.shape != (WINDOW_HOURS, 3):
            return None
        k = K_MAX_GAT
        nw = np.zeros((k, WINDOW_HOURS, 3), dtype=np.float32)
        nl = np.zeros((k, 3), dtype=np.float32)
        dist = np.zeros((k,), dtype=np.float32)
        mask = np.zeros((k,), dtype=np.float32)
        usable = 0
        for j, (arr, dkm, nid) in enumerate(zip(neighbor_phys, distances_km, neighbor_ids)):
            if j >= k:
                break
            if nid not in self.scalers:
                continue
            w = apply_minmax(np.asarray(arr, dtype=np.float64), self.scalers[nid])
            if w.shape != (WINDOW_HOURS, 3):
                continue
            nw[usable] = np.nan_to_num(w, nan=0.0)
            nl[usable] = nw[usable, -1]
            dist[usable] = max(float(dkm), 0.1)
            mask[usable] = 1.0
            usable += 1
        if usable < MIN_USABLE_BUDDIES:
            return None
        with torch.no_grad():
            logit, mix_last, alpha = self.model(
                torch.from_numpy(np.nan_to_num(prim, nan=0.0)).unsqueeze(0),
                torch.from_numpy(nw).unsqueeze(0),
                torch.from_numpy(nl).unsqueeze(0),
                torch.from_numpy(dist).unsqueeze(0),
                torch.from_numpy(mask).unsqueeze(0),
            )
            p_agree = float(torch.sigmoid(logit)[0].cpu())
            mix_s = mix_last[0].cpu().numpy()
            attn = alpha[0].cpu().numpy()
        mix = inverse_minmax(mix_s, stats)
        return {
            "neighbors_agree": p_agree >= self.threshold,
            "p_agree": p_agree,
            "method": "stgnn",
            "mix": {f: float(mix[i]) for i, f in enumerate(FEATURES)},
            "attention": attn[:usable].tolist(),
            "usable_count": usable,
        }
