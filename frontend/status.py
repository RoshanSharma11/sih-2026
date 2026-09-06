"""Display helpers for pipeline_status. Colors are UI-only; they are not API fields."""

from __future__ import annotations

from typing import Any

PIPELINE_COLOR = {
    "CLEAN": "#2dd4bf",
    "GENUINE_WEATHER": "#f5b942",
    "HARDWARE": "#f43f5e",
    "UNKNOWN": "#94a3b8",
}

PIPELINE_LABEL = {
    "CLEAN": "Clean",
    "GENUINE_WEATHER": "Genuine weather",
    "HARDWARE": "Hardware fault",
    "UNKNOWN": "Unknown",
}

IDLE_COLOR = "#3d4f6f"
IDLE_LABEL = "Waiting for stream"

HEALTH_COLOR = {
    "HEALTHY": "#2dd4bf",
    "DEGRADED": "#f5b942",
    "CRITICAL": "#f43f5e",
}


def short_name(name: str) -> str:
    if "/" in name:
        return name.split("/")[-1].strip()
    return name


def pipeline_status(station: dict[str, Any]) -> str | None:
    return station.get("pipeline_status")


def pipeline_color(status: str | None) -> str:
    if not status:
        return IDLE_COLOR
    return PIPELINE_COLOR.get(status, IDLE_COLOR)


def pipeline_label(status: str | None) -> str:
    if not status:
        return IDLE_LABEL
    return PIPELINE_LABEL.get(status, status)


def health_color(status: str | None) -> str:
    if not status:
        return IDLE_COLOR
    return HEALTH_COLOR.get(status, IDLE_COLOR)


def is_weather(status: str | None, fault_type: str | None = None) -> bool:
    return status == "GENUINE_WEATHER" or fault_type == "GENUINE_WEATHER"


def is_hardware(status: str | None, fault_type: str | None = None) -> bool:
    if status == "HARDWARE":
        return True
    return fault_type in {
        "SPIKE",
        "FREEZE",
        "DRIFT",
        "COMM_ERROR",
        "PHYSICS_BREACH",
    }


def selected_station(stations: list[dict[str, Any]], station_id: str | None) -> dict[str, Any] | None:
    for row in stations:
        if row["station_id"] == station_id:
            return row
    return stations[0] if stations else None


def overlay_caption(overlay: dict[str, Any]) -> str:
    kind = overlay.get("kind", "?")
    hours = overlay.get("remaining_hours")
    ids = overlay.get("station_ids") or []
    channel = overlay.get("channel")
    who = ", ".join(ids) if ids else "armed"
    extra = f" · {channel}" if channel else ""
    return f"{kind}{extra} on {who} · {hours}h left"
