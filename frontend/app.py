"""SkyGuard live demo console. Polls frozen REST; drives /demo/inject."""

from __future__ import annotations

from typing import Any

import streamlit as st

from api import SkyGuardApiError, SkyGuardClient, Snapshot
from charts import telemetry_figures
from map_view import india_map
from status import (
    is_hardware,
    is_weather,
    overlay_caption,
    pipeline_color,
    pipeline_label,
    selected_station,
    short_name,
)
from theme import CSS

PALAM = "42181"
HERO_STORM = {"target": "neighborhood", "station_id": PALAM, "kind": "GENUINE_WEATHER"}
HERO_SPIKE = {"target": "station", "station_id": PALAM, "kind": "SPIKE", "channel": "temp_c"}

st.set_page_config(page_title="SkyGuard AI", page_icon="◈", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

if "station_id" not in st.session_state:
    st.session_state.station_id = PALAM
if "flash" not in st.session_state:
    st.session_state.flash = None


@st.cache_resource
def get_client() -> SkyGuardClient:
    return SkyGuardClient()


def flash(message: str, kind: str = "ok") -> None:
    st.session_state.flash = {"message": message, "kind": kind}


def fire_inject(body: dict[str, Any]) -> None:
    try:
        get_client().inject(body)
        flash(f"Armed {body['kind']}. Watch the next streamed hour.")
    except SkyGuardApiError as exc:
        flash(str(exc), kind="bad")


def fire_reset() -> None:
    try:
        get_client().reset()
        flash("Overlays cleared.")
    except SkyGuardApiError as exc:
        flash(str(exc), kind="bad")


def apply_map_selection(event: Any) -> None:
    selection = getattr(event, "selection", None)
    points = getattr(selection, "points", None) if selection is not None else None
    if not points:
        return
    point = points[0]
    custom = point.get("customdata") if isinstance(point, dict) else None
    if custom is None and not isinstance(point, dict):
        custom = getattr(point, "customdata", None)
    if isinstance(custom, (list, tuple)):
        custom = custom[0] if custom else None
    if custom:
        st.session_state.station_id = str(custom)


def header(online: bool) -> None:
    left, right = st.columns([3, 1])
    with left:
        st.markdown('<div class="sg-kicker">SIH PS 26073</div>', unsafe_allow_html=True)
        st.title("SkyGuard AI")
        st.markdown(
            '<p class="sg-sub">Live QC for Indian AWS · T / P / H only · buddy-graph check separates a storm from a broken sensor.</p>',
            unsafe_allow_html=True,
        )
    with right:
        st.write("")
        if online:
            st.markdown('<span class="sg-chip sg-chip-ok">API live</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="sg-chip sg-chip-bad">API down</span>', unsafe_allow_html=True)


def hero() -> None:
    st.markdown("##### Judge controls")
    storm, spike, reset = st.columns([1.2, 1.3, 0.8])
    with storm:
        st.button(
            "Storm around Palam",
            type="primary",
            width="stretch",
            help="Arm GENUINE_WEATHER on Palam plus 1-hop buddies. Mumbai must stay clean.",
            on_click=fire_inject,
            args=(HERO_STORM,),
        )
    with spike:
        st.button(
            "Break Palam temperature",
            width="stretch",
            help="Arm a temp SPIKE on 42181 only. Safdarjung should stay clean.",
            on_click=fire_inject,
            args=(HERO_SPIKE,),
        )
    with reset:
        st.button("Reset overlays", width="stretch", on_click=fire_reset)


def show_flash() -> None:
    note = st.session_state.flash
    if not note:
        return
    if note["kind"] == "bad":
        st.error(note["message"])
    else:
        st.success(note["message"])
    st.session_state.flash = None


def legend() -> None:
    st.markdown(
        """<div class="sg-legend">
        <span><i class="sg-dot" style="background:#2dd4bf"></i> Clean</span>
        <span><i class="sg-dot" style="background:#f5b942"></i> Genuine weather</span>
        <span><i class="sg-dot" style="background:#f43f5e"></i> Hardware</span>
        <span><i class="sg-dot" style="background:#94a3b8"></i> Unknown</span>
        </div>""",
        unsafe_allow_html=True,
    )


def station_rail(stations: list[dict[str, Any]], selected_id: str) -> None:
    st.markdown("##### Stations")
    for row in stations:
        sid = row["station_id"]
        status = row.get("pipeline_status")
        color = pipeline_color(status)
        health = row.get("health_score")
        health_txt = f"{health:.0f}" if isinstance(health, (int, float)) else "—"
        if st.button(
            f"{short_name(row['name'])}  ·  {sid}",
            key=f"rail_{sid}",
            width="stretch",
            type="primary" if sid == selected_id else "secondary",
        ):
            st.session_state.station_id = sid
        st.caption(
            f"{row.get('cluster_id', '')} · {pipeline_label(status)} · health {health_txt} ({row.get('status', '—')})"
        )
        st.markdown(
            f'<div style="height:4px;border-radius:99px;background:{color};margin:-0.35rem 0 0.7rem 0"></div>',
            unsafe_allow_html=True,
        )


def verdict_banner(station: dict[str, Any] | None, alerts: list[dict[str, Any]]) -> None:
    if station is None:
        return
    status = station.get("pipeline_status")
    latest = station.get("latest") or {}
    name = short_name(station.get("name", station["station_id"]))
    alert = alerts[0] if alerts else None
    fault = None if alert is None else alert.get("fault_type")
    if is_weather(status, fault):
        kind = "weather"
    elif is_hardware(status, fault):
        kind = "hardware"
    elif status == "UNKNOWN":
        kind = "unknown"
    else:
        kind = "clean"

    if alert and alert.get("explainability_text"):
        text = alert["explainability_text"]
        meta = (
            f"{alert.get('fault_type', '')} · confidence {alert.get('confidence_score', 0):.2f}"
            f" · {alert.get('severity', '')}"
        )
        kicker = f"{pipeline_label(status)} · {name} · {station['station_id']}"
    elif status:
        text = {
            "CLEAN": f"{name} is tracking with its neighbors. No hardware alert this hour.",
            "UNKNOWN": (
                "Not enough same-hour neighbors yet. The first station in a storm hour "
                "stays UNKNOWN until its buddy arrives."
            ),
        }.get(status, f"{name} · {pipeline_label(status)}")
        meta = f"health {station.get('health_score', '—')} · {station.get('status', '')}"
        kicker = f"{pipeline_label(status)} · {name}"
    else:
        text = "Waiting for the clean streamer. Seed + hourly ingest will light this station."
        meta = "No telemetry yet"
        kicker = f"{name} · idle"

    if latest.get("observed") and status:
        obs = latest["observed"]
        meta += (
            f" · T { _fmt(obs.get('temp_c')) }°C"
            f" · P { _fmt(obs.get('pres_hpa')) } hPa"
            f" · H { _fmt(obs.get('rhum_pct')) }%"
        )

    st.markdown(
        f"""<div class="sg-verdict sg-verdict-{kind}">
        <div class="sg-verdict-kicker">{kicker}</div>
        <div class="sg-verdict-text">{text}</div>
        <div class="sg-verdict-meta">{meta}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value):.1f}"


def overlay_row(overlays: list[dict[str, Any]]) -> None:
    if not overlays:
        st.caption("No demo overlay armed. Streamer is sending clean hours.")
        return
    chips = " ".join(f'<span class="sg-overlay">{overlay_caption(item)}</span>' for item in overlays)
    st.markdown(chips, unsafe_allow_html=True)


def alert_feed(alerts: list[dict[str, Any]]) -> None:
    st.markdown("##### Alerts")
    if not alerts:
        st.caption("No alerts for this station yet.")
        return
    for row in alerts[:12]:
        fault = row.get("fault_type", "")
        weather = is_weather(None, fault)
        color = "#f5b942" if weather else "#f43f5e" if is_hardware(None, fault) else "#94a3b8"
        stamp = str(row.get("timestamp", "")).replace("T", " ").replace("Z", " UTC")
        st.markdown(
            f"<div style='border-left:3px solid {color};padding:0.35rem 0.7rem;margin-bottom:0.45rem;"
            f"background:#101827;border-radius:0 8px 8px 0'>"
            f"<div style='font-size:0.72rem;letter-spacing:0.08em;color:#8b9bb4;font-weight:700'>"
            f"{fault} · {stamp}</div>"
            f"<div style='color:#e8eef7;margin-top:0.15rem'>{row.get('explainability_text', '')}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


def advanced_panel(stations: list[dict[str, Any]]) -> None:
    with st.expander("Advanced inject"):
        kinds = ["SPIKE", "FREEZE", "DRIFT", "COMM_ERROR", "GENUINE_WEATHER"]
        kind = st.selectbox("Kind", kinds, index=0)
        if kind == "GENUINE_WEATHER":
            options = {f"{short_name(row['name'])} ({row['station_id']})": row["station_id"] for row in stations}
            picked = st.selectbox("Neighborhood of", list(options) or [PALAM])
            if st.button("Arm storm", key="adv_storm"):
                station_id = options.get(picked, PALAM)
                fire_inject({"target": "neighborhood", "station_id": station_id, "kind": "GENUINE_WEATHER"})
        else:
            options = {f"{short_name(row['name'])} ({row['station_id']})": row["station_id"] for row in stations}
            picked = st.selectbox("Station", list(options))
            channel = None
            if kind in {"SPIKE", "FREEZE", "DRIFT"}:
                channel = st.selectbox("Channel", ["temp_c", "pres_hpa", "rhum_pct"])
            if st.button("Arm hardware fault", key="adv_hw"):
                body: dict[str, Any] = {
                    "target": "station",
                    "station_id": options[picked],
                    "kind": kind,
                }
                if channel:
                    body["channel"] = channel
                fire_inject(body)
        st.caption("Storm must target a neighborhood. Hardware must target one station. Same rules as POST /demo/inject.")


def offline_help(error: str) -> None:
    st.error(error)
    st.code(
        "python scripts/run_api.py\n"
        "python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 --start 2024-07-01T00:00:00Z\n"
        "python scripts/run_dashboard.py",
        language="text",
    )


@st.fragment(run_every=1)
def live() -> None:
    snap: Snapshot = get_client().snapshot(st.session_state.station_id)
    if not snap.ok:
        offline_help(snap.error or "API error")
        return
    if snap.selected_id:
        st.session_state.station_id = snap.selected_id
    selected = selected_station(snap.stations, snap.selected_id)

    overlay_row(snap.overlays)
    map_col, rail_col = st.columns([1.55, 1], gap="large")
    with map_col:
        st.markdown("##### Network")
        legend()
        event = st.plotly_chart(
            india_map(snap.stations, snap.selected_id),
            theme=None,
            width="stretch",
            on_select="rerun",
            selection_mode="points",
            key="india_map",
        )
        apply_map_selection(event)
        selected = selected_station(snap.stations, st.session_state.station_id)
    with rail_col:
        station_rail(snap.stations, st.session_state.station_id)
        selected = selected_station(snap.stations, st.session_state.station_id)

    verdict_banner(selected, snap.alerts)

    if not snap.telemetry:
        st.info("No telemetry yet for this station. Start the clean streamer, then wait one poll.")
    else:
        st.markdown("##### Observed vs imputed")
        st.caption("Solid = raw (never overwritten). Dashed gold = reconstruction overlay.")
        for fig in telemetry_figures(snap.telemetry):
            st.plotly_chart(fig, theme=None, width="stretch")

    health = None if selected is None else selected.get("health_score")
    status = None if selected is None else selected.get("status")
    if selected is not None:
        m1, m2, m3 = st.columns(3)
        m1.metric("Health (7-day)", f"{health:.0f}" if isinstance(health, (int, float)) else "—")
        m2.metric("Station status", status or "—")
        m3.metric("Live hour", pipeline_label(selected.get("pipeline_status")))
        st.caption("Health is a 7-day maintenance score. Weather alerts do not lower it.")

    alert_feed(snap.alerts)
    advanced_panel(snap.stations)


header(get_client().healthz())
hero()
show_flash()
live()
