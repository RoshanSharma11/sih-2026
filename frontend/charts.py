"""Observed vs imputed T/P/H. Raw series stay visible."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from theme import CARD, GRID, IMPUTED, MUTED, OBSERVED, TEXT

CHANNELS = (
    ("temp_observed", "temp_imputed", "Temperature °C", "°C"),
    ("pres_observed", "pres_imputed", "Pressure hPa", "hPa"),
    ("rhum_observed", "rhum_imputed", "Humidity %", "%"),
)

CONTRIBUTION = (
    ("contribution_temp", "Temperature", "#0F766E"),
    ("contribution_pres", "Pressure", "#0369A1"),
    ("contribution_rhum", "Humidity", "#6D28D9"),
)


def channel_figure(
    telemetry: list[dict[str, Any]],
    observed_key: str,
    imputed_key: str,
    title: str,
    mark_at: Any | None = None,
) -> go.Figure:
    stamps = [row.get("timestamp") for row in telemetry]
    observed = [row.get(observed_key) for row in telemetry]
    imputed = [row.get(imputed_key) for row in telemetry]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=stamps,
            y=observed,
            mode="lines+markers",
            name="Observed",
            line=dict(color=OBSERVED, width=2),
            marker=dict(size=5),
            connectgaps=False,
        )
    )
    if any(value is not None for value in imputed):
        fig.add_trace(
            go.Scatter(
                x=stamps,
                y=imputed,
                mode="lines",
                name="Predicted",
                line=dict(color=IMPUTED, width=2, dash="dash"),
                connectgaps=False,
            )
        )
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color=TEXT), pad=dict(t=0, b=0)),
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        margin=dict(l=40, r=16, t=36, b=32),
        height=230,
        legend=dict(orientation="h", y=1.18, x=0, font=dict(size=11, color=MUTED)),
        font=dict(color=MUTED, size=11, family="IBM Plex Sans, system-ui, sans-serif"),
        xaxis=dict(gridcolor=GRID, zeroline=False, showline=False, color=MUTED),
        yaxis=dict(gridcolor=GRID, zeroline=False, showline=False, color=MUTED),
        hovermode="x unified",
    )
    if mark_at is not None:
        fig.add_vline(
            x=mark_at,
            line_dash="dot",
            line_color=MUTED,
            line_width=1,
            annotation_text="Pinned alert",
            annotation_position="top",
            annotation_font=dict(size=10, color=MUTED),
        )
    return fig


def telemetry_figures(telemetry: list[dict[str, Any]], mark_at: Any | None = None) -> list[go.Figure]:
    return [
        channel_figure(telemetry, observed, imputed, title, mark_at=mark_at)
        for observed, imputed, title, _unit in CHANNELS
    ]


def contribution_html(alert: dict[str, Any] | None) -> str:
    if not alert:
        return ""
    rows: list[str] = []
    for key, label, color in CONTRIBUTION:
        raw = alert.get(key)
        if raw is None:
            continue
        try:
            pct = float(raw)
        except (TypeError, ValueError):
            continue
        width = max(0.0, min(pct, 100.0))
        rows.append(
            f'<div class="sg-bar-row"><span class="sg-bar-label">{label}</span>'
            f'<div class="sg-bar"><i style="width:{width:.1f}%;background:{color}"></i></div>'
            f'<span class="sg-bar-pct">{pct:.1f}%</span></div>'
        )
    if not rows:
        return ""
    return '<div class="sg-bars">' + "".join(rows) + "</div>"
