"""Control page: neighborhood storm, Palam spike, reset, advanced inject."""

from __future__ import annotations

from typing import Any

import streamlit as st

from api import SkyGuardApiError
from chrome import (
    HERO_SPIKE,
    HERO_STORM,
    PALAM,
    catalog_stations,
    fire_inject,
    fire_reset,
    get_client,
    offline_help,
    overlay_banner,
    page_header,
    show_flash,
    station_options,
    view_picker,
)
from status import fault_label, pipeline_label


def render_control() -> None:
    show_flash()
    client = get_client()
    page_header(
        "Control",
        "Arm a neighborhood storm or a single-station fault. The streamer stays clean.",
        client.health(),
    )
    st.caption(
        "CLI `--stations` on the streamer overrides this view filter. "
        "If you started the streamer with `--stations 42181`, changing the picker here will not shrink ingest."
    )

    try:
        catalog = catalog_stations()
        filt = client.stream_filter()
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return

    _hero()
    control_live()
    ingest = filt.get("ingest") or []
    view = filt.get("view") or []
    st.caption(f"View {len(view) or '—'} · ingest {len(ingest) or '—'} (buddies included when the checkbox is on).")

    picker, advanced = st.columns([1.15, 1], gap="large")
    with picker:
        st.markdown("##### View set")
        view_picker(catalog)
    with advanced:
        _advanced(catalog)


def _hero() -> None:
    st.markdown("##### Judge controls")
    storm, spike, reset = st.columns([1.2, 1.3, 0.8])
    with storm:
        st.button(
            "Storm around Palam",
            type="primary",
            width="stretch",
            help="Arm GENUINE_WEATHER on Palam plus 1-hop buddies. Santacruz must stay clean.",
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


@st.fragment(run_every=1)
def control_live() -> None:
    try:
        status = get_client().demo_status()
        alerts = get_client().alerts(limit=8)
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return
    overlays = status.get("overlays") or []
    overlay_banner(overlays)
    if not overlays:
        st.caption("No demo overlay armed. Streamer is sending clean hours.")
    if alerts:
        latest = alerts[0]
        stamp = str(latest.get("timestamp", "")).replace("T", " ").replace("Z", " UTC")
        st.caption(
            f"Latest detection: {fault_label(latest.get('fault_type'))} · "
            f"{pipeline_label(latest.get('label'))} · {latest.get('station_id')} · {stamp}"
        )


def _advanced(catalog: list[dict[str, Any]]) -> None:
    st.markdown("##### Advanced inject")
    options = station_options(catalog)
    kinds = ["SPIKE", "FREEZE", "DRIFT", "COMM_ERROR", "GENUINE_WEATHER"]
    kind = st.selectbox("Kind", kinds, index=0)
    labels = list(options.keys())
    if not labels:
        st.caption("Catalog is empty.")
        return
    default = PALAM if PALAM in options else labels[0]
    picked = st.selectbox(
        "Neighborhood of" if kind == "GENUINE_WEATHER" else "Station",
        labels,
        format_func=lambda sid: options.get(sid, sid),
        index=labels.index(default) if default in labels else 0,
    )
    channel = None
    if kind in {"SPIKE", "FREEZE", "DRIFT"}:
        channel = st.selectbox("Channel", ["temp_c", "pres_hpa", "rhum_pct"])
    if kind == "GENUINE_WEATHER":
        if st.button("Arm storm", key="adv_storm", width="stretch"):
            fire_inject({"target": "neighborhood", "station_id": picked, "kind": "GENUINE_WEATHER"})
    elif st.button("Arm hardware fault", key="adv_hw", width="stretch"):
        body: dict[str, Any] = {"target": "station", "station_id": picked, "kind": kind}
        if channel:
            body["channel"] = channel
        fire_inject(body)
    st.caption("Storm must target a neighborhood. Hardware must target one station.")
