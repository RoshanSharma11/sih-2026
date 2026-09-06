"""POST /ingest — persist-only in slice 1b."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from skyguard.api.deps import get_db
from skyguard.engine.pipeline import ingest_observation
from skyguard.errors import CatalogNotLoaded, DuplicateObservation, StationNotFound
from skyguard.schemas import IngestPayload, IngestResult

router = APIRouter()


@router.post("/ingest", response_model=IngestResult)
def ingest(payload: IngestPayload, request: Request, session: Session = Depends(get_db)) -> IngestResult:
    try:
        return ingest_observation(session, payload, request.app.state.catalog_ready)
    except CatalogNotLoaded as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except StationNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Unknown station_id: {exc}") from exc
    except DuplicateObservation as exc:
        raise HTTPException(status_code=409, detail=f"Duplicate observation: {exc}") from exc
