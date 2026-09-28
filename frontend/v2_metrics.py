"""Charts for the architecture page, read from v2/artifacts only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import plotly.graph_objects as go

from theme import ACCENT, CARD, CLEAN, GRID, MUTED, OBSERVED, TEXT

_SLATE = "#64748B"
_CHANNELS = (
    ("temp", "Temperature", "#0F766E"),
    ("rhum", "Humidity", "#6D28D9"),
    ("pres", "Pressure", "#0369A1"),
)


def artifacts_dir(root: Path | None = None) -> Path:
    base = root if root is not None else Path(__file__).resolve().parents[1]
    return base / "v2-deliverable" / "v2" / "artifacts"


def load_v2_metrics(root: Path | None = None) -> dict[str, Any] | None:
    """Return artifact JSON when both chart sources exist. Otherwise None."""
    folder = artifacts_dir(root)
    percentiles_path = folder / "val_error_percentiles.json"
    overlay_path = folder / "overlay_metadata.json"
    if not percentiles_path.is_file() or not overlay_path.is_file():
        return None
    percentiles = json.loads(percentiles_path.read_text())
    overlay = json.loads(overlay_path.read_text())
    if "window_mse" not in percentiles or "val_mae_scaled" not in overlay:
        return None
    model_path = folder / "model_metadata.json"
    model = json.loads(model_path.read_text()) if model_path.is_file() else None
    return {"percentiles": percentiles, "overlay": overlay, "model": model}


def _pairs(block: dict[str, Any]) -> tuple[list[float], list[float]]:
    keys = sorted((key for key in block if _is_number(block[key])), key=float)
    return [float(key) for key in keys], [float(block[key]) for key in keys]


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _layout(fig: go.Figure, title: str, *, height: int = 320) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color=TEXT), x=0, xanchor="left"),
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        margin=dict(l=52, r=20, t=64, b=56),
        height=height,
        legend=dict(orientation="h", y=1.14, x=0, font=dict(size=11, color=MUTED)),
        font=dict(color=MUTED, size=12, family="IBM Plex Sans, system-ui, sans-serif"),
        xaxis=dict(gridcolor=GRID, zeroline=False, showline=False, color=MUTED),
        yaxis=dict(gridcolor=GRID, zeroline=False, showline=False, color=MUTED),
        hovermode="x unified",
    )
    return fig


def reconstruction_figure(metrics: dict[str, Any]) -> go.Figure | None:
    percentiles = metrics["percentiles"]
    window = percentiles.get("window_mse")
    if not isinstance(window, dict):
        return None
    x, y = _pairs(window)
    if not x:
        return None
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="lines+markers",
            name="Window MSE",
            line=dict(color=OBSERVED, width=2.4),
            marker=dict(size=7, color=OBSERVED),
        )
    )
    last = percentiles.get("last_step_mse")
    if isinstance(last, dict):
        lx, ly = _pairs(last)
        fig.add_trace(
            go.Scatter(
                x=lx,
                y=ly,
                mode="lines+markers",
                name="Last-step MSE",
                line=dict(color="#0369A1", width=2.4),
                marker=dict(size=7, color="#0369A1"),
            )
        )
    frozen = percentiles.get("operating_threshold")
    if _is_number(frozen):
        fig.add_hline(
            y=float(frozen),
            line_dash="dot",
            line_color=ACCENT,
            annotation_text="Frozen window p99",
            annotation_position="top left",
            annotation_font=dict(size=11, color=OBSERVED),
        )
    year = percentiles.get("operating_score_year")
    title = "Reconstruction error on 2023 validation"
    if year:
        title = f"Reconstruction error, {year} validation"
    fig.update_xaxes(
        title_text="Percentile",
        tickmode="array",
        tickvals=x,
        ticktext=[f"{value:g}" for value in x],
        tickangle=-35,
    )
    fig.update_yaxes(title_text="MSE")
    return _layout(fig, title)


def overlay_figure(metrics: dict[str, Any]) -> go.Figure | None:
    overlay = metrics["overlay"]
    mae = overlay.get("val_mae_scaled")
    gates = overlay.get("gates")
    if not isinstance(mae, dict) or not isinstance(gates, dict):
        return None
    labels: list[str] = []
    values: list[float] = []
    limits: list[float] = []
    colors: list[str] = []
    for key, label, color in _CHANNELS:
        if key not in mae or key not in gates:
            continue
        if not _is_number(mae[key]) or not _is_number(gates[key]):
            continue
        labels.append(label)
        values.append(float(mae[key]))
        limits.append(float(gates[key]))
        colors.append(color)
    if not labels:
        return None
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=values, name="Scaled MAE", marker_color=colors))
    fig.add_trace(
        go.Scatter(
            x=labels,
            y=limits,
            mode="markers",
            name="Gate",
            marker=dict(symbol="diamond", size=14, color=MUTED, line=dict(width=0)),
        )
    )
    passed = overlay.get("gates_passed")
    title = "Overlay error against the validation gates"
    if passed is True:
        title = "Overlay error inside the validation gates"
    fig.update_yaxes(title_text="Scaled MAE")
    return _layout(fig, title)


def metrics_html(metrics: dict[str, Any]) -> str:
    percentiles = metrics["percentiles"]
    overlay = metrics["overlay"]
    model = metrics.get("model") or {}
    tiles: list[tuple[str, str, str]] = []
    score = percentiles.get("operating_score")
    if _is_number(score):
        tiles.append(("Ingest score", f"{float(score):.6f}", CLEAN))
    window_p99 = percentiles.get("operating_threshold")
    if _is_number(window_p99):
        tiles.append(("Window p99", f"{float(window_p99):.6f}", OBSERVED))
    windows = percentiles.get("n_val_windows")
    if isinstance(windows, int):
        tiles.append(("Val windows", f"{windows:,}", _SLATE))
    if overlay.get("gates_passed") is True:
        tiles.append(("Overlay gates", "Passed", CLEAN))
    elif overlay.get("gates_passed") is False:
        tiles.append(("Overlay gates", "Outside", "#E11D48"))
    cells = "".join(
        f'<div class="sg-kpi" style="border-top-color:{color}">'
        f'<div class="sg-kpi-label">{label}</div>'
        f'<div class="sg-kpi-value" style="color:{color}">{value}</div></div>'
        for label, value, color in tiles
    )
    grid = "sg-kpis sg-kpis-4" if len(tiles) == 4 else "sg-kpis"
    year = percentiles.get("operating_score_year") or "2023"
    stride = percentiles.get("operating_score_stride")
    counted = percentiles.get("operating_score_n_windows")
    detail = f"Ingest score is the {year} last-hour-weighted p99"
    if isinstance(counted, int):
        detail += f" on {counted:,} windows"
    if stride is not None:
        detail += f", stride {stride}"
    detail += ". Window p99 is the plain 24-hour MSE."
    train = ""
    if isinstance(model.get("n_train_stations"), int) and isinstance(model.get("n_train_windows"), int):
        train = (
            f" The LSTM trained on {model['n_train_stations']} stations"
            f" and {model['n_train_windows']:,} windows."
        )
    coverage = overlay.get("val_coverage_90")
    cover = ""
    if isinstance(coverage, dict):
        bits = []
        for key, label, _color in _CHANNELS:
            if _is_number(coverage.get(key)):
                bits.append(f"{label} {float(coverage[key]) * 100:.1f}%")
        if bits:
            cover = " 90% band coverage: " + ", ".join(bits) + "."
    return (
        '<div class="sg-arch">'
        '<p class="sg-arch-band">Frozen v2 numbers</p>'
        f'<div class="{grid}">{cells}</div>'
        f'<p class="sg-caption">{detail}{train}{cover} Read from v2/artifacts.</p>'
        "</div>"
    )
