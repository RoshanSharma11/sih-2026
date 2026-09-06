"""Completeness filter, clustering, and stations.json I/O. No Meteostat imports."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any

import pandas as pd

from skyguard.config import (
    BUDDY_KM,
    COMPLETENESS_MIN,
    KEEPER_COUNT,
    NORTH_QUOTA,
    STATIONS_PATH,
    WEST_QUOTA,
)
from skyguard.schemas import ClusterId

CHANNELS = ("temp_c", "pres_hpa", "rhum_pct")


@dataclass
class StationRecord:
    station_id: str
    name: str
    latitude: float
    longitude: float
    elevation_m: float | None
    cluster_id: str
    completeness: dict[str, float]

    def mean_completeness(self) -> float:
        return sum(self.completeness[c] for c in CHANNELS) / len(CHANNELS)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlmb = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlmb / 2) ** 2
    return 2 * r * asin(sqrt(a))


def expected_hours(start: datetime, end: datetime) -> int:
    idx = pd.date_range(start=start, end=end, freq="h")
    return int(len(idx))


def completeness(df: pd.DataFrame, start: datetime, end: datetime) -> dict[str, float]:
    expected = max(expected_hours(start, end), 1)
    out: dict[str, float] = {}
    for channel in CHANNELS:
        present = int(df[channel].notna().sum()) if channel in df.columns else 0
        out[channel] = round(present / expected, 4)
    return out


def passes_threshold(scores: dict[str, float], minimum: float = COMPLETENESS_MIN) -> bool:
    return all(scores.get(channel, 0.0) >= minimum for channel in CHANNELS)


def nearest_cluster(lat: float, lon: float) -> str:
    delhi = (28.57, 77.12)
    mumbai = (19.09, 72.87)
    pune = (18.58, 73.92)
    d_north = haversine_km(lat, lon, *delhi)
    d_west = min(haversine_km(lat, lon, *mumbai), haversine_km(lat, lon, *pune))
    if d_north <= BUDDY_KM and d_north <= d_west:
        return ClusterId.NORTH.value
    if d_west <= BUDDY_KM:
        return ClusterId.WEST.value
    return ClusterId.NORTH.value if d_north < d_west else ClusterId.WEST.value


def _best_west_pair(west: list[StationRecord]) -> list[StationRecord]:
    best: tuple[float, StationRecord, StationRecord] | None = None
    for i, left in enumerate(west):
        for right in west[i + 1 :]:
            if haversine_km(left.latitude, left.longitude, right.latitude, right.longitude) > BUDDY_KM:
                continue
            score = left.mean_completeness() + right.mean_completeness()
            if best is None or score > best[0]:
                best = (score, left, right)
    if best is None:
        return []
    return [best[1], best[2]]


def select_keepers(candidates: list[StationRecord]) -> tuple[list[StationRecord], str]:
    """Pick 5 stations in 2 clusters, or fall back to all-NORTH."""
    ranked = sorted(candidates, key=lambda s: s.mean_completeness(), reverse=True)
    north = [s for s in ranked if s.cluster_id == ClusterId.NORTH.value]
    west = [s for s in ranked if s.cluster_id == ClusterId.WEST.value]
    picked_west = _best_west_pair(west)
    notes = ""

    if len(picked_west) < WEST_QUOTA:
        notes = (
            "WEST lacked 2 stations within 150 km that passed completeness; "
            "all keepers assigned to NORTH."
        )
        keepers = ranked[:KEEPER_COUNT]
        for station in keepers:
            station.cluster_id = ClusterId.NORTH.value
        return keepers, notes

    picked_north = north[:NORTH_QUOTA]
    used = {s.station_id for s in picked_north + picked_west}
    if len(picked_north) < NORTH_QUOTA:
        extras = [s for s in ranked if s.station_id not in used]
        need = NORTH_QUOTA - len(picked_north)
        for extra in extras[:need]:
            extra.cluster_id = ClusterId.NORTH.value
            picked_north.append(extra)
            used.add(extra.station_id)

    keepers = picked_north[:NORTH_QUOTA] + picked_west[:WEST_QUOTA]
    return keepers[:KEEPER_COUNT], notes


def catalog_document(
    stations: list[StationRecord],
    notes: str = "",
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notes": notes,
        "range": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
        "stations": [asdict(s) for s in stations],
    }


def write_catalog(document: dict[str, Any], path: Path | None = None) -> Path:
    target = path or STATIONS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return target


def read_catalog(path: Path | None = None) -> dict[str, Any]:
    target = path or STATIONS_PATH
    return json.loads(target.read_text(encoding="utf-8"))
