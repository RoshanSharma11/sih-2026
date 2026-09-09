"""India map: view-set markers colored by latest.label. Weather is amber."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from status import marker_color, short_name, status_label
from theme import CARD, MAP_BORDER, MAP_LAND, MAP_OCEAN, MUTED, TEXT

EDGE = "#94A3B8"


def india_map(
    stations: list[dict[str, Any]],
    selected_id: str | None,
    buddies: dict[str, list[str]] | None = None,
) -> go.Figure:
    fig = go.Figure()
    if buddies:
        fig.add_trace(_edge_trace(stations, buddies))

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
        sizes.append(22 if row["station_id"] == selected_id else 16)
        label = short_name(row["name"])
        texts.append(label)
        ids.append(row["station_id"])
        health = row.get("health_score")
        health_txt = f"{health:.0f}" if isinstance(health, (int, float)) else "—"
        hovers.append(
            f"<b>{label}</b> ({row['station_id']})<br>"
            f"{status_label(row)}<br>"
            f"Health {health_txt}"
        )

    fig.add_trace(
        go.Scattergeo(
            lat=lats,
            lon=lons,
            mode="markers+text",
            text=texts,
            textposition="top center",
            textfont=dict(color=TEXT, size=12, family="IBM Plex Sans, system-ui, sans-serif"),
            marker=dict(
                size=sizes,
                color=colors,
                opacity=0.95,
                line=dict(width=2, color=CARD),
                symbol="circle",
            ),
            customdata=ids,
            hovertext=hovers,
            hoverinfo="text",
        )
    )
    fig.update_geos(
        projection_type="mercator",
        center=dict(lat=23.4, lon=78.0),
        lataxis_range=[7.5, 33.5],
        lonaxis_range=[67.5, 89.5],
        showland=True,
        landcolor=MAP_LAND,
        showocean=True,
        oceancolor=MAP_OCEAN,
        showcountries=True,
        countrycolor=MAP_BORDER,
        showcoastlines=True,
        coastlinecolor=MAP_BORDER,
        showlakes=False,
        showframe=False,
        bgcolor=MAP_OCEAN,
        resolution=50,
    )
    fig.update_layout(
        paper_bgcolor=MAP_OCEAN,
        plot_bgcolor=MAP_OCEAN,
        margin=dict(l=0, r=0, t=8, b=0),
        height=460,
        showlegend=False,
        font=dict(color=MUTED),
        dragmode=False,
    )
    return fig


def _edge_trace(stations: list[dict[str, Any]], buddies: dict[str, list[str]]) -> go.Scattergeo:
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
    return go.Scattergeo(
        lat=lats,
        lon=lons,
        mode="lines",
        line=dict(width=1.4, color=EDGE),
        hoverinfo="skip",
    )
