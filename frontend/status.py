"""Display helpers. Colors are UI-only; they are not API fields."""

from __future__ import annotations

from typing import Any

# Light-theme status colors (docs/frontend.md). Weather is amber, never rose.
LABEL_COLOR = {
    "CLEAN": "#0D9488",
    "GENUINE_WEATHER_EVENT": "#D97706",
    "PHYSICAL_FAULT": "#E11D48",
    "HARDWARE_ANOMALY": "#E11D48",
    "UNCONFIRMED_ANOMALY": "#64748B",
}

PIPELINE_COLOR = {
    "CLEAN": "#0D9488",
    "GENUINE_WEATHER": "#D97706",
    "HARDWARE": "#E11D48",
    "UNKNOWN": "#64748B",
}

LABEL_TEXT = {
    "CLEAN": "Clean",
    "GENUINE_WEATHER_EVENT": "Genuine weather",
    "PHYSICAL_FAULT": "Physical fault",
    "HARDWARE_ANOMALY": "Hardware anomaly",
    "UNCONFIRMED_ANOMALY": "Unconfirmed",
}

PIPELINE_LABEL = {
    "CLEAN": "Clean",
    "GENUINE_WEATHER": "Genuine weather",
    "HARDWARE": "Hardware fault",
    "UNKNOWN": "Unknown",
}

IDLE_COLOR = "#64748B"
IDLE_LABEL = "Waiting for stream"

HEALTH_COLOR = {
    "HEALTHY": "#0D9488",
    "DEGRADED": "#D97706",
    "CRITICAL": "#E11D48",
}

WEATHER_LABELS = {"GENUINE_WEATHER_EVENT"}
HARDWARE_LABELS = {"PHYSICAL_FAULT", "HARDWARE_ANOMALY"}
WEATHER_PIPELINE = {"GENUINE_WEATHER"}
HARDWARE_PIPELINE = {"HARDWARE"}
HARDWARE_FAULTS = {"SPIKE", "FREEZE", "DRIFT", "COMM_ERROR", "PHYSICS_BREACH"}


def short_name(name: str) -> str:
    if "/" in name:
        return name.split("/")[-1].strip()
    return name


def latest_payload(station: dict[str, Any] | None) -> dict[str, Any]:
    if not station:
        return {}
    latest = station.get("latest")
    return latest if isinstance(latest, dict) else {}


def station_label(station: dict[str, Any] | None) -> str | None:
    latest = latest_payload(station)
    label = latest.get("label")
    if label:
        return str(label)
    if station:
        return station.get("label")
    return None


def pipeline_status(station: dict[str, Any] | None) -> str | None:
    latest = latest_payload(station)
    status = latest.get("pipeline_status")
    if status:
        return str(status)
    if station:
        return station.get("pipeline_status")
    return None


def marker_key(station: dict[str, Any] | None) -> str | None:
    """Prefer five-way label; fall back to pipeline_status (D18)."""
    return station_label(station) or pipeline_status(station)


def pipeline_color(status: str | None) -> str:
    if not status:
        return IDLE_COLOR
    if status in LABEL_COLOR:
        return LABEL_COLOR[status]
    return PIPELINE_COLOR.get(status, IDLE_COLOR)


def marker_color(station: dict[str, Any] | None) -> str:
    return pipeline_color(marker_key(station))


def pipeline_label(status: str | None) -> str:
    if not status:
        return IDLE_LABEL
    if status in LABEL_TEXT:
        return LABEL_TEXT[status]
    return PIPELINE_LABEL.get(status, status)


def status_label(station: dict[str, Any] | None) -> str:
    if station and latest_payload(station) == {} and not station.get("pipeline_status"):
        return IDLE_LABEL
    key = marker_key(station)
    if key is None and station and not latest_payload(station):
        return IDLE_LABEL
    return pipeline_label(key)


def health_color(status: str | None) -> str:
    if not status:
        return IDLE_COLOR
    return HEALTH_COLOR.get(status, IDLE_COLOR)


def is_weather(status: str | None, fault_type: str | None = None) -> bool:
    return (
        status in WEATHER_LABELS
        or status in WEATHER_PIPELINE
        or fault_type == "GENUINE_WEATHER"
    )


def is_hardware(status: str | None, fault_type: str | None = None) -> bool:
    if status in HARDWARE_LABELS or status in HARDWARE_PIPELINE:
        return True
    return fault_type in HARDWARE_FAULTS


def verdict_kind(station: dict[str, Any] | None, fault_type: str | None = None) -> str:
    key = marker_key(station)
    if is_weather(key, fault_type):
        return "weather"
    if is_hardware(key, fault_type):
        return "hardware"
    if key in {"UNCONFIRMED_ANOMALY", "UNKNOWN"}:
        return "unknown"
    if key in {"CLEAN"}:
        return "clean"
    if not latest_payload(station) and not pipeline_status(station):
        return "idle"
    return "clean"


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


def kpi_counts(stations: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"clean": 0, "weather": 0, "hardware": 0, "unconfirmed": 0, "idle": 0}
    for row in stations:
        latest = latest_payload(row)
        if not latest and not row.get("pipeline_status"):
            counts["idle"] += 1
            continue
        key = marker_key(row)
        kind = verdict_kind(row)
        if kind == "weather":
            counts["weather"] += 1
        elif kind == "hardware":
            counts["hardware"] += 1
        elif kind == "unknown":
            counts["unconfirmed"] += 1
        elif kind == "idle" or key is None:
            counts["idle"] += 1
        else:
            counts["clean"] += 1
    return counts
