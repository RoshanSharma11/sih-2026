"""FastAPI runtime. Live AWS only — no DB, no simulator.

Start from repo root:

    uvicorn ml.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .engine import DetectionEngine, UnknownStationError, get_engine


class HourRow(BaseModel):
    timestamp: datetime
    temp: float | None = None
    rhum: float | None = None
    pres: float | None = None


class BuddyPayload(BaseModel):
    station_id: str
    distance_km: float | None = None
    window: list[HourRow] = Field(default_factory=list)


class IngestRequest(BaseModel):
    station_id: str
    timestamp: datetime
    temp: float | None = None
    rhum: float | None = None
    pres: float | None = None
    window: list[HourRow] | None = None
    buddies: list[BuddyPayload] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = get_engine()
    yield


app = FastAPI(
    title="SIH AWS anomaly engine",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _engine() -> DetectionEngine:
    engine = getattr(app.state, "engine", None)
    if engine is None:
        engine = get_engine()
        app.state.engine = engine
    return engine


@app.get("/health")
def health():
    engine = _engine()
    return {
        "ok": True,
        "model_loaded": engine.lstm.loaded,
        "threshold": engine.lstm.threshold,
        "n_stations": len(engine.exported_ids),
        "n_isolates": len(engine.isolates),
    }


@app.get("/buddy-map")
def buddy_map():
    return _engine().buddy_map()


@app.post("/ingest")
def ingest(req: IngestRequest):
    try:
        return _engine().process_aws_data(req.model_dump())
    except UnknownStationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Missing field: {exc}") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("ml.main:app", host="0.0.0.0", port=8000, reload=True)
