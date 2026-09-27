"""Engine and session factory."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from skyguard.config import DB_PATH
from skyguard.db.models import Base, TelemetryLog

_EXTRA_COLUMNS = (
    ("telemetry_logs", "label", "VARCHAR(40) NOT NULL DEFAULT 'CLEAN'"),
    ("anomaly_alerts", "label", "VARCHAR(40) NOT NULL DEFAULT 'CLEAN'"),
    ("stations", "isolate", "BOOLEAN NOT NULL DEFAULT 0"),
    ("stations", "aws_id", "VARCHAR(32)"),
    ("stations", "aws_name", "VARCHAR(100)"),
    ("stations", "aws_distance_km", "REAL"),
    ("telemetry_logs", "explainability_text", "TEXT"),
    ("telemetry_logs", "imputed_interval", "TEXT"),
    ("telemetry_logs", "thermo", "TEXT"),
    ("telemetry_logs", "tier2_score", "REAL"),
    ("telemetry_logs", "tier3_method", "VARCHAR(20)"),
    ("telemetry_logs", "tier3_mix", "TEXT"),
    ("telemetry_logs", "tier3_corr", "TEXT"),
    ("telemetry_logs", "warming_up", "BOOLEAN NOT NULL DEFAULT 0"),
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
    _relax_telemetry_labels(engine)


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


def _relax_telemetry_labels(engine: Engine) -> None:
    """Let a warming hour store a null label. Older databases marked that column required."""
    inspector = inspect(engine)
    if "telemetry_logs" not in set(inspector.get_table_names()):
        return
    columns = {col["name"]: col for col in inspector.get_columns("telemetry_logs")}
    blocked = [
        name
        for name in ("label", "pipeline_status")
        if name in columns and not columns[name]["nullable"]
    ]
    if not blocked:
        return
    old_names = list(columns)
    indexes = [
        index["name"]
        for index in inspector.get_indexes("telemetry_logs")
        if index.get("name") and not str(index["name"]).startswith("sqlite_")
    ]
    shared = [name for name in TelemetryLog.__table__.columns.keys() if name in old_names]
    quoted = ", ".join(shared)
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        for name in indexes:
            conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
        conn.execute(text("ALTER TABLE telemetry_logs RENAME TO telemetry_logs_old"))
        TelemetryLog.__table__.create(conn)
        conn.execute(
            text(
                f"INSERT INTO telemetry_logs ({quoted}) "
                f"SELECT {quoted} FROM telemetry_logs_old"
            )
        )
        conn.execute(text("DROP TABLE telemetry_logs_old"))
