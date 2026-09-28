"""V2 runtime constants."""

from __future__ import annotations

from pathlib import Path

V2_DIR = Path(__file__).resolve().parent
ROOT = V2_DIR.parent
ARTIFACTS_DIR = V2_DIR / "artifacts"
DATA_DIR = V2_DIR / "data"
WEIGHT_CANDIDATES = (
    "lstm_autoencoder.pt",
    "lstm_autoencoder.pth",
    "lstm_autoencoder.zip",
)


def resolve_weights_path(artifacts_dir: Path | None = None) -> Path | None:
    d = Path(artifacts_dir or ARTIFACTS_DIR)
    for name in WEIGHT_CANDIDATES:
        p = d / name
        if p.is_file():
            return p
    return None


def resolve_raw_dir() -> Path:
    for p in (DATA_DIR / "raw", ROOT / "data" / "raw"):
        if (p / "43003.csv").exists():
            return p
    return DATA_DIR / "raw"


RAW_DIR = resolve_raw_dir()
CATALOG_PATH = DATA_DIR / "stations.csv"
EDGES_PATH = DATA_DIR / "buddy_edges.csv"
JUDGE48_PATH = DATA_DIR / "stations_judge48.csv"

FEATURES = ["temp", "rhum", "pres"]
WINDOW_HOURS = 24

TEMP_MIN, TEMP_MAX = -10.0, 60.0
RHUM_MIN, RHUM_MAX = 0.0, 100.0
PRES_MIN, PRES_MAX = 870.0, 1080.0
STEP_TEMP = 10.0
STEP_RHUM = 30.0
STEP_PRES = 10.0

INTERPOLATE_LIMIT_HOURS = 2
GAP_RESET_HOURS = 2.0
HOUR_TOLERANCE_SECONDS = 90

IDW_POWER = 2.0
BUDDY_TIME_TOLERANCE_HOURS = 1.0
MIN_USABLE_BUDDIES = 2
K_MAX_GAT = 8
AGREE_TEMP = 3.0
AGREE_RHUM = 8.0
AGREE_PRES = 2.0
CORR_TAU = 0.35
# Shared shock: for "genuine weather" the neighbour blend itself must have moved.
# Either the blend jumped this hour by SHOCK_STEP_FRACTION of the agree band, or it sits
# SHOCK_BASELINE_FRACTION of the band away from its own 24 h mean. Otherwise an LSTM flag
# with agreeing, calm neighbours is a clean hour the model simply found unusual.
# Frozen on 2023 Jul-Sep Mumbai four (seed-42 injector): storm recall flat at 313/324 for
# every setting tried; clean hours labelled weather fell 1088 -> 533 here. 2024 held-out:
# 1056 -> 504, storm 306/324 unchanged, hardware recall unchanged.
SHOCK_STEP_FRACTION = 1.0
SHOCK_BASELINE_FRACTION = 1.5
SHOCK_BASELINE_MIN_HOURS = 6

CONFIDENCE_K = 2.0
DEFAULT_PERCENTILE = "99"
LAST_HOURS_SCORE = 3
SCORE_LAST_WEIGHT = 0.7
SCORE_WINDOW_WEIGHT = 0.3

HEALTH_MAX_HOURS = 24 * 7
HEALTHY_MIN = 0.90
DEGRADED_MIN = 0.70

FREEZE_HOURS = 12
FREEZE_HOURS_MULTI = 6
FREEZE_EPS = 0.15
FREEZE_EPS_BY_FEATURE = {"temp": 0.15, "rhum": 0.5, "pres": 0.15}
DRIFT_HOURS = 12
DRIFT_BIAS = 0.15

MAGNUS_A = 17.27
MAGNUS_B = 237.7
THERMO_EPS_C = 0.1

# Ingest / seed-42 eval use CW-IDW. Demo stories opt into GAT.
STGNN_ON_INGEST = False

TIMING_IG_STEPS = 16
TIMING_CACHE_MAX = 512
