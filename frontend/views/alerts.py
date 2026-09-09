"""Alerts page: newest-first feed. Weather amber, hardware rose."""

from __future__ import annotations

from typing import Any

import streamlit as st

from api import SkyGuardApiError
from chrome import (
    catalog_stations,
    get_client,
    offline_help,
    page_header,
    show_flash,
)
from status import is_hardware, is_weather, pipeline_color, short_name
from theme import HARDWARE, SLATE, WEATHER


def render_alerts() -> None:
    show_flash()
    page_header(
        "Alerts",
        "Newest first. Genuine weather stays amber; hardware is rose.",
        get_client().health(),
    )
    st.checkbox("Selected station only", key="alerts_station_only")
    alerts_live()


@st.fragment(run_every=1)
def alerts_live() -> None:
    client = get_client()
    station_id = st.session_state.get("station_id")
    only = bool(st.session_state.get("alerts_station_only"))
    try:
        rows = client.alerts(station_id if only else None, limit=80)
        catalog = catalog_stations()
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return

    names = {row["station_id"]: short_name(row["name"]) for row in catalog}
    if not rows:
        st.caption("No alerts yet. Arm a fault on Control or wait for the streamer.")
        return

    for row in rows:
        _alert_row(row, names)


def _alert_row(row: dict[str, Any], names: dict[str, str]) -> None:
    sid = str(row.get("station_id", ""))
    name = names.get(sid, sid)
    label = row.get("label")
    fault = row.get("fault_type")
    if is_weather(label, fault):
        color = WEATHER
    elif is_hardware(label, fault):
        color = HARDWARE
    else:
        color = pipeline_color(label) if label else SLATE
    stamp = str(row.get("timestamp", "")).replace("T", " ").replace("Z", " UTC")
    text = row.get("explainability_text") or ""
    meta = f"{fault} · {name} · {sid} · {stamp}"
    left, right = st.columns([5.2, 1], gap="small")
    with left:
        st.markdown(
            f"<div class='sg-alert' style='border-left-color:{color}'>"
            f"<div class='sg-alert-meta'>{meta}</div>"
            f"<div class='sg-alert-text'>{text}</div></div>",
            unsafe_allow_html=True,
        )
    with right:
        if st.button("Open", key=f"alert_{row.get('alert_id')}_{sid}", width="stretch"):
            st.session_state.station_id = sid
            st.switch_page("station")
