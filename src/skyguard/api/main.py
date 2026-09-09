"""FastAPI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from skyguard.api.routes_demo import router as demo_router
from skyguard.api.routes_ingest import router as ingest_router
from skyguard.api.routes_query import router as query_router
from skyguard.config import BUDDY_EDGES_PATH, DB_PATH, STATIONS_PATH
from skyguard.data.catalog import read_catalog
from skyguard.db.catalog import load_buddy_edges_document, upsert_buddies, upsert_catalog
from skyguard.db.session import create_tables, make_engine, make_session_factory
from skyguard.engine.adapter import load_qc_engine
from skyguard.engine.demo import DemoController
from skyguard.engine.windows import WindowStore


def create_app(
    db_path: Path | None = None,
    stations_path: Path | None = None,
    buddy_edges_path: Path | None = None,
) -> FastAPI:
    resolved_db = db_path or DB_PATH
    resolved_stations = stations_path or STATIONS_PATH
    resolved_edges = buddy_edges_path or BUDDY_EDGES_PATH

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(resolved_db)
        create_tables(engine)
        factory = make_session_factory(engine)
        app.state.session_factory = factory
        app.state.catalog_ready = False
        app.state.windows = WindowStore()
        app.state.demo = DemoController()
        app.state.qc_engine = load_qc_engine()
        session = factory()
        try:
            if resolved_stations.exists():
                document = read_catalog(resolved_stations)
                upsert_catalog(session, document)
                if resolved_edges.exists():
                    edges_doc = read_catalog(resolved_edges)
                    known = {row["station_id"] for row in document.get("stations", [])}
                    upsert_buddies(session, load_buddy_edges_document(edges_doc), known)
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
