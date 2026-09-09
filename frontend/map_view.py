"""India map: view-set markers colored by latest.label. Weather is amber."""

from __future__ import annotations

import math
from typing import Any

import plotly.graph_objects as go

from status import marker_color, short_name, status_label
from theme import CARD, EDGE, MUTED, TEXT

MAP_HEIGHT = 640
FOCUS_DEG = 2.5
MIN_SPAN_DEG = 1.6


def india_map(
    stations: list[dict[str, Any]],
    selected_id: str | None,
    buddies: dict[str, list[str]] | None = None,
) -> go.Figure:
    fig = go.Figure()
    if buddies:
        fig.add_trace(_edge_trace(stations, buddies))

    selected = _selected(stations, selected_id)
    if selected is not None:
        fig.add_trace(
            go.Scattermap(
                lat=[selected["latitude"]],
                lon=[selected["longitude"]],
                mode="markers",
                marker=dict(size=36, color=marker_color(selected), opacity=0.22),
                hoverinfo="skip",
            )
        )

    lats: list[float] = []
    lons: list[float] = []
    colors: list[str] = []
    sizes: list[int] = []
    texts: list[str] = []
    ids: list[str] = []
    hovers: list[str] = []

    for row in stations:
        lats.append(row["latitude"])
        lons.append(row["longitude"])
        colors.append(marker_color(row))
        is_sel = row["station_id"] == (selected["station_id"] if selected else None)
        sizes.append(20 if is_sel else 13)
        label = short_name(row["name"])
        texts.append(label if is_sel else "")
        ids.append(row["station_id"])
        health = row.get("health_score")
        health_txt = f"{health:.0f}" if isinstance(health, (int, float)) else "—"
        hovers.append(
            f"<b>{label}</b> ({row['station_id']})<br>"
            f"{status_label(row)}<br>"
            f"Health {health_txt}<br>"
            "Click to open Station"
        )

    fig.add_trace(
        go.Scattermap(
            lat=lats,
            lon=lons,
            mode="markers+text",
            text=texts,
            textposition="top right",
            textfont=dict(color=TEXT, size=13, family="IBM Plex Sans, system-ui, sans-serif"),
            marker=dict(size=sizes, color=colors, opacity=0.96, allowoverlap=True),
            customdata=ids,
            hovertext=hovers,
            hoverinfo="text",
        )
    )

    camera = map_camera(stations, selected_id)
    fig.update_layout(
        map=dict(
            style="carto-positron",
            center=dict(lat=camera["lat"], lon=camera["lon"]),
            zoom=camera["zoom"],
        ),
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        margin=dict(l=0, r=0, t=0, b=0),
        height=MAP_HEIGHT,
        showlegend=False,
        font=dict(color=MUTED),
        uirevision="network-map",
        hovermode="closest",
    )
    return fig


def map_camera(stations: list[dict[str, Any]], selected_id: str | None) -> dict[str, float]:
    focus = focused_subset(stations, selected_id)
    rows = focus or stations
    lats = [float(row["latitude"]) for row in rows]
    lons = [float(row["longitude"]) for row in rows]
    if not lats:
        return {"lat": 23.4, "lon": 78.0, "zoom": 4.4}
    lat_c = (min(lats) + max(lats)) / 2
    lon_c = (min(lons) + max(lons)) / 2
    span = max(max(lats) - min(lats), max(lons) - min(lons), MIN_SPAN_DEG)
    zoom = max(4.3, min(9.0, math.log2(360.0 / span) - 1.15))
    return {"lat": lat_c, "lon": lon_c, "zoom": round(zoom, 2)}


def focused_subset(stations: list[dict[str, Any]], selected_id: str | None) -> list[dict[str, Any]]:
    if not stations:
        return []
    selected = _selected(stations, selected_id) or stations[0]
    nearby = [
        row
        for row in stations
        if _deg_distance(row, selected) <= FOCUS_DEG
    ]
    return nearby or [selected]


def offscreen_stations(
    stations: list[dict[str, Any]], selected_id: str | None
) -> list[dict[str, Any]]:
    nearby_ids = {row["station_id"] for row in focused_subset(stations, selected_id)}
    return [row for row in stations if row["station_id"] not in nearby_ids]


def _selected(stations: list[dict[str, Any]], selected_id: str | None) -> dict[str, Any] | None:
    if selected_id:
        for row in stations:
            if row["station_id"] == selected_id:
                return row
    return stations[0] if stations else None


def _deg_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    dlat = float(a["latitude"]) - float(b["latitude"])
    dlon = float(a["longitude"]) - float(b["longitude"])
    return math.hypot(dlat, dlon)


def _edge_trace(stations: list[dict[str, Any]], buddies: dict[str, list[str]]) -> go.Scattermap:
    by_id = {row["station_id"]: row for row in stations}
    lats: list[float | None] = []
    lons: list[float | None] = []
    seen: set[tuple[str, str]] = set()
    for station_id, neighbors in buddies.items():
        if station_id not in by_id:
            continue
        for buddy_id in neighbors:
            if buddy_id not in by_id:
                continue
            pair = (station_id, buddy_id) if station_id < buddy_id else (buddy_id, station_id)
            if pair in seen:
                continue
            seen.add(pair)
            a = by_id[pair[0]]
            b = by_id[pair[1]]
            lats.extend([a["latitude"], b["latitude"], None])
            lons.extend([a["longitude"], b["longitude"], None])
    return go.Scattermap(
        lat=lats,
        lon=lons,
        mode="lines",
        line=dict(width=2.4, color=EDGE),
        hoverinfo="skip",
        opacity=0.7,
    )
