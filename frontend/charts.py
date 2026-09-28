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

BAND_FILL = "rgba(217, 119, 6, 0.22)"


def _correction(
    observed: list[Any],
    imputed: list[float | None],
    lows: list[float | None],
) -> list[float | None]:
    """Trusted hours stay on the reading. A distrusted hour uses the prediction.

    One stored prediction is still a series: the dashed line follows the sensor
    and leaves it on the hour QC corrected.
    """
    if not any(value is not None for value in lows):
        return [None] * len(observed)
    series: list[float | None] = []
    for obs, imp, low in zip(observed, imputed, lows, strict=True):
        if low is not None:
            series.append(imp)
        elif isinstance(obs, (int, float)):
            series.append(float(obs))
        else:
            series.append(None)
    return series


def _hour_ribbon(
    stamps: list[Any],
    lows: list[float | None],
    highs: list[float | None],
) -> tuple[list[Any], list[float | None], list[float | None]]:
    """Each corrected hour is a filled span from the previous hour to this one."""
    xs: list[Any] = []
    lo: list[float | None] = []
    hi: list[float | None] = []
    for index, low in enumerate(lows):
        if low is None or highs[index] is None:
            continue
        start = stamps[index - 1] if index else stamps[index]
        xs.extend([start, stamps[index], None])
        lo.extend([low, low, None])
        hi.extend([highs[index], highs[index], None])
    return xs, lo, hi


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
    corrected = _correction(observed, imputed, lows)
    ribbon_x, ribbon_lo, ribbon_hi = _hour_ribbon(stamps, lows, highs)
    fig = go.Figure()
    if ribbon_x:
        fig.add_trace(
            go.Scatter(
                x=ribbon_x,
                y=ribbon_hi,
                mode="lines",
                name="Band high",
                line=dict(width=0),
                hoverinfo="skip",
                showlegend=False,
                connectgaps=False,
                legendrank=2,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=ribbon_x,
                y=ribbon_lo,
                mode="lines",
                name="90% band",
                line=dict(width=0),
                fill="tonexty",
                fillcolor=BAND_FILL,
                hoverinfo="skip",
                connectgaps=False,
                legendrank=2,
            )
        )
    fig.add_trace(
        go.Scatter(
            x=stamps,
            y=observed,
            mode="lines+markers",
            name="Observed",
            line=dict(color=OBSERVED, width=2.4),
            marker=dict(size=5, color=OBSERVED),
            connectgaps=False,
            legendrank=1,
        )
    )
    if any(value is not None for value in corrected):
        fig.add_trace(
            go.Scatter(
                x=stamps,
                y=corrected,
                mode="lines+markers",
                name="Predicted",
                line=dict(color=IMPUTED, width=2, dash="dash"),
                marker=dict(
                    size=[8 if low is not None else 0 for low in lows],
                    color=IMPUTED,
                    line=dict(color=CARD, width=1),
                ),
                connectgaps=False,
                legendrank=3,
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


def sparkline_figure(
    telemetry: list[dict[str, Any]],
    observed_key: str = "temp_observed",
    title: str = "Temperature so far",
) -> go.Figure:
    stamps = [row.get("timestamp") for row in telemetry]
    observed = [row.get(observed_key) for row in telemetry]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=stamps,
            y=observed,
            mode="lines+markers",
            name="Observed",
            line=dict(color=OBSERVED, width=2),
            marker=dict(size=6),
            connectgaps=False,
        )
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color=TEXT), pad=dict(t=0, b=0)),
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        margin=dict(l=36, r=12, t=28, b=24),
        height=140,
        showlegend=False,
        font=dict(color=MUTED, size=11, family="IBM Plex Sans, system-ui, sans-serif"),
        xaxis=dict(gridcolor=GRID, zeroline=False, showline=False, color=MUTED),
        yaxis=dict(gridcolor=GRID, zeroline=False, showline=False, color=MUTED),
        hovermode="x unified",
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


