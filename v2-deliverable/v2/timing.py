"""Off-path TIMING: time-respecting integrated gradients of the LSTM ingest score.

Never call from inside process_aws_data before return. First ingest JSON stays
timing=null. Poll get_timing / GET /stations/{id}/timing?ts=.
"""

from __future__ import annotations

import copy
import queue
import threading
import time
from collections import OrderedDict
from datetime import datetime

try:
    import torch
except ImportError:
    torch = None

import numpy as np
import pandas as pd

from .config import (
    FEATURES,
    LAST_HOURS_SCORE,
    SCORE_LAST_WEIGHT,
    SCORE_WINDOW_WEIGHT,
    TIMING_CACHE_MAX,
    TIMING_IG_STEPS,
    WINDOW_HOURS,
)
from .lstm_inference import LSTMInference, apply_minmax, _to_naive


def timing_key(station_id: str, timestamp) -> str:
    return f"{station_id}|{_to_naive(timestamp).strftime('%Y-%m-%dT%H:%M:%S')}"


def _score_torch(err):
    window_mse = err.mean()
    last = err[-LAST_HOURS_SCORE:] if err.shape[0] >= LAST_HOURS_SCORE else err
    return SCORE_LAST_WEIGHT * last.mean() + SCORE_WINDOW_WEIGHT * window_mse


class TimingService:
    def __init__(self, lstm: LSTMInference, n_steps: int = TIMING_IG_STEPS):
        self.lstm = lstm
        self.n_steps = int(n_steps)
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()
        self._jobs: queue.SimpleQueue = queue.SimpleQueue()
        self._explain_model = None
        if torch is not None and lstm.model is not None:
            self._explain_model = copy.deepcopy(lstm.model)
            self._explain_model.eval()
            if lstm.device is not None:
                self._explain_model.to(lstm.device)
            for p in self._explain_model.parameters():
                p.requires_grad_(False)
        self._worker = threading.Thread(target=self._loop, name="timing", daemon=True)
        self._worker.start()

    def _loop(self) -> None:
        while True:
            item = self._jobs.get()
            if item is None:
                break
            key, sid, snap = item
            self._run(key, sid, snap)

    @property
    def available(self) -> bool:
        return torch is not None and self._explain_model is not None and self.lstm.loaded

    def enqueue(self, station_id: str, timestamp: datetime, window_df: pd.DataFrame) -> str:
        key = timing_key(station_id, timestamp)
        if not self.available or window_df is None or len(window_df) < WINDOW_HOURS:
            return key
        sid = str(station_id)
        if not self.lstm.has_scaler(sid):
            return key
        snap = window_df.tail(WINDOW_HOURS).copy()
        with self._lock:
            existing = self._cache.get(key)
            if existing and existing.get("status") == "pending":
                return key
            self._cache[key] = {
                "station_id": sid,
                "timestamp": _to_naive(timestamp).strftime("%Y-%m-%dT%H:%M:%S"),
                "status": "pending",
                "timing": None,
            }
            self._cache.move_to_end(key)
            while len(self._cache) > TIMING_CACHE_MAX:
                self._cache.popitem(last=False)
        self._jobs.put((key, sid, snap))
        return key

    def get(self, station_id: str, timestamp, wait_s: float = 0.0) -> dict:
        key = timing_key(station_id, timestamp)
        if wait_s and wait_s > 0:
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < wait_s:
                with self._lock:
                    hit = self._cache.get(key)
                if hit and hit.get("status") != "pending":
                    return dict(hit)
                time.sleep(0.05)
        with self._lock:
            hit = self._cache.get(key)
        if hit is None:
            return {
                "station_id": str(station_id),
                "timestamp": _to_naive(timestamp).strftime("%Y-%m-%dT%H:%M:%S"),
                "status": "not_requested",
                "timing": None,
            }
        return dict(hit)

    def compute(self, station_id: str, window_df: pd.DataFrame) -> dict:
        if not self.available:
            raise RuntimeError("TIMING model is not loaded")
        sid = str(station_id)
        stats = self.lstm.scalers[sid]
        raw = window_df[FEATURES].to_numpy(dtype=np.float64)[-WINDOW_HOURS:]
        scaled = apply_minmax(raw, stats)
        x_np = np.nan_to_num(scaled, nan=0.0).astype(np.float32)
        device = self.lstm.device
        x = torch.from_numpy(x_np).unsqueeze(0).to(device)
        baseline = torch.zeros_like(x)
        delta = x - baseline
        grads = torch.zeros_like(x)
        steps = max(1, self.n_steps)
        for i in range(1, steps + 1):
            x_a = (baseline + (i / steps) * delta).detach().requires_grad_(True)
            recon = self._explain_model(x_a)
            err = (recon - x_a).pow(2).squeeze(0)
            loss = _score_torch(err)
            loss.backward()
            grads = grads + x_a.grad.detach()
        ig = (delta * grads / steps).squeeze(0).detach().cpu().numpy()
        hour_abs = np.abs(ig).sum(axis=1)
        total = float(hour_abs.sum()) + 1e-12
        cum = np.cumsum(hour_abs)
        start = int(np.searchsorted(cum, 0.5 * total, side="left"))
        start = min(max(start, 0), WINDOW_HOURS - 1)
        ch = np.abs(ig).sum(axis=0)
        ch = ch / (float(ch.sum()) + 1e-12)
        channel_attr = {feat: round(float(ch[i]), 4) for i, feat in enumerate(FEATURES)}
        top = max(channel_attr, key=channel_attr.get)
        return {
            "start_hour_in_window": start,
            "channel_attr": channel_attr,
            "hour_attr": [round(float(v / total), 4) for v in hour_abs],
            "reason": (
                f"Anomaly attribution starts at hour {start} of the 24 h window "
                f"(mostly {top})."
            ),
        }

    def _run(self, key: str, station_id: str, window_df: pd.DataFrame) -> None:
        try:
            timing = self.compute(station_id, window_df)
            status = "ready"
            err = None
        except Exception as exc:
            timing = None
            status = "error"
            err = str(exc)
        with self._lock:
            row = self._cache.get(key) or {
                "station_id": station_id,
                "timestamp": key.split("|", 1)[-1],
            }
            row["status"] = status
            row["timing"] = timing
            if err:
                row["error"] = err
            self._cache[key] = row
            self._cache.move_to_end(key)
