"""Load stations.json (and buddy edges) into SQLite without touching health scores."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from skyguard.db.models import Station, StationBuddy
from skyguard.errors import StationNotFound
from skyguard.schemas import StationStatus


def upsert_catalog(session: Session, document: dict[str, Any]) -> int:
    count = 0
    for row in document.get("stations", []):
        station = session.get(Station, row["station_id"])
        isolate = bool(row.get("isolate", False))
        if station is None:
            station = Station(
                station_id=row["station_id"],
                name=row["name"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                elevation_m=row.get("elevation_m"),
                cluster_id=row.get("cluster_id"),
                isolate=isolate,
                health_score=100.0,
                status=StationStatus.HEALTHY.value,
            )
            session.add(station)
        else:
            station.name = row["name"]
            station.latitude = row["latitude"]
            station.longitude = row["longitude"]
            station.elevation_m = row.get("elevation_m")
            if "cluster_id" in row:
                station.cluster_id = row.get("cluster_id")
            station.isolate = isolate
        count += 1
    session.flush()

    known = {row["station_id"] for row in document.get("stations", [])}
    edges: list[tuple[str, str, float]] = []
    for row in document.get("stations", []):
        station_id = row["station_id"]
        distances = {
            item["station_id"]: float(item["distance_km"])
            for item in row.get("buddies") or []
            if isinstance(item, dict) and "station_id" in item and "distance_km" in item
        }
        for buddy_id in row.get("buddy_ids") or []:
            if buddy_id not in known:
                continue
            edges.append((station_id, buddy_id, distances.get(buddy_id, 0.0)))
    if edges:
        upsert_buddies(session, edges, known)
    return count


def upsert_buddies(
    session: Session,
    edges: list[tuple[str, str, float]] | list[dict[str, Any]],
    known_ids: set[str] | None = None,
) -> int:
    normalized: list[tuple[str, str, float]] = []
    for item in edges:
        if isinstance(item, dict):
            left = str(item.get("primary_station_id") or item.get("station_id") or "")
            right = str(item.get("buddy_station_id") or item.get("buddy_id") or "")
            try:
                distance = float(item["distance_km"])
            except (KeyError, TypeError, ValueError):
                continue
        else:
            left, right, distance = item
        if not left or not right:
            continue
        if known_ids is not None and (left not in known_ids or right not in known_ids):
            continue
        normalized.append((left, right, float(distance)))

    if known_ids:
        session.execute(delete(StationBuddy).where(StationBuddy.station_id.in_(known_ids)))
    else:
        session.execute(delete(StationBuddy))
    session.flush()

    count = 0
    seen: set[tuple[str, str]] = set()
    for left, right, distance in normalized:
        key = (left, right)
        if key in seen:
            continue
        session.add(StationBuddy(station_id=left, buddy_id=right, distance_km=distance))
        seen.add(key)
        count += 1
    session.flush()
    return count


def catalog_station_ids(session: Session) -> list[str]:
    return list(session.scalars(select(Station.station_id).order_by(Station.station_id)).all())


def buddy_map_from_db(session: Session) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    rows = session.execute(
        select(StationBuddy.station_id, StationBuddy.buddy_id).order_by(
            StationBuddy.station_id, StationBuddy.buddy_id
        )
    ).all()
    for station_id, buddy_id in rows:
        mapping.setdefault(station_id, []).append(buddy_id)
    return mapping


def neighborhood_ids(session: Session, station_id: str) -> list[str]:
    station = session.get(Station, station_id)
    if station is None:
        raise StationNotFound(station_id)
    buddies = session.scalars(
        select(StationBuddy.buddy_id)
        .where(StationBuddy.station_id == station_id)
        .order_by(StationBuddy.buddy_id)
    ).all()
    return [station_id, *[buddy_id for buddy_id in buddies if buddy_id != station_id]]


def load_buddy_edges_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    if "edges" in document:
        return list(document["edges"])
    return list(document) if isinstance(document, list) else []
