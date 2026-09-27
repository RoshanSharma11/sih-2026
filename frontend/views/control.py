"""Control page: live poll status and Mumbai replay stories."""

from __future__ import annotations

import streamlit as st

from api import SkyGuardApiError
from chrome import (
    fire_replay,
    fire_reset,
    get_client,
    offline_help,
    page_header,
    show_flash,
)

STORIES = (
    ("clean", "Clean hour", "Five demo stations, no mutation."),
    ("hardware", "55 °C at Santa Cruz", "Santa Cruz only, at 55 °C / 95% / 980 hPa."),
    ("weather", "+8 °C across Mumbai", "Santa Cruz, Colaba, and Juhu. Alibag stays on the fixture hour."),
    ("freeze", "12-hour freeze", "Santa Cruz temperature held for 12 hours."),
    ("comms", "Missing temperature", "Santa Cruz temperature null."),
)


def render_control() -> None:
    show_flash()
    client = get_client()
    health = client.health()
    page_header(
        "Control",
        "Live poll status, and the Mumbai replay. The stories use the same ingest path.",
        health,
    )
    if health is None:
        offline_help(f"API is not reachable at {client.base_url}. Start it with python scripts/run_api.py.")
        return

    _poll(health)
    st.markdown("##### Replay")
    st.caption("Each story seeds 2024-12-31 and scores the last hour. Santa Cruz opens on Station.")
    columns = st.columns(3)
    for index, (story, label, help_text) in enumerate(STORIES):
        with columns[index % 3]:
            st.button(
                label,
                key=f"replay_{story}",
                type="primary" if story == "hardware" else "secondary",
                width="stretch",
                help=help_text,
                on_click=fire_replay,
                args=(story,),
            )
    st.button("Reset overlays", on_click=fire_reset)
    _replay_note()


def _poll(health: dict) -> None:
    imd = health.get("imd") if isinstance(health.get("imd"), dict) else {}
    matched = imd.get("matched")
    last_success = imd.get("last_success") or "—"
    last_error = imd.get("last_error")
    st.markdown("##### Live poll")
    c1, c2, c3 = st.columns(3)
    c1.metric("Matched", matched if isinstance(matched, int) else "—")
    c2.metric("Last success", "yes" if imd.get("last_success") else "—")
    c3.metric("Last error", "none" if not last_error else "see below")
    st.caption(f"Last success {last_success}. Matched is how many of the 48 had an IMD id on the last poll.")
    if last_error:
        st.warning(str(last_error))


def _replay_note() -> None:
    try:
        status = get_client().demo_status()
    except SkyGuardApiError:
        return
    overlays = status.get("overlays") or []
    if overlays:
        st.caption("An older overlay is still armed. Reset clears it. Replay stories do not leave one armed.")
