"""ORM tables matching docs/contracts.md."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Station(Base):
    __tablename__ = "stations"

    station_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    isolate: Mapped[bool] = mapped_column(Boolean, default=False)
    health_score: Mapped[float] = mapped_column(Float, default=100.0)
    status: Mapped[str] = mapped_column(String(20), default="HEALTHY")

    telemetry: Mapped[list[TelemetryLog]] = relationship(back_populates="station")
    alerts: Mapped[list[AnomalyAlert]] = relationship(back_populates="station")
    buddies: Mapped[list[StationBuddy]] = relationship(
        back_populates="station",
        cascade="all, delete-orphan",
        foreign_keys="StationBuddy.station_id",
    )


class StationBuddy(Base):
    __tablename__ = "station_buddies"

    station_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("stations.station_id"), primary_key=True
    )
    buddy_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("stations.station_id"), primary_key=True
    )
    distance_km: Mapped[float] = mapped_column(Float)

    station: Mapped[Station] = relationship(
        back_populates="buddies",
        foreign_keys=[station_id],
    )


class TelemetryLog(Base):
    __tablename__ = "telemetry_logs"
    __table_args__ = (UniqueConstraint("station_id", "timestamp", name="uq_telemetry_station_time"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[str] = mapped_column(String(20), ForeignKey("stations.station_id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    temp_observed: Mapped[float | None] = mapped_column(Float, nullable=True)
    pres_observed: Mapped[float | None] = mapped_column(Float, nullable=True)
    rhum_observed: Mapped[float | None] = mapped_column(Float, nullable=True)
    temp_imputed: Mapped[float | None] = mapped_column(Float, nullable=True)
    pres_imputed: Mapped[float | None] = mapped_column(Float, nullable=True)
    rhum_imputed: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    label: Mapped[str] = mapped_column(String(40), default="CLEAN")
    pipeline_status: Mapped[str] = mapped_column(String(20), default="CLEAN")
    mse: Mapped[float | None] = mapped_column(Float, nullable=True)

    station: Mapped[Station] = relationship(back_populates="telemetry")


class AnomalyAlert(Base):
    __tablename__ = "anomaly_alerts"

    alert_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[str] = mapped_column(String(20), ForeignKey("stations.station_id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    label: Mapped[str] = mapped_column(String(40), default="CLEAN")
    fault_type: Mapped[str] = mapped_column(String(50))
    confidence_score: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(20))
    explainability_text: Mapped[str] = mapped_column(String)
    contribution_temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    contribution_pres: Mapped[float | None] = mapped_column(Float, nullable=True)
    contribution_rhum: Mapped[float | None] = mapped_column(Float, nullable=True)

    station: Mapped[Station] = relationship(back_populates="alerts")
