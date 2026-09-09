"""Station page — filled in F9."""

from __future__ import annotations

import streamlit as st

from chrome import get_client, page_header, show_flash
from status import short_name


def render_station() -> None:
    show_flash()
    health = get_client().health()
    page_header(
        "Station",
        "Observed T / P / H stay on the chart. Predicted values are a dashed overlay.",
        health,
    )
    sid = st.session_state.get("station_id", "42181")
    st.caption(f"Selected {sid}. Stream + prediction overlay lands next.")
    st.info(f"Waiting for the station view. Focus is {short_name(sid) if False else sid}.")
