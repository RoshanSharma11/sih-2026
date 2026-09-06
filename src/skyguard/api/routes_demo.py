"""POST /demo/inject, POST /demo/reset, GET /demo/status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from skyguard.api.deps import get_db
from skyguard.db.models import Station
from skyguard.errors import CatalogNotLoaded, InvalidDemoRequest, StationNotFound
from skyguard.schemas import DemoInjectRequest, DemoStatus

router = APIRouter()


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
    if body.target == "station":
        assert body.station_id is not None
        station = session.get(Station, body.station_id)
        if station is None:
            raise StationNotFound(body.station_id)
        return [station.station_id]

    assert body.cluster_id is not None
    rows = session.scalars(
        select(Station.station_id)
        .where(Station.cluster_id == body.cluster_id.value)
        .order_by(Station.station_id)
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Unknown cluster_id: {body.cluster_id.value}")
    return list(rows)


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
