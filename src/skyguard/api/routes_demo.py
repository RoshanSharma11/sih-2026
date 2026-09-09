"""POST /demo/inject, POST /demo/reset, GET /demo/status, stream-filter."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from skyguard.api.deps import get_db
from skyguard.db.catalog import buddy_map_from_db, catalog_station_ids, neighborhood_ids
from skyguard.db.models import Station
from skyguard.errors import CatalogNotLoaded, InvalidDemoRequest, StationNotFound
from skyguard.schemas import DemoInjectRequest, DemoStatus, StreamFilterRequest, StreamFilterStatus

router = APIRouter()

CLUSTER_REJECTED = "cluster target is no longer valid; use neighborhood with station_id"


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, CatalogNotLoaded):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, StationNotFound):
        return HTTPException(status_code=404, detail=f"Unknown station_id: {exc}")
    if isinstance(exc, InvalidDemoRequest):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


def _require_catalog(request: Request) -> None:
    if not request.app.state.catalog_ready:
        raise CatalogNotLoaded("Station catalog not loaded")


def _resolve_stations(session: Session, body: DemoInjectRequest) -> list[str]:
    if body.target == "cluster":
        raise InvalidDemoRequest(CLUSTER_REJECTED)
    if body.target == "station":
        assert body.station_id is not None
        station = session.get(Station, body.station_id)
        if station is None:
            raise StationNotFound(body.station_id)
        return [station.station_id]
    assert body.station_id is not None
    return neighborhood_ids(session, body.station_id)


def _filter_snapshot(request: Request, session: Session) -> StreamFilterStatus:
    known = catalog_station_ids(session)
    return request.app.state.stream_filter.snapshot(known, buddy_map_from_db(session))


@router.post("/demo/inject", response_model=DemoStatus)
def inject_demo(
    body: DemoInjectRequest,
    request: Request,
    session: Session = Depends(get_db),
) -> DemoStatus:
    try:
        _require_catalog(request)
        station_ids = _resolve_stations(session, body)
        request.app.state.demo.arm(body, station_ids)
    except (CatalogNotLoaded, StationNotFound, InvalidDemoRequest) as exc:
        raise _translate(exc) from exc
    return request.app.state.demo.status()


@router.post("/demo/reset", response_model=DemoStatus)
def reset_demo(request: Request) -> DemoStatus:
    request.app.state.demo.reset()
    return request.app.state.demo.status()


@router.get("/demo/status", response_model=DemoStatus)
def demo_status(request: Request) -> DemoStatus:
    return request.app.state.demo.status()


@router.get("/demo/stream-filter", response_model=StreamFilterStatus)
def get_stream_filter(request: Request, session: Session = Depends(get_db)) -> StreamFilterStatus:
    try:
        _require_catalog(request)
        return _filter_snapshot(request, session)
    except CatalogNotLoaded as exc:
        raise _translate(exc) from exc


@router.post("/demo/stream-filter", response_model=StreamFilterStatus)
def set_stream_filter(
    body: StreamFilterRequest,
    request: Request,
    session: Session = Depends(get_db),
) -> StreamFilterStatus:
    try:
        _require_catalog(request)
        known = set(catalog_station_ids(session))
        unknown = [station_id for station_id in body.station_ids if station_id not in known]
        if unknown:
            raise StationNotFound(", ".join(unknown))
        request.app.state.stream_filter.set(body.station_ids, body.include_buddies)
        return _filter_snapshot(request, session)
    except (CatalogNotLoaded, StationNotFound) as exc:
        raise _translate(exc) from exc
