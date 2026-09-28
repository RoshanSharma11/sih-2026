"""FastAPI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from skyguard.api.routes_demo import router as demo_router
from skyguard.api.routes_export import router as export_router
from skyguard.api.routes_ingest import router as ingest_router
from skyguard.api.routes_reliability import router as reliability_router
from skyguard.api.routes_query import router as query_router
from skyguard.config import BUDDY_EDGES_PATH, DB_PATH, STATIONS_PATH
from skyguard.data.catalog import read_catalog
from skyguard.db.catalog import load_buddy_edges_document, upsert_buddies, upsert_catalog
from skyguard.db.session import create_tables, make_engine, make_session_factory
from skyguard.engine.adapter import load_qc_engine
from skyguard.engine.demo import DemoController, StreamFilterController
from skyguard.engine.windows import WindowStore
from skyguard.notify import Notifier, notifier_from_env
from skyguard.imd.poller import ImdPoller, ImdStatus, poll_enabled, poll_interval_seconds, poll_minute


def create_app(
    db_path: Path | None = None,
    stations_path: Path | None = None,
    buddy_edges_path: Path | None = None,
    notifier: Notifier | None = None,
) -> FastAPI:
    resolved_db = db_path or DB_PATH
    resolved_stations = stations_path or STATIONS_PATH
    # A custom catalog owns its buddy_ids. The product edges file is only the
    # pair of the default stations.json, unless the caller passes one.
    if buddy_edges_path is not None:
        resolved_edges = buddy_edges_path
    elif stations_path is None:
        resolved_edges = BUDDY_EDGES_PATH
    else:
        resolved_edges = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(resolved_db)
        create_tables(engine)
        factory = make_session_factory(engine)
        app.state.session_factory = factory
        app.state.catalog_ready = False
        app.state.windows = WindowStore()
        app.state.demo = DemoController()
        app.state.stream_filter = StreamFilterController()
        app.state.qc_engine = load_qc_engine()
        app.state.imd_status = ImdStatus()
        app.state.imd_poller = None
        app.state.notifier = notifier if notifier is not None else notifier_from_env()
        session = factory()
        try:
            if resolved_stations.exists():
                document = read_catalog(resolved_stations)
                upsert_catalog(session, document)
                if resolved_edges is not None and resolved_edges.exists():
                    edges_doc = read_catalog(resolved_edges)
                    known = {row["station_id"] for row in document.get("stations", [])}
                    upsert_buddies(session, load_buddy_edges_document(edges_doc), known)
                session.commit()
                app.state.catalog_ready = True
                app.state.windows.hydrate(session)
        finally:
            session.close()
        if poll_enabled(db_path is not None):
            poller = ImdPoller(app, interval_seconds=poll_interval_seconds(), poll_minute=poll_minute())
            app.state.imd_poller = poller
            poller.start()
        yield
        poller_running = getattr(app.state, "imd_poller", None)
        if poller_running is not None:
            poller_running.stop()
        app.state.notifier.close()
        engine.dispose()

    app = FastAPI(title="SkyGuard AI", version="0.1.0", lifespan=lifespan)
    app.include_router(query_router)
    app.include_router(ingest_router)
    app.include_router(demo_router)
    app.include_router(export_router)
    app.include_router(reliability_router)
    return app


app = create_app()
