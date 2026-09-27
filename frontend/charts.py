"""Observed vs imputed T/P/H. Raw series stay visible."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import plotly.graph_objects as go

from theme import CARD, GRID, IMPUTED, MUTED, OBSERVED, TEXT

CHANNELS = (
    ("temp_observed", "temp_imputed", "temp_c", "Temperature °C", "°C"),
    ("pres_observed", "pres_imputed", "pres_hpa", "Pressure hPa", "hPa"),
    ("rhum_observed", "rhum_imputed", "rhum_pct", "Humidity %", "%"),
)

CONTRIBUTION = (
    ("contribution_temp", "Temperature", "#0F766E"),
    ("contribution_pres", "Pressure", "#0369A1"),
    ("contribution_rhum", "Humidity", "#6D28D9"),
)


def _band(row: dict[str, Any], channel: str) -> tuple[float, float] | None:
    interval = row.get("imputed_interval")
    if not isinstance(interval, dict):
        return None
    pair = interval.get(channel)
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return None
    try:
        return float(pair[0]), float(pair[1])
    except (TypeError, ValueError):
        return None


def _as_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def cluster_around(
    telemetry: list[dict[str, Any]],
    timestamp: Any | None,
    gap: timedelta = timedelta(hours=6),
) -> list[dict[str, Any]]:
    """Hours that belong to the same continuous run as timestamp.

    A live hour a year after the replay must not draw a line across the gap.
    """
    rows = [row for row in telemetry if _as_dt(row.get("timestamp")) is not None]
    rows.sort(key=lambda row: _as_dt(row.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))
    if not rows:
        return []
    target = _as_dt(timestamp) or _as_dt(rows[-1].get("timestamp"))
    assert target is not None
    index = min(
        range(len(rows)),
        key=lambda i: abs((_as_dt(rows[i].get("timestamp")) - target).total_seconds()),
    )
    start = index
    while start > 0:
        left = _as_dt(rows[start - 1].get("timestamp"))
        right = _as_dt(rows[start].get("timestamp"))
        if left is None or right is None or right - left > gap:
            break
        start -= 1
    end = index
    while end + 1 < len(rows):
        left = _as_dt(rows[end].get("timestamp"))
        right = _as_dt(rows[end + 1].get("timestamp"))
        if left is None or right is None or right - left > gap:
            break
        end += 1
    return rows[start : end + 1]


def channel_figure(
    telemetry: list[dict[str, Any]],
    observed_key: str,
    imputed_key: str,
    interval_key: str,
    title: str,
    mark_at: Any | None = None,
    mark_label: str | None = None,
) -> go.Figure:
    stamps = [row.get("timestamp") for row in telemetry]
    observed = [row.get(observed_key) for row in telemetry]
    imputed: list[float | None] = []
    lows: list[float | None] = []
    highs: list[float | None] = []
    for row in telemetry:
        band = _band(row, interval_key)
        if band is None:
            imputed.append(None)
            lows.append(None)
            highs.append(None)
            continue
        lows.append(band[0])
        highs.append(band[1])
        value = row.get(imputed_key)
        imputed.append(float(value) if isinstance(value, (int, float)) else None)
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
    if any(value is not None for value in highs):
        fig.add_trace(
            go.Scatter(
                x=stamps,
                y=highs,
                mode="lines",
                name="Band high",
                line=dict(width=0),
                hoverinfo="skip",
                showlegend=False,
                connectgaps=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=stamps,
                y=lows,
                mode="lines",
                name="90% band",
                line=dict(width=0),
                fill="tonexty",
                fillcolor="rgba(217, 119, 6, 0.18)",
                hoverinfo="skip",
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
            annotation_text=mark_label or "Pinned hour",
            annotation_position="top",
            annotation_font=dict(size=10, color=MUTED),
        )
    return fig


def telemetry_figures(
    telemetry: list[dict[str, Any]],
    mark_at: Any | None = None,
    mark_label: str | None = None,
) -> list[go.Figure]:
    return [
        channel_figure(
            telemetry,
            observed,
            imputed,
            interval,
            title,
            mark_at=mark_at,
            mark_label=mark_label,
        )
        for observed, imputed, interval, title, _unit in CHANNELS
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
