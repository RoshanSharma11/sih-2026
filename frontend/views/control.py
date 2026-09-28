"""Control page: Mumbai replay plus a custom inject builder."""

from __future__ import annotations

from typing import Any

import streamlit as st

from api import SkyGuardApiError
from chrome import (
    SANTACRUZ,
    catalog_stations,
    fire_inject,
    fire_replay,
    fire_reset,
    focus_station,
    get_client,
    go_page,
    offline_help,
    page_header,
    show_flash,
    station_options,
)
from panels import (
    CHANNEL_CHOICES,
    CUSTOM_EVENTS,
    STORIES,
    build_inject_body,
    event_preview_html,
    event_spec,
    overlay_cards_html,
    poll_html,
    webhook_html,
    result_cards_html,
    section_html,
    split_lead_result,
    story_preview_html,
    story_spec,
)
from status import short_name


def render_control() -> None:
    show_flash()
    client = get_client()
    health = client.health()
    page_header(
        "Control",
        "Play a Mumbai story for an instant scored hour, or arm any event on the next live ingest.",
        health,
    )
    if health is None:
        offline_help(f"API is not reachable at {client.base_url}. Start it with python scripts/run_api.py.")
        return

    imd = health.get("imd") if isinstance(health.get("imd"), dict) else {}
    n_stations = health.get("n_stations") if isinstance(health.get("n_stations"), int) else 48
    st.markdown(poll_html(imd, n_stations), unsafe_allow_html=True)
    webhook = health.get("webhook") if isinstance(health.get("webhook"), dict) else {}
    st.markdown(webhook_html(webhook), unsafe_allow_html=True)

    try:
        catalog = catalog_stations()
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return
    names = {row["station_id"]: short_name(row.get("name", row["station_id"])) for row in catalog}
    by_id = {row["station_id"]: row for row in catalog}

    _replay_block(names)
    _custom_block(catalog, names, by_id)
    _armed_overlays(names)

    st.button("Reset overlays", width="stretch", on_click=fire_reset)


def _replay_block(names: dict[str, str]) -> None:
    st.markdown(
        section_html(
            "Mumbai stories",
            "Five scored fixtures. Play scores the hour in this card. Inspect opens Santa Cruz.",
        ),
        unsafe_allow_html=True,
    )
    _story_picker()
    spec = story_spec(st.session_state.control_story)
    last = st.session_state.get("replay_last")
    if _result_for(last, spec["id"]):
        _scored_story(names, spec, last)
        return
    st.markdown(story_preview_html(spec["id"]), unsafe_allow_html=True)
    st.button(
        f"Play · {spec['title']}",
        type="primary",
        width="stretch",
        key="replay_play",
        on_click=fire_replay,
        args=(spec["id"],),
    )


def _result_for(last: Any, story_id: str) -> bool:
    return isinstance(last, dict) and bool(last.get("results")) and last.get("story") == story_id


def _scored_story(names: dict[str, str], spec: dict[str, str], last: dict[str, Any]) -> None:
    lead, rest = split_lead_result(list(last.get("results") or []), SANTACRUZ)
    st.markdown(
        result_cards_html(lead, names, heading=f"Scored · {spec['title']}"),
        unsafe_allow_html=True,
    )
    inspect, again = st.columns([3, 2], gap="small")
    with inspect:
        if st.button(
            "Inspect Santa Cruz on Station",
            type="primary",
            width="stretch",
            key="inspect_replay",
        ):
            focus_station(SANTACRUZ)
            go_page("station")
    with again:
        st.button(
            "Play again",
            width="stretch",
            key="replay_again",
            on_click=fire_replay,
            args=(spec["id"],),
        )
    if rest:
        st.markdown(
            result_cards_html(rest, names, heading="Other stations this hour"),
            unsafe_allow_html=True,
        )


def _story_picker() -> None:
    columns = st.columns(len(STORIES), gap="small")
    for index, spec in enumerate(STORIES):
        selected = st.session_state.get("control_story") == spec["id"]
        with columns[index]:
            if st.button(
                spec["short"],
                key=f"pick_{spec['id']}",
                type="primary" if selected else "secondary",
                width="stretch",
                help=spec["claim"],
            ):
                st.session_state.control_story = spec["id"]
                st.rerun()


def _custom_block(
    catalog: list[dict[str, Any]],
    names: dict[str, str],
    by_id: dict[str, dict[str, Any]],
) -> None:
    st.markdown(
        section_html(
            "Custom event",
            "Pick a station, a fault, and how long it lasts. This arms POST /demo/inject for the next ingested hours.",
        ),
        unsafe_allow_html=True,
    )
    options = station_options(catalog)
    if not options:
        st.info("The catalog is empty.")
        return

    current = st.session_state.get("station_id")
    if current not in options:
        current = SANTACRUZ if SANTACRUZ in options else next(iter(options))

    kind_ids = [row["id"] for row in CUSTOM_EVENTS]
    if st.session_state.get("inject_kind") not in kind_ids:
        st.session_state.inject_kind = "SPIKE"

    station_col, kind_col = st.columns(2, gap="medium")
    with station_col:
        station_id = st.selectbox(
            "Station",
            options=list(options.keys()),
            index=list(options.keys()).index(current) if current in options else 0,
            format_func=lambda sid: options.get(sid, sid),
            key="inject_station",
        )
    with kind_col:
        kind = st.selectbox(
            "Event",
            options=kind_ids,
            format_func=lambda kid: event_spec(kid)["title"],
            key="inject_kind",
        )

    spec = event_spec(kind)
    if st.session_state.get("_inject_kind_seen") != kind:
        st.session_state.inject_hours = spec["default_hours"]
        st.session_state._inject_kind_seen = kind

    channel_col, hours_col = st.columns(2, gap="medium")
    with channel_col:
        if spec["needs_channel"]:
            channel = st.selectbox(
                "Channel",
                options=[key for key, _label in CHANNEL_CHOICES],
                format_func=lambda key: dict(CHANNEL_CHOICES)[key],
                key="inject_channel",
            )
        else:
            channel = None
            st.caption("Channel is ignored for this event.")
    with hours_col:
        hours = st.number_input(
            "Duration (hours)",
            min_value=1,
            max_value=168,
            step=1,
            key="inject_hours",
        )

    station = by_id.get(station_id)
    st.markdown(
        event_preview_html(spec, station, names, channel, int(hours)),
        unsafe_allow_html=True,
    )
    body = build_inject_body(
        kind=kind,
        station_id=station_id,
        channel=channel,
        duration_hours=int(hours),
    )
    arm, inspect = st.columns([2, 1], gap="medium")
    with arm:
        st.button(
            f"Arm · {spec['title']}",
            type="primary",
            width="stretch",
            on_click=fire_inject,
            args=(body,),
        )
    with inspect:
        if st.button("Open Station", width="stretch"):
            focus_station(station_id)
            go_page("station")


def _armed_overlays(names: dict[str, str]) -> None:
    try:
        status = get_client().demo_status()
    except SkyGuardApiError:
        return
    overlays = status.get("overlays") or []
    st.markdown(overlay_cards_html(overlays, names), unsafe_allow_html=True)
