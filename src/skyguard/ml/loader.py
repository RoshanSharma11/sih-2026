"""Load the configured Detector. Real .pt loading lands with the ML owner."""

from __future__ import annotations

import os

from skyguard.ml.identity import IdentityDetector
from skyguard.ml.protocol import Detector


def load_detector(model_path: str | None = None) -> Detector:
    path = model_path if model_path is not None else os.environ.get("MODEL_PATH", "").strip()
    if path:
        raise NotImplementedError(
            f"Real detector loading is not implemented (MODEL_PATH={path}). "
            "Unset MODEL_PATH to use IdentityDetector."
        )
    return IdentityDetector()
