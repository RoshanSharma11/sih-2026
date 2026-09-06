"""Detector boundary for the LSTM autoencoder. See docs/contracts.md."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class Reconstruction:
    reconstructed: np.ndarray
    mse: float
    mse_vector: np.ndarray
    contribution_pct: np.ndarray
    skipped: bool


class Detector(Protocol):
    def reconstruct(self, window: np.ndarray) -> Reconstruction:
        """window: shape (N, 3), oldest→newest, original units, no NaNs."""
