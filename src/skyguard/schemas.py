"""Pydantic contracts. Field names match docs/contracts.md."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FaultType(str, Enum):
    SPIKE = "SPIKE"
    FREEZE = "FREEZE"
    DRIFT = "DRIFT"
    COMM_ERROR = "COMM_ERROR"
    PHYSICS_BREACH = "PHYSICS_BREACH"
    GENUINE_WEATHER = "GENUINE_WEATHER"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class StationStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


class PipelineStatus(str, Enum):
    CLEAN = "CLEAN"
    GENUINE_WEATHER = "GENUINE_WEATHER"
    HARDWARE = "HARDWARE"
    UNKNOWN = "UNKNOWN"


class Channel(str, Enum):
    TEMP_C = "temp_c"
    PRES_HPA = "pres_hpa"
    RHUM_PCT = "rhum_pct"


class ClusterId(str, Enum):
    NORTH = "NORTH"
    WEST = "WEST"


class DemoKind(str, Enum):
    SPIKE = "SPIKE"
    FREEZE = "FREEZE"
    DRIFT = "DRIFT"
    COMM_ERROR = "COMM_ERROR"
    GENUINE_WEATHER = "GENUINE_WEATHER"


CHANNEL_FAULTS = {DemoKind.SPIKE, DemoKind.FREEZE, DemoKind.DRIFT}


class ChannelValues(BaseModel):
    temp_c: float | None = None
    pres_hpa: float | None = None
    rhum_pct: float | None = None


class IngestPayload(BaseModel):
    station_id: str
    timestamp: datetime
    temp_c: float | None
    pres_hpa: float | None
    rhum_pct: float | None
    sequence_id: int | None = None


class SeedObservation(BaseModel):
    timestamp: datetime
    temp_c: float | None
    pres_hpa: float | None
    rhum_pct: float | None


class SeedPayload(BaseModel):
    observations: list[SeedObservation] = Field(min_length=1, max_length=48)


class SeedResult(BaseModel):
    station_id: str
    accepted: int
    skipped: int


class IngestResult(BaseModel):
    station_id: str
    timestamp: datetime
    pipeline_status: PipelineStatus
    fault_type: FaultType | None = None
    confidence: float | None = None
    severity: Severity | None = None
    explainability_text: str | None = None
    contribution_pct: ChannelValues
    observed: ChannelValues
    imputed: ChannelValues
    mse: float | None = None
    mse_vector: ChannelValues
    health_score: float
    station_status: StationStatus
    demo_injected: FaultType | None = None


class DemoInjectRequest(BaseModel):
    target: Literal["station", "cluster"]
    station_id: str | None = None
    cluster_id: ClusterId | None = None
    kind: DemoKind
    channel: Channel | None = None
    duration_hours: int | None = None

    @model_validator(mode="after")
    def validate_demo_rules(self) -> DemoInjectRequest:
        if self.kind == DemoKind.GENUINE_WEATHER and self.target != "cluster":
            raise ValueError("GENUINE_WEATHER inject must target a cluster")
        if self.kind != DemoKind.GENUINE_WEATHER and self.target != "station":
            raise ValueError("hardware inject must target a station")
        if self.kind in CHANNEL_FAULTS and self.channel is None:
            raise ValueError(f"{self.kind.value} requires channel")
        if self.target == "station" and not self.station_id:
            raise ValueError("station target requires station_id")
        if self.target == "cluster" and self.cluster_id is None:
            raise ValueError("cluster target requires cluster_id")
        return self


class StationSummary(BaseModel):
    station_id: str
    name: str
    latitude: float
    longitude: float
    elevation_m: float | None = None
    cluster_id: ClusterId
    health_score: float
    status: StationStatus


class StationDetail(StationSummary):
    latest: IngestResult | None = None


class TelemetryRow(BaseModel):
    station_id: str
    timestamp: datetime
    temp_observed: float | None
    pres_observed: float | None
    rhum_observed: float | None
    temp_imputed: float | None
    pres_imputed: float | None
    rhum_imputed: float | None
    is_anomaly: bool
    pipeline_status: PipelineStatus
    mse: float | None = None


class AlertRow(BaseModel):
    alert_id: int
    station_id: str
    timestamp: datetime
    fault_type: FaultType
    confidence_score: float
    severity: Severity
    explainability_text: str
    contribution_temp: float | None = None
    contribution_pres: float | None = None
    contribution_rhum: float | None = None


class Healthz(BaseModel):
    ok: bool = True


class DemoOverlayStatus(BaseModel):
    kind: DemoKind
    station_ids: list[str]
    channel: Channel | None = None
    remaining_hours: int
    hour_index: int


class DemoStatus(BaseModel):
    overlays: list[DemoOverlayStatus]
