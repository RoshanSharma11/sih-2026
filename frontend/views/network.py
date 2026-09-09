"""Network page: view-set picker, KPI strip, India map."""

from __future__ import annotations

from typing import Any

import streamlit as st

from api import SkyGuardApiError, merge_station
from chrome import (
    cached_buddy_map,
    catalog_stations,
    get_client,
    kpi_strip,
    legend,
    offline_help,
    page_header,
    show_flash,
    sync_stream_filter,
    view_picker,
)
from map_view import india_map
from status import kpi_counts


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
        "Neighborhood weather stays amber. A lone broken sensor goes rose.",
        get_client().health(),
    )

    picker, copy = st.columns([1.4, 1], gap="large")
    with picker:
        view_picker(catalog)
    with copy:
        st.markdown(
            """<div class="sg-card">
            <div class="sg-kicker">151 trained stations</div>
            <p class="sg-caption" style="margin:0.4rem 0 0 0">
            The live map shows a handful of stations so a judge can read markers.
            Ingest still POSTs each selected station plus its 1-hop buddies, so a Palam-only
            view does not starve Tier 3.
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
    event = st.plotly_chart(
        india_map(stations, st.session_state.station_id, buddies=buddies),
        theme=None,
        width="stretch",
        on_select="rerun",
        selection_mode="points",
        key="india_map",
    )
    if _apply_map_selection(event):
        st.switch_page("station")


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
    if not points:
        return False
    point = points[0]
    custom = point.get("customdata") if isinstance(point, dict) else None
    if custom is None and not isinstance(point, dict):
        custom = getattr(point, "customdata", None)
    if isinstance(custom, (list, tuple)):
        custom = custom[0] if custom else None
    if not custom:
        return False
    st.session_state.station_id = str(custom)
    return True
