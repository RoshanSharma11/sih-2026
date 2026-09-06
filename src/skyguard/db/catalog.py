"""Load stations.json into SQLite without touching health scores on restart."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from skyguard.db.models import Station
from skyguard.schemas import StationStatus


def upsert_catalog(session: Session, document: dict[str, Any]) -> int:
    count = 0
    for row in document.get("stations", []):
        station = session.get(Station, row["station_id"])
        if station is None:
            station = Station(
                station_id=row["station_id"],
                name=row["name"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                elevation_m=row.get("elevation_m"),
                cluster_id=row["cluster_id"],
                health_score=100.0,
                status=StationStatus.HEALTHY.value,
            )
            session.add(station)
        else:
            station.name = row["name"]
            station.latitude = row["latitude"]
            station.longitude = row["longitude"]
            station.elevation_m = row.get("elevation_m")
            station.cluster_id = row["cluster_id"]
        count += 1
    session.flush()
    return count
