"""Detector reconstruction on the last complete 24-hour window."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from skyguard.config import WINDOW_HOURS, recon_threshold
from skyguard.engine.windows import WindowPoint
from skyguard.ml.identity import IdentityDetector
from skyguard.ml.protocol import Detector, Reconstruction
from skyguard.schemas import Channel

CHANNELS = (Channel.TEMP_C, Channel.PRES_HPA, Channel.RHUM_PCT)


def skipped_reconstruction() -> Reconstruction:
    zeros = np.zeros(3, dtype=float)
    return Reconstruction(
        reconstructed=zeros,
        mse=0.0,
        mse_vector=zeros,
        contribution_pct=zeros,
        skipped=True,
    )


@dataclass(frozen=True)
class Tier2Result:
    reconstruction: Reconstruction
    over_threshold: bool

    @property
    def skipped(self) -> bool:
        return self.reconstruction.skipped


def window_matrix(points: list[WindowPoint], size: int = WINDOW_HOURS) -> np.ndarray | None:
    if len(points) < size:
        return None
    rows: list[list[float]] = []
    for point in points[-size:]:
        values = [point.temp_c, point.pres_hpa, point.rhum_pct]
        if any(value is None for value in values):
            return None
        rows.append([float(value) for value in values])
    return np.asarray(rows, dtype=float)


def evaluate(
    points: list[WindowPoint],
    detector: Detector | None = None,
    threshold: float | None = None,
) -> Tier2Result:
    matrix = window_matrix(points)
    if matrix is None:
        return Tier2Result(skipped_reconstruction(), False)
    recon = (detector or IdentityDetector()).reconstruct(matrix)
    cut = recon_threshold() if threshold is None else threshold
    over = (not recon.skipped) and recon.mse > cut
    return Tier2Result(recon, over)
