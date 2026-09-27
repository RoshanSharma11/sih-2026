"""Network page: 48 markers, KPI strip, India map."""

from __future__ import annotations

from typing import Any

import streamlit as st

from api import SkyGuardApiError, merge_station
from chrome import (
    DEMO_FOCUS,
    cached_buddy_map,
    focus_station,
    fmt_value,
    get_client,
    go_page,
    kpi_strip,
    legend,
    offline_help,
    page_header,
    show_flash,
)
from map_view import india_map
from status import kpi_counts, marker_color, short_name, status_label


def render_network() -> None:
    show_flash()
    page_header(
        "Network",
        "48 live stations. Neighbors that agree stay amber. A sensor that disagrees goes rose.",
        get_client().health(),
    )
    st.markdown(
        """<div class="sg-card">
        <div class="sg-kicker">How to read this map</div>
        <p class="sg-caption" style="margin:0.4rem 0 0 0">
        The camera starts on Mumbai and Safdarjung. Color is this hour’s label.
        Warming up means fewer than 24 hours — not a fault. Safdarjung has no buddies
        in this set, so weather versus hardware cannot be called there.
        Click a marker or a row to open Station.
        </p>
        </div>""",
        unsafe_allow_html=True,
    )
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

    kpi_strip(kpi_counts(stations))
    if not stations:
        st.info("Catalog is empty. Import the 48-station catalog and restart the API.")
        return
    st.caption(f"{len(stations)} live stations. Scroll the map for sites outside Mumbai and Delhi.")
    legend()

    buddies = _view_buddies(DEMO_FOCUS, graph)
    roster = _roster_order(stations)
    map_col, list_col = st.columns([2.35, 1], gap="large")
    with map_col:
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
        st.caption("Camera starts on Mumbai and Safdarjung. Double-click the map to reset.")
    with list_col:
        _station_roster(roster)
    if _apply_map_selection(event):
        go_page("station")


def _roster_order(stations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rank = {station_id: index for index, station_id in enumerate(DEMO_FOCUS)}
    return sorted(stations, key=lambda row: (rank.get(row["station_id"], 99), row.get("name") or ""))


def _station_roster(stations: list[dict[str, Any]]) -> None:
    st.markdown("##### Stations")
    st.caption("Names live here so nearby markers do not stack.")
    selected = st.session_state.get("station_id")
    for row in stations:
        sid = row["station_id"]
        name = short_name(row["name"])
        color = marker_color(row)
        health = fmt_value(row.get("health_score"), 0)
        label = status_label(row)
        cols = st.columns([0.18, 1], gap="small")
        with cols[0]:
            st.markdown(
                f'<div class="sg-dot" style="width:0.85rem;height:0.85rem;margin-top:0.7rem;background:{color}"></div>',
                unsafe_allow_html=True,
            )
        with cols[1]:
            clicked = st.button(
                f"{name} · {label}",
                key=f"roster_{sid}",
                width="stretch",
                type="primary" if sid == selected else "secondary",
                help=f"{sid} · health {health}",
            )
            st.caption(f"{sid} · health {health}")
        if clicked:
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
