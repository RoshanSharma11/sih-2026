"""V2 FastAPI. From repo root: uvicorn v2.main:app --port 8001"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .engine import DetectionEngine, UnknownStationError, get_engine
from .config import ARTIFACTS_DIR, resolve_weights_path


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


app = FastAPI(title="SkyGuard V2", version="2.0.0-slice-a", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _engine() -> DetectionEngine:
    engine = getattr(app.state, "engine", None)
    if engine is None:
        engine = get_engine()
        app.state.engine = engine
    return engine


@app.get("/healthz")
@app.get("/health")
def health():
    engine = _engine()
    overlay = (ARTIFACTS_DIR / "overlay.pt").is_file()
    stgnn = (ARTIFACTS_DIR / "stgnn.pt").is_file()
    return {
        "ok": True,
        "model_loaded": engine.lstm.loaded,
        "threshold": engine.lstm.threshold,
        "stgnn_loaded": engine.stgnn.loaded,
        "stgnn_on": engine.use_stgnn,
        "n_stations": len(engine.exported_ids),
        "timing_async": engine.timing_async,
        "v2_artifacts": {
            "lstm": resolve_weights_path() is not None,
            "stgnn": stgnn,
            "stgnn_gates": bool(engine.stgnn.metadata.get("gates_passed")),
            "overlay": overlay,
            "overlay_gates": bool(engine.overlay.metadata.get("gates_passed")),
            "overlay_loaded": engine.overlay.loaded,
        },
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


@app.get("/stations/{station_id}/timing")
def station_timing(station_id: str, ts: datetime, wait_s: float = 0.0):
    try:
        _engine()._reject_unknown(str(station_id))
    except UnknownStationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    out = _engine().get_timing(str(station_id), ts, wait_s=min(max(wait_s, 0.0), 10.0))
    return out
