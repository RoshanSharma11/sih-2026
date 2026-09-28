"""Network page: 48 markers, KPI strip, dispatch board, India map."""

from __future__ import annotations

from typing import Any

import streamlit as st

from api import SkyGuardApiError, merge_station
from chrome import (
    DEMO_FOCUS,
    cached_buddy_map,
    focus_station,
    get_client,
    go_page,
    kpi_strip,
    offline_help,
    page_header,
    render_html,
    show_flash,
)
from map_view import india_map
from panels import (
    dispatch_lists,
    dispatch_panel_html,
    dispatch_row_html,
    map_head_html,
    network_intro_html,
)
from status import kpi_counts, short_name, status_label


def render_network() -> None:
    show_flash()
    page_header(
        "Network",
        "This hour across the live 48. Amber is weather. Rose is a sensor. Health is the 7-day index.",
        get_client().health(),
    )
    render_html(network_intro_html())
    network_live()


@st.fragment(run_every=1)
def network_live() -> None:
    client = get_client()
    health = client.health()
    if health is None:
        offline_help(f"API is not reachable at {client.base_url}. Start it with python scripts/run_api.py.")
        return

    try:
        stations = [merge_station(row) for row in client.stations()]
        graph = cached_buddy_map()
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return
    try:
        alerts = client.alerts(limit=80)
    except SkyGuardApiError:
        alerts = []

    kpi_strip(kpi_counts(stations))
    if not stations:
        st.info("Catalog is empty. Import the 48-station catalog and restart the API.")
        return

    _dispatch_board(stations, alerts)

    buddies = _view_buddies(DEMO_FOCUS, graph)
    focus, rest = _roster_groups(stations)
    selected = next((row for row in stations if row["station_id"] == st.session_state.get("station_id")), None)
    selected_name = short_name(selected["name"]) if selected else None

    map_col, rail_col = st.columns([2.2, 1], gap="large")
    with map_col:
        render_html(map_head_html(len(stations), selected_name))
        event = st.plotly_chart(
            india_map(
                stations,
                st.session_state.station_id,
                buddies=buddies,
                focus_ids=DEMO_FOCUS,
            ),
            theme=None,
            width="stretch",
            on_select="rerun",
            selection_mode="points",
            key="india_map",
            config={"scrollZoom": True, "displayModeBar": False, "doubleClick": "reset"},
        )
        st.caption("Camera starts on Mumbai and Safdarjung. Double-click the map to reset. Click a marker to open Station.")
    with rail_col:
        _station_roster("Mumbai + Safdarjung", focus)
        _station_roster("All other stations", rest)
    if _apply_map_selection(event):
        go_page("station")


def _dispatch_board(stations: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> None:
    lists = dispatch_lists(stations, alerts)
    with st.container(border=True):
        render_html(dispatch_panel_html(lists))
        _dispatch_group("Needs a technician", "page", lists.get("page") or [])
        _dispatch_group("Watch this hour", "watch", lists.get("watch") or [])


def _dispatch_group(title: str, rank: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    st.caption(f"{title} · {len(rows)}")
    render_html('<div class="sg-dispatch-list">' + "".join(dispatch_row_html(row) for row in rows) + "</div>")
    for start in range(0, len(rows), 4):
        chunk = rows[start : start + 4]
        cols = st.columns(len(chunk), gap="small")
        for col, row in zip(cols, chunk):
            with col:
                if st.button(
                    row["name"],
                    key=f"dispatch_{rank}_{row['station_id']}",
                    width="stretch",
                    help="Open this station. Pins the newest hardware hour when the feed has one.",
                ):
                    focus_station(row["station_id"], alert_id=row.get("alert_id"))
                    go_page("station")


def _roster_groups(stations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rank = {station_id: index for index, station_id in enumerate(DEMO_FOCUS)}
    focus = [row for row in stations if row["station_id"] in rank]
    focus.sort(key=lambda row: rank[row["station_id"]])
    rest = [row for row in stations if row["station_id"] not in rank]
    rest.sort(key=lambda row: row.get("name") or "")
    return focus, rest


def _station_roster(title: str, stations: list[dict[str, Any]]) -> None:
    if not stations:
        return
    st.caption(title)
    selected = st.session_state.get("station_id")
    for row in stations:
        sid = row["station_id"]
        name = short_name(row.get("name", sid))
        if st.button(
            name,
            key=f"roster_{sid}",
            width="stretch",
            type="primary" if sid == selected else "secondary",
            help=f"{sid} · {status_label(row)} · 7-day {row.get('health_score', '—')}",
        ):
            focus_station(sid)
            go_page("station")


def _view_buddies(view_ids: list[str], graph: dict[str, Any]) -> dict[str, list[str]]:
    raw = graph.get("buddies") if isinstance(graph, dict) else None
    if not isinstance(raw, dict):
        return {}
    allowed = set(view_ids)
    return {
        station_id: [buddy for buddy in neighbors if buddy in allowed]
        for station_id, neighbors in raw.items()
        if station_id in allowed
    }


def _apply_map_selection(event: Any) -> bool:
    selection = getattr(event, "selection", None)
    points = getattr(selection, "points", None) if selection is not None else None
    custom = None
    if points:
        point = points[0]
        custom = point.get("customdata") if isinstance(point, dict) else None
        if custom is None and not isinstance(point, dict):
            custom = getattr(point, "customdata", None)
        if isinstance(custom, (list, tuple)):
            custom = custom[0] if custom else None
    sid = str(custom) if custom else None
    if not st.session_state.get("_map_armed"):
        st.session_state._map_armed = True
        st.session_state._map_pick = sid
        return False
    if not sid or st.session_state.get("_map_pick") == sid:
        return False
    st.session_state._map_pick = sid
    focus_station(sid)
    return True
