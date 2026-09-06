"""Paths and tunables. Override with environment variables."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("SKYGUARD_DATA", REPO_ROOT / "data"))
DB_PATH = Path(os.environ.get("SKYGUARD_DB", DATA_DIR / "skyguard.db"))
STATIONS_PATH = Path(os.environ.get("SKYGUARD_STATIONS", DATA_DIR / "processed" / "stations.json"))
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

WINDOW_HOURS = int(os.environ.get("SKYGUARD_WINDOW", "24"))
STREAM_MS = int(os.environ.get("SKYGUARD_STREAM_MS", "200"))


def recon_threshold() -> float:
    return float(os.environ.get("SKYGUARD_RECON_THRESHOLD", "inf"))
COMPLETENESS_MIN = 0.85
BUDDY_KM = float(os.environ.get("SKYGUARD_BUDDY_KM", "150"))
IDW_POWER = float(os.environ.get("SKYGUARD_IDW_POWER", "2"))
SEARCH_RADIUS_M = 80_000
NORTH_QUOTA = 3
WEST_QUOTA = 2
KEEPER_COUNT = 5

FETCH_START = datetime(2018, 1, 1)
FETCH_END = datetime(2024, 12, 31, 23, 0, 0)
DEMO_START = datetime(2024, 7, 1, tzinfo=timezone.utc)

ANCHORS = (
    {"name": "Delhi NCR", "latitude": 28.57, "longitude": 77.12, "cluster_id": "NORTH"},
    {"name": "Mumbai", "latitude": 19.09, "longitude": 72.87, "cluster_id": "WEST"},
    {"name": "Pune", "latitude": 18.58, "longitude": 73.92, "cluster_id": "WEST"},
)
