"""Reliability page: per-station completeness and flag history from GET /reliability."""

from __future__ import annotations

import streamlit as st

from api import SkyGuardApiError
from charts import reliability_figure
from chrome import (
    focus_station,
    get_client,
    go_page,
    offline_help,
    page_header,
    render_html,
    show_flash,
)
from panels import (
    reliability_intro_html,
    reliability_kpis_html,
    reliability_table,
    section_html,
)

WINDOWS = ((24, "24 hours"), (72, "3 days"), (168, "7 days"), (720, "30 days"))


def render_reliability() -> None:
    show_flash()
    client = get_client()
    page_header(
        "Reliability",
        "Which stations report, how often QC had to step in, and where the feed itself went quiet.",
        client.health(),
    )
    render_html(reliability_intro_html())
    labels = [label for _hours, label in WINDOWS]
    hours_by_label = {label: hours for hours, label in WINDOWS}
    picked = st.radio("Window", labels, index=2, horizontal=True, key="reliability_window")
    hours = hours_by_label[picked]

    try:
        report = client.reliability(hours=hours)
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return
    if not report:
        offline_help(f"API is not reachable at {client.base_url}. Start it with python scripts/run_api.py.")
        return

    render_html(reliability_kpis_html(report.get("network") or {}))
    rows = report.get("stations") or []
    if not rows:
        st.info("Catalog is empty. Import the 48-station catalog and restart the API.")
        return

    render_html(
        section_html(
            "Hours by outcome",
            f"Each bar is one station over the last {picked}. The dotted line is the full window. "
            "Worst completeness at the top.",
        )
    )
    figure = reliability_figure(rows)
    if figure is not None:
        st.plotly_chart(figure, theme=None, width="stretch")

    render_html(section_html("Every station", "Click a column header to sort. Open a station from the picker below."))
    st.dataframe(
        reliability_table(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Completeness": st.column_config.ProgressColumn(
                "Completeness", min_value=0.0, max_value=1.0, format="percent"
            ),
            "Flag rate": st.column_config.ProgressColumn(
                "Flag rate", min_value=0.0, max_value=1.0, format="percent"
            ),
            "7-day health": st.column_config.NumberColumn("7-day health", format="%.0f"),
        },
    )

    names = {str(row["station_id"]): f"{row.get('name') or row['station_id']} · {row['station_id']}" for row in rows}
    pick_col, open_col = st.columns([3, 1], gap="small")
    with pick_col:
        chosen = st.selectbox(
            "Open a station",
            list(names),
            format_func=lambda sid: names[sid],
            key="reliability_pick",
            label_visibility="collapsed",
        )
    with open_col:
        if st.button("Open on Station", key="reliability_open", width="stretch"):
            focus_station(chosen)
            go_page("station")
