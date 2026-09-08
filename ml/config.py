"""Shared runtime constants."""

from pathlib import Path

ML_DIR = Path(__file__).resolve().parent
ROOT = ML_DIR.parent
ARTIFACTS_DIR = ML_DIR / "artifacts"
WEIGHT_CANDIDATES = (
    "lstm_autoencoder.pt",
    "lstm_autoencoder.pth",
    "lstm_autoencoder.zip",
)


def resolve_weights_path(artifacts_dir: Path | None = None) -> Path | None:
    """Return the checkpoint file. Windows often saves torch .pt as .zip."""
    d = Path(artifacts_dir or ARTIFACTS_DIR)
    for name in WEIGHT_CANDIDATES:
        p = d / name
        if p.is_file():
            return p
    return None
RAW_DIR = ROOT / "data" / "raw"
CATALOG_PATH = RAW_DIR / "stations.csv"
EDGES_PATH = RAW_DIR / "buddy_edges.csv"

FEATURES = ["temp", "rhum", "pres"]
WINDOW_HOURS = 24

# Tier 1 — WMO-style operational bounds
TEMP_MIN, TEMP_MAX = -10.0, 60.0
RHUM_MIN, RHUM_MAX = 0.0, 100.0
PRES_MIN, PRES_MAX = 870.0, 1080.0
STEP_TEMP = 10.0
STEP_RHUM = 30.0
STEP_PRES = 10.0

# Gaps
INTERPOLATE_LIMIT_HOURS = 2
GAP_RESET_HOURS = 2.0
HOUR_TOLERANCE_SECONDS = 90

# Buddy IDW
IDW_POWER = 2.0
BUDDY_TIME_TOLERANCE_HOURS = 1.0
MIN_USABLE_BUDDIES = 2
AGREE_TEMP = 3.0
AGREE_RHUM = 8.0
AGREE_PRES = 2.0

# LSTM score
CONFIDENCE_K = 2.0
DEFAULT_PERCENTILE = "99"

# Health
HEALTH_MAX_HOURS = 24 * 7
HEALTHY_MIN = 0.90
DEGRADED_MIN = 0.70

FREEZE_HOURS = 6
DRIFT_HOURS = 12
DRIFT_BIAS = 0.15  # scaled-space-ish °C-equivalent via reconstructed residual
