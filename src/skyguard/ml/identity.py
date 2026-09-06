"""Stub detector so the API can ship before ML weights exist."""

from __future__ import annotations

import numpy as np

from skyguard.ml.protocol import Reconstruction

WINDOW_SIZE = 24


class IdentityDetector:
    def reconstruct(self, window: np.ndarray) -> Reconstruction:
        if window.ndim != 2 or window.shape[1] != 3 or window.shape[0] == 0:
            return Reconstruction(
                reconstructed=np.zeros(3, dtype=float),
                mse=0.0,
                mse_vector=np.zeros(3, dtype=float),
                contribution_pct=np.zeros(3, dtype=float),
                skipped=True,
            )
        skipped = window.shape[0] < WINDOW_SIZE or bool(np.isnan(window).any())
        return Reconstruction(
            reconstructed=np.asarray(window[-1], dtype=float).copy(),
            mse=0.0,
            mse_vector=np.zeros(3, dtype=float),
            contribution_pct=np.zeros(3, dtype=float),
            skipped=skipped,
        )
