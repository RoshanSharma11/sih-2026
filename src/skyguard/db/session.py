"""Engine and session factory."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from skyguard.config import DB_PATH
from skyguard.db.models import Base

_EXTRA_COLUMNS = (
    ("telemetry_logs", "label", "VARCHAR(40) NOT NULL DEFAULT 'CLEAN'"),
    ("anomaly_alerts", "label", "VARCHAR(40) NOT NULL DEFAULT 'CLEAN'"),
    ("stations", "isolate", "BOOLEAN NOT NULL DEFAULT 0"),
)


def make_engine(db_path: Path | None = None) -> Engine:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", future=True)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def create_tables(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    _ensure_columns(engine)


def _ensure_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, ddl in _EXTRA_COLUMNS:
            if table not in tables:
                continue
            existing = {col["name"] for col in inspector.get_columns(table)}
            if column in existing:
                continue
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            except OperationalError:
                continue
