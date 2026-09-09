"""Network page: view-set picker, KPI strip, India map."""

from __future__ import annotations

from typing import Any

import streamlit as st

from api import SkyGuardApiError, merge_station
from chrome import (
    cached_buddy_map,
    catalog_stations,
    focus_station,
    fmt_value,
    get_client,
    go_page,
    kpi_strip,
    legend,
    offline_help,
    page_header,
    show_flash,
    sync_stream_filter,
    view_picker,
)
from map_view import india_map, offscreen_stations
from status import kpi_counts, marker_color, short_name, status_label


def render_network() -> None:
    show_flash()
    try:
        catalog = catalog_stations()
    except SkyGuardApiError as exc:
        page_header("Network", "Live view of the filtered AWS set.")
        offline_help(str(exc))
        return

    if not catalog:
        page_header("Network", "Live view of the filtered AWS set.")
        offline_help("Catalog is empty. Load stations.json and restart the API.")
        return

    if not st.session_state.get("filter_synced"):
        sync_stream_filter()
        st.session_state.filter_synced = True

    page_header(
        "Network",
        "Neighbors that agree stay amber. A sensor that disagrees goes rose.",
        get_client().health(),
    )

    picker, copy = st.columns([1.55, 1], gap="large")
    with picker:
        view_picker(catalog)
    with copy:
        st.markdown(
            """<div class="sg-card">
            <div class="sg-kicker">How to read this map</div>
            <p class="sg-caption" style="margin:0.4rem 0 0 0">
            Color is this hour’s QC label — not health. Teal lines are 1-hop buddies.
            Palam, Safdarjung, and Meerut sit together; Santacruz is Mumbai, so a Delhi
            storm must not paint it. Click a marker or a row to open Station.
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

    view_ids = list(st.session_state.get("view_ids") or [])
    try:
        stations = [merge_station(row) for row in client.stations(ids=view_ids)]
        filt = client.stream_filter()
        graph = cached_buddy_map()
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return

    kpi_strip(kpi_counts(stations))
    if not stations:
        st.info("Nothing in the view set. Pick Palam and a neighbor on the left — do not load all 151 onto the map.")
        return
    ingest = filt.get("ingest") or []
    st.caption(
        f"View {len(view_ids)} · ingest {len(ingest)} "
        f"(includes 1-hop buddies so QC can still run)."
    )
    legend()

    buddies = _view_buddies(view_ids, graph)
    far = offscreen_stations(stations, st.session_state.station_id)
    map_col, list_col = st.columns([2.35, 1], gap="large")
    with map_col:
        event = st.plotly_chart(
            india_map(stations, st.session_state.station_id, buddies=buddies),
            theme=None,
            width="stretch",
            on_select="rerun",
            selection_mode="points",
            key="india_map",
            config={"scrollZoom": True, "displayModeBar": False, "doubleClick": "reset"},
        )
        if far:
            names = ", ".join(short_name(row["name"]) for row in far)
            st.caption(f"Also in this view set, outside this zoom: {names}. Open from the list, or zoom out.")
        else:
            st.caption("Scroll-zoom to separate nearby NCR sites. Double-click the map to reset.")
    with list_col:
        _station_roster(stations)
    if _apply_map_selection(event):
        go_page("station")


def _station_roster(stations: list[dict[str, Any]]) -> None:
    st.markdown("##### Stations in view")
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
