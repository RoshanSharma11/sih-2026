"""India map: four AWS markers colored by latest pipeline_status."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from status import pipeline_color, pipeline_label, short_name

PAPER = "#070b14"
LAND = "#152036"
OCEAN = "#070b14"
GRID = "#24344f"


def india_map(stations: list[dict[str, Any]], selected_id: str | None) -> go.Figure:
    lats: list[float] = []
    lons: list[float] = []
    colors: list[str] = []
    sizes: list[int] = []
    texts: list[str] = []
    ids: list[str] = []
    hovers: list[str] = []

    for row in stations:
        status = row.get("pipeline_status")
        lats.append(row["latitude"])
        lons.append(row["longitude"])
        colors.append(pipeline_color(status))
        sizes.append(22 if row["station_id"] == selected_id else 16)
        label = short_name(row["name"])
        texts.append(label)
        ids.append(row["station_id"])
        health = row.get("health_score")
        health_txt = f"{health:.0f}" if isinstance(health, (int, float)) else "—"
        hovers.append(
            f"<b>{label}</b> ({row['station_id']})<br>"
            f"{row.get('cluster_id', '')} · {pipeline_label(status)}<br>"
            f"Health {health_txt}"
        )

    fig = go.Figure(
        go.Scattergeo(
            lat=lats,
            lon=lons,
            mode="markers+text",
            text=texts,
            textposition="top center",
            textfont=dict(color="#e8eef7", size=12, family="Inter, system-ui, sans-serif"),
            marker=dict(
                size=sizes,
                color=colors,
                opacity=0.95,
                line=dict(width=2, color="#e8eef7"),
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
        landcolor=LAND,
        showocean=True,
        oceancolor=OCEAN,
        showcountries=True,
        countrycolor=GRID,
        showcoastlines=True,
        coastlinecolor=GRID,
        showlakes=False,
        showframe=False,
        bgcolor=PAPER,
        resolution=50,
    )
    fig.update_layout(
        paper_bgcolor=PAPER,
        plot_bgcolor=PAPER,
        margin=dict(l=0, r=0, t=8, b=0),
        height=430,
        showlegend=False,
        font=dict(color="#e8eef7"),
        dragmode=False,
    )
    return fig
