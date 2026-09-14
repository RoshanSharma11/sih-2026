"""Observed vs imputed T/P/H. Raw series stay visible; markers carry the QC label."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import plotly.graph_objects as go

from status import (
    fault_label,
    pipeline_color,
    pipeline_label,
    stamp_key,
)
from theme import CARD, GRID, HARDWARE, IMPUTED, MUTED, OBSERVED, SLATE, TEXT, WEATHER

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

_FILL = {
    "GENUINE_WEATHER_EVENT": WEATHER,
    "GENUINE_WEATHER": WEATHER,
    "PHYSICAL_FAULT": HARDWARE,
    "HARDWARE_ANOMALY": HARDWARE,
    "HARDWARE": HARDWARE,
    "UNCONFIRMED_ANOMALY": SLATE,
    "UNKNOWN": SLATE,
}


def _fmt_hover(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _as_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _x_range(stamps: list[Any], mark_at: Any | None) -> list[Any] | None:
    if not stamps:
        return None
    if mark_at is not None:
        mark = stamp_key(mark_at)
        idx = next((i for i, stamp in enumerate(stamps) if stamp_key(stamp) == mark), None)
        if idx is None:
            target = _as_dt(mark_at)
            parsed = [_as_dt(stamp) for stamp in stamps]
            if target is not None and any(parsed):
                idx = min(
                    range(len(stamps)),
                    key=lambda i: abs((parsed[i] - target).total_seconds()) if parsed[i] else 10**12,
                )
        if idx is not None:
            lo = max(0, idx - 24)
            hi = min(len(stamps) - 1, idx + 12)
            return [stamps[lo], stamps[hi]]
    if len(stamps) > 48:
        return [stamps[-48], stamps[-1]]
    return None


def _marker_colors(telemetry: list[dict[str, Any]]) -> list[str]:
    return [
        pipeline_color(row.get("label") or row.get("pipeline_status")) for row in telemetry
    ]


def _span_rects(telemetry: list[dict[str, Any]]) -> list[tuple[Any, Any, str, str]]:
    rects: list[tuple[Any, Any, str, str]] = []
    start = None
    color = HARDWARE
    label = ""
    for row in telemetry:
        flagged = bool(row.get("is_anomaly"))
        if flagged and start is None:
            start = row.get("timestamp")
            key = str(row.get("label") or row.get("pipeline_status") or "")
            color = _FILL.get(key, HARDWARE)
            label = fault_label(row.get("fault_type")) if row.get("fault_type") else pipeline_label(key)
        elif not flagged and start is not None:
            rects.append((start, row.get("timestamp"), color, label))
            start = None
    if start is not None and telemetry:
        last = telemetry[-1].get("timestamp")
        end = last
        dt = _as_dt(last)
        if dt is not None:
            end = dt + timedelta(minutes=50)
        rects.append((start, end, color, label))
    return rects


def channel_figure(
    telemetry: list[dict[str, Any]],
    observed_key: str,
    imputed_key: str,
    title: str,
    unit: str,
    mark_at: Any | None = None,
) -> go.Figure:
    stamps = [row.get("timestamp") for row in telemetry]
    observed = [row.get(observed_key) for row in telemetry]
    imputed = [row.get(imputed_key) for row in telemetry]
    colors = _marker_colors(telemetry)
    sizes = [10 if row.get("is_anomaly") else 5 for row in telemetry]
    custom = []
    for row, pred, obs in zip(telemetry, imputed, observed):
        residual = None
        if obs is not None and pred is not None:
            try:
                residual = float(obs) - float(pred)
            except (TypeError, ValueError):
                residual = None
        custom.append(
            [
                _fmt_hover(pred),
                _fmt_hover(residual),
                pipeline_label(row.get("label") or row.get("pipeline_status")),
                fault_label(row.get("fault_type")) if row.get("fault_type") else "—",
            ]
        )
    fig = go.Figure()
    for x0, x1, color, _label in _span_rects(telemetry):
        fig.add_vrect(x0=x0, x1=x1, fillcolor=color, opacity=0.10, line_width=0)
    fig.add_trace(
        go.Scatter(
            x=stamps,
            y=observed,
            mode="lines+markers",
            name="Observed",
            line=dict(color=OBSERVED, width=2),
            marker=dict(size=sizes, color=colors, line=dict(width=0.5, color=CARD)),
            customdata=custom,
            hovertemplate=(
                "%{x}<br>Observed: %{y:.2f} "
                + unit
                + "<br>Predicted: %{customdata[0]} "
                + unit
                + "<br>Residual: %{customdata[1]} "
                + unit
                + "<br>%{customdata[2]} · %{customdata[3]}<extra></extra>"
            ),
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
                hovertemplate="%{x}<br>Predicted: %{y:.2f} " + unit + "<extra></extra>",
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
        yaxis=dict(gridcolor=GRID, zeroline=False, showline=False, color=MUTED, ticksuffix=f" {unit}"),
        hovermode="x unified",
    )
    span = _x_range(stamps, mark_at)
    if span is not None:
        fig.update_xaxes(range=span)
    if mark_at is not None:
        fig.add_vline(
            x=mark_at,
            line_dash="dot",
            line_color=MUTED,
            line_width=1,
            annotation_text="Inspected hour",
            annotation_position="top",
            annotation_font=dict(size=10, color=MUTED),
        )
    return fig


def residual_figure(telemetry: list[dict[str, Any]], mark_at: Any | None = None) -> go.Figure:
    stamps = [row.get("timestamp") for row in telemetry]
    fig = go.Figure()
    series = (
        ("temp_observed", "temp_imputed", "Temperature", OBSERVED),
        ("pres_observed", "pres_imputed", "Pressure", "#0369A1"),
        ("rhum_observed", "rhum_imputed", "Humidity", "#6D28D9"),
    )
    for observed_key, imputed_key, name, color in series:
        residuals: list[float | None] = []
        for row in telemetry:
            obs, pred = row.get(observed_key), row.get(imputed_key)
            if obs is None or pred is None:
                residuals.append(None)
                continue
            try:
                residuals.append(float(obs) - float(pred))
            except (TypeError, ValueError):
                residuals.append(None)
        fig.add_trace(
            go.Scatter(
                x=stamps,
                y=residuals,
                mode="lines",
                name=name,
                line=dict(color=color, width=1.6),
                connectgaps=False,
            )
        )
    fig.add_hline(y=0, line_dash="dot", line_color=GRID, line_width=1)
    fig.update_layout(
        title=dict(text="Reconstruction residual (observed − predicted)", font=dict(size=13, color=TEXT), pad=dict(t=0, b=0)),
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        margin=dict(l=40, r=16, t=36, b=32),
        height=200,
        legend=dict(orientation="h", y=1.18, x=0, font=dict(size=11, color=MUTED)),
        font=dict(color=MUTED, size=11, family="IBM Plex Sans, system-ui, sans-serif"),
        xaxis=dict(gridcolor=GRID, zeroline=False, showline=False, color=MUTED),
        yaxis=dict(gridcolor=GRID, zeroline=True, showline=False, color=MUTED),
        hovermode="x unified",
    )
    span = _x_range(stamps, mark_at)
    if span is not None:
        fig.update_xaxes(range=span)
    if mark_at is not None:
        fig.add_vline(x=mark_at, line_dash="dot", line_color=MUTED, line_width=1)
    return fig


def telemetry_figures(telemetry: list[dict[str, Any]], mark_at: Any | None = None) -> list[go.Figure]:
    figures = [
        channel_figure(telemetry, observed, imputed, title, unit, mark_at=mark_at)
        for observed, imputed, title, unit in CHANNELS
    ]
    figures.append(residual_figure(telemetry, mark_at=mark_at))
    return figures


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