def timing_figure(timing: dict[str, Any] | None) -> go.Figure | None:
    """24 bars: how much each hour of the window carried the reconstruction error.

    Hours before `start_hour_in_window` stay slate; the attributed run is drawn in the
    overlay color so the eye lands on when the anomaly began.
    """
    body = (timing or {}).get("timing") if isinstance((timing or {}).get("timing"), dict) else None
    if not body:
        return None
    attr = body.get("hour_attr")
    if not isinstance(attr, (list, tuple)) or not attr:
        return None
    values: list[float] = []
    for value in attr:
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            values.append(0.0)
    n = len(values)
    start = body.get("start_hour_in_window")
    start_idx = int(start) if isinstance(start, (int, float)) else None
    labels = [f"−{n - 1 - i} h" if i < n - 1 else "this hour" for i in range(n)]
    colors = [
        IMPUTED if (start_idx is not None and i >= start_idx) else "#CBD5E1" for i in range(n)
    ]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker=dict(color=colors, line=dict(width=0)),
            hovertemplate="%{x}<br>share %{y:.1%}<extra></extra>",
        )
    )
    if start_idx is not None and 0 <= start_idx < n:
        fig.add_vline(
            x=start_idx - 0.5,
            line_dash="dot",
            line_color=MUTED,
            line_width=1,
            annotation_text="attribution starts",
            annotation_position="top left",
            annotation_font=dict(size=10, color=MUTED),
        )
    fig.update_layout(
        title=dict(text="When the error entered the window", font=dict(size=13, color=TEXT), pad=dict(t=0, b=0)),
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        margin=dict(l=40, r=16, t=36, b=32),
        height=200,
        showlegend=False,
        font=dict(color=MUTED, size=11, family="IBM Plex Sans, system-ui, sans-serif"),
        xaxis=dict(gridcolor=GRID, zeroline=False, showline=False, color=MUTED, tickangle=0, nticks=8),
        yaxis=dict(gridcolor=GRID, zeroline=False, showline=False, color=MUTED, tickformat=".0%"),
        bargap=0.25,
    )
    return fig


ALERT_KIND_COLOR = {
    "hardware": "#E11D48",
    "weather": "#D97706",
    "unknown": "#64748B",
}

ALERT_KIND_TEXT = {"hardware": "Hardware", "weather": "Weather", "unknown": "Unconfirmed"}


def alerts_timeline_figure(
    rows: list[dict[str, Any]],
    kind_of: Any,
) -> go.Figure | None:
    """Stacked bars per hour: how many hardware / weather / unconfirmed hours landed when."""
    if not rows:
        return None
    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        stamp = _as_dt(row.get("timestamp"))
        if stamp is None:
            continue
        key = stamp.strftime("%Y-%m-%dT%H:00Z")
        kind = kind_of(row)
        if kind not in ALERT_KIND_COLOR:
            kind = "unknown"
        buckets.setdefault(key, {"hardware": 0, "weather": 0, "unknown": 0})[kind] += 1
    if not buckets:
        return None
    keys = sorted(buckets)
    fig = go.Figure()
    for kind in ("hardware", "weather", "unknown"):
        ys = [buckets[k][kind] for k in keys]
        if not any(ys):
            continue
        fig.add_trace(
            go.Bar(
                x=keys,
                y=ys,
                name=ALERT_KIND_TEXT[kind],
                marker=dict(color=ALERT_KIND_COLOR[kind], line=dict(width=0)),
                hovertemplate="%{x}<br>" + ALERT_KIND_TEXT[kind] + " %{y}<extra></extra>",
            )
        )
    fig.update_layout(
        barmode="stack",
        title=dict(text="Exceptions per hour", font=dict(size=13, color=TEXT), pad=dict(t=0, b=0)),
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        margin=dict(l=40, r=16, t=36, b=32),
        height=190,
        legend=dict(orientation="h", y=1.22, x=0, font=dict(size=11, color=MUTED)),
        font=dict(color=MUTED, size=11, family="IBM Plex Sans, system-ui, sans-serif"),
        xaxis=dict(gridcolor=GRID, zeroline=False, showline=False, color=MUTED, type="category", nticks=10),
        yaxis=dict(gridcolor=GRID, zeroline=False, showline=False, color=MUTED, dtick=1),
        bargap=0.2,
    )
    return fig


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
