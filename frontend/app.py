"""SkyGuard live ops console. Polls frozen REST; drives /demo/inject."""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="SkyGuard AI",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

from chrome import init_session, inject_theme
from views.alerts import render_alerts
from views.control import render_control
from views.guide import render_guide
from views.network import render_network
from views.station import render_station

inject_theme()
init_session()

pg = st.navigation(
    {
        "Operations": [
            st.Page(render_network, title="Network", icon=":material/map:", default=True, url_path="network"),
            st.Page(render_station, title="Station", icon=":material/thermostat:", url_path="station"),
            st.Page(render_alerts, title="Alerts", icon=":material/notifications:", url_path="alerts"),
        ],
        "Demo": [
            st.Page(render_control, title="Control", icon=":material/tune:", url_path="control"),
        ],
        "Guide": [
            st.Page(render_guide, title="How QC works", icon=":material/menu_book:", url_path="guide"),
        ],
    }
)
pg.run()
