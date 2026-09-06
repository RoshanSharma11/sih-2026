"""FastAPI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from skyguard.api.routes_demo import router as demo_router
from skyguard.api.routes_ingest import router as ingest_router
from skyguard.api.routes_query import router as query_router
from skyguard.config import DB_PATH, STATIONS_PATH
from skyguard.data.catalog import read_catalog
from skyguard.db.catalog import upsert_catalog
from skyguard.db.session import create_tables, make_engine, make_session_factory
from skyguard.engine.demo import DemoController
from skyguard.engine.tier3 import ResidualStore
from skyguard.engine.windows import WindowStore
from skyguard.ml import load_detector


def create_app(db_path: Path | None = None, stations_path: Path | None = None) -> FastAPI:
    resolved_db = db_path or DB_PATH
    resolved_stations = stations_path or STATIONS_PATH

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(resolved_db)
        create_tables(engine)
        factory = make_session_factory(engine)
        app.state.session_factory = factory
        app.state.catalog_ready = False
        app.state.windows = WindowStore()
        app.state.residuals = ResidualStore()
        app.state.demo = DemoController()
        app.state.detector = load_detector()
        session = factory()
        try:
            if resolved_stations.exists():
                upsert_catalog(session, read_catalog(resolved_stations))
                session.commit()
                app.state.catalog_ready = True
                app.state.windows.hydrate(session)
        finally:
            session.close()
        yield
        engine.dispose()

    app = FastAPI(title="SkyGuard AI", version="0.1.0", lifespan=lifespan)
    app.include_router(query_router)
    app.include_router(ingest_router)
    app.include_router(demo_router)
    return app


app = create_app()
