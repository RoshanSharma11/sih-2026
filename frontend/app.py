"""SkyGuard live ops console. Polls frozen REST; drives /demo/inject."""
# Navigation pages are registered below and used by go_page().

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="SkyGuard AI",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

from chrome import init_session, inject_theme, register_pages, render_sidebar
from views.alerts import render_alerts
from views.architecture import render_architecture
from views.control import render_control
from views.guide import render_guide
from views.network import render_network
from views.reliability import render_reliability
from views.station import render_station

inject_theme()
init_session()

network = st.Page(render_network, title="Network", icon=":material/map:", default=True, url_path="network")
station = st.Page(render_station, title="Station", icon=":material/thermostat:", url_path="station")
alerts = st.Page(render_alerts, title="Alerts", icon=":material/notifications:", url_path="alerts")
reliability = st.Page(
    render_reliability, title="Reliability", icon=":material/monitoring:", url_path="reliability"
)
control = st.Page(render_control, title="Control", icon=":material/tune:", url_path="control")
guide = st.Page(render_guide, title="How QC works", icon=":material/menu_book:", url_path="guide")
architecture = st.Page(
    render_architecture,
    title="Architecture",
    icon=":material/account_tree:",
    url_path="architecture",
)

register_pages(
    {
        "network": network,
        "station": station,
        "alerts": alerts,
        "reliability": reliability,
        "control": control,
        "guide": guide,
        "architecture": architecture,
    }
)
pg = st.navigation(
    {
        "Operations": [network, station, alerts, reliability],
        "Demo": [control],
        "Guide": [guide, architecture],
    },
    position="hidden",
)
render_sidebar(
    operations=[network, station, alerts, reliability],
    demo=[control],
    guide=[guide, architecture],
)
pg.run()
