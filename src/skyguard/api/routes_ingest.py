"""POST /ingest and POST /stations/{id}/seed."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from skyguard.api.deps import get_db
from skyguard.engine.pipeline import ingest_observation, seed_station
from skyguard.errors import CatalogNotLoaded, DuplicateObservation, StationNotFound
from skyguard.schemas import IngestPayload, IngestResult, SeedPayload, SeedResult

router = APIRouter()


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, CatalogNotLoaded):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, StationNotFound):
        return HTTPException(status_code=404, detail=f"Unknown station_id: {exc}")
    if isinstance(exc, DuplicateObservation):
        return HTTPException(status_code=409, detail=f"Duplicate observation: {exc}")
    raise exc


@router.post("/ingest", response_model=IngestResult)
def ingest(payload: IngestPayload, request: Request, session: Session = Depends(get_db)) -> IngestResult:
    try:
        return ingest_observation(
            session,
            payload,
            request.app.state.catalog_ready,
            request.app.state.windows,
            request.app.state.residuals,
            request.app.state.demo,
            request.app.state.detector,
        )
    except (CatalogNotLoaded, StationNotFound, DuplicateObservation) as exc:
        raise _translate(exc) from exc


@router.post("/stations/{station_id}/seed", response_model=SeedResult)
def seed(
    station_id: str,
    payload: SeedPayload,
    request: Request,
    session: Session = Depends(get_db),
) -> SeedResult:
    try:
        accepted, skipped = seed_station(
            session,
            station_id,
            payload.observations,
            request.app.state.catalog_ready,
            request.app.state.windows,
        )
    except (CatalogNotLoaded, StationNotFound) as exc:
        raise _translate(exc) from exc
    return SeedResult(station_id=station_id, accepted=accepted, skipped=skipped)
