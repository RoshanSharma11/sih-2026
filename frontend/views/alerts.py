"""Alerts page: QC inbox. Weather amber, hardware rose, unconfirmed slate."""

from __future__ import annotations

from typing import Any

import streamlit as st

from api import SkyGuardApiError
from charts import alerts_timeline_figure
from chrome import (
    catalog_stations,
    focus_station,
    get_client,
    go_page,
    offline_help,
    page_header,
    show_flash,
)
from panels import (
    ACK_FILTERS,
    ALERT_FILTERS,
    ack_actions,
    alert_card_html,
    alert_counts,
    alerts_empty_html,
    alerts_intro_html,
    alert_kpis_html,
    filter_alerts,
    section_html,
)
from status import alert_kind, short_name


def render_alerts() -> None:
    show_flash()
    page_header(
        "Alerts",
        "Hours QC did not trust. Weather stays amber. Hardware is rose. Inspect opens that hour.",
        get_client().health(),
    )
    st.markdown(alerts_intro_html(), unsafe_allow_html=True)
    _filters()
    alerts_live()


def _filters() -> None:
    try:
        catalog = catalog_stations()
    except SkyGuardApiError:
        catalog = []
    names = {row["station_id"]: short_name(row.get("name", row["station_id"])) for row in catalog}
    current = st.session_state.get("station_id")
    station_name = names.get(str(current), current or "this station")

    kind_cols = st.columns(len(ALERT_FILTERS), gap="small")
    for index, (kind, label) in enumerate(ALERT_FILTERS):
        selected = st.session_state.get("alerts_kind") == kind
        with kind_cols[index]:
            if st.button(
                label,
                key=f"alerts_kind_{kind}",
                type="primary" if selected else "secondary",
                width="stretch",
            ):
                st.session_state.alerts_kind = kind
                st.rerun()
    state_col, who_col, only_col = st.columns([2.4, 1.2, 1.2], gap="small")
    with state_col:
        labels = [label for _key, label in ACK_FILTERS]
        keys = [key for key, _label in ACK_FILTERS]
        current_state = st.session_state.get("alerts_ack") or "open"
        picked = st.radio(
            "Operator state",
            labels,
            index=keys.index(current_state) if current_state in keys else 0,
            horizontal=True,
            key="alerts_ack_radio",
            help="Open is the inbox. Acknowledged means someone owns it. Resolved is closed; the QC hour is unchanged.",
        )
        st.session_state.alerts_ack = keys[labels.index(picked)]
    with who_col:
        st.text_input(
            "Your name for the log",
            key="operator_name",
            placeholder="ops-1",
            help="Stored as ack_by on the alert.",
        )
    with only_col:
        st.checkbox(
            f"Only {station_name}",
            key="alerts_station_only",
            help="Limit the inbox to the station selected on Network or Station.",
        )


@st.fragment(run_every=1)
def alerts_live() -> None:
    client = get_client()
    station_id = st.session_state.get("station_id")
    only = bool(st.session_state.get("alerts_station_only"))
    kind = st.session_state.get("alerts_kind") or "all"
    ack = st.session_state.get("alerts_ack") or "open"
    try:
        rows = client.alerts(station_id if only else None, limit=80, state=None if ack == "all" else ack)
        catalog = catalog_stations()
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return

    names = {row["station_id"]: short_name(row.get("name", row["station_id"])) for row in catalog}
    counts = alert_counts(rows)
    visible = filter_alerts(rows, kind)
    st.markdown(alert_kpis_html(counts, len(rows)), unsafe_allow_html=True)
    timeline = alerts_timeline_figure(rows, alert_kind)
    if timeline is not None:
        st.plotly_chart(timeline, theme=None, width="stretch")
        st.caption(
            "One bar per hour in this feed. A wide amber bar is a shared weather hour; a lone rose bar is one sensor."
        )
    st.markdown(
        section_html(
            "Newest first",
            "Inspect pins this hour on Station. Acknowledge takes ownership; Resolve closes it. QC data never changes.",
        ),
        unsafe_allow_html=True,
    )
    if not visible:
        st.markdown(alerts_empty_html(filtered=bool(rows) or ack != "all"), unsafe_allow_html=True)
        return
    for row in visible:
        _alert_row(row, names)


def _ack(alert_id: Any, state: str) -> None:
    try:
        get_client().ack_alert(alert_id, state, by=(st.session_state.get("operator_name") or "").strip() or None)
    except SkyGuardApiError as exc:
        st.toast(str(exc), icon="⚠️")
        return
    st.toast(f"Alert {alert_id} → {state}")


def _alert_row(row: dict[str, Any], names: dict[str, str]) -> None:
    sid = str(row.get("station_id", ""))
    left, right = st.columns([5.2, 1.15], gap="small")
    with left:
        st.markdown(alert_card_html(row, names), unsafe_allow_html=True)
    with right:
        if st.button(
            "Inspect this hour",
            key=f"alert_{row.get('alert_id')}_{sid}",
            width="stretch",
            help="Show this hour on Station, even if the live hour is already clean.",
        ):
            focus_station(sid, alert_id=row.get("alert_id"))
            go_page("station")
        for label, next_state in ack_actions(row):
            if st.button(
                label,
                key=f"ack_{row.get('alert_id')}_{next_state}",
                width="stretch",
                type="primary" if next_state == "acknowledged" else "secondary",
            ):
                _ack(row.get("alert_id"), next_state)
                st.rerun()
