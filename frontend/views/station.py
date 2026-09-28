"""Station page: identity, readings, warmup progress, overlay charts, root cause."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from api import SkyGuardApiError, merge_station
from charts import adjacent_hour, cluster_around, contribution_html, ordered_hours, run_index, split_runs, telemetry_figures, timing_figure
from evidence import (
    decision_trace_html,
    neighbor_table_html,
    run_csv,
    technician_note,
    timing_channels_line,
    verdict_ribbon_html,
)
from chrome import (
    catalog_stations,
    fmt_value,
    get_client,
    offline_help,
    page_header,
    show_flash,
    station_options,
)
from panels import (
    WINDOW_HOURS,
    buddy_html,
    collected_hours,
    fmt_stamp,
    health_html,
    hour_caption,
    hour_kind,
    identity_html,
    readings_html,
    section_html,
    warmup_html,
)
from status import (
    alert_kind,
    alert_status_label,
    feed_gap,
    feed_gap_words,
    hour_alert,
    hour_telemetry,
    is_weather,
    latest_payload,
    pick_alert,
    short_name,
    stamp_key,
    status_label,
)


def render_station() -> None:
    show_flash()
    client = get_client()
    health = client.health()
    page_header(
        "Station",
        "Step through stored hours. The chart is that continuous run. A dashed prediction appears on any hour QC distrusted.",
        health,
    )
    try:
        view_rows = catalog_stations()
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return

    options = station_options(view_rows)
    current = st.session_state.get("station_id")
    if current and current not in options:
        options = _add_station_option(client, options, current)
    if not options:
        st.info("The catalog is empty. Import the 48 stations and restart the API.")
        return

    if current not in options:
        current = next(iter(options))
        st.session_state.station_id = current

    _sync_alert_pin(current)
    st.selectbox(
        "Station",
        options=list(options.keys()),
        format_func=lambda sid: options.get(sid, sid),
        key="station_id",
    )
    station_live()


@st.fragment(run_every=1)
def station_live() -> None:
    client = get_client()
    station_id = st.session_state.get("station_id")
    if not station_id:
        st.info("Pick a station on Network or from the selector.")
        return
    try:
        detail = client.station(station_id)
        station = merge_station(detail)
        telemetry = client.telemetry(station_id, limit=2000)
        alerts = client.alerts(station_id, limit=1000)
        catalog = catalog_stations()
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return
    health = client.health() or {}
    threshold = health.get("threshold") if isinstance(health.get("threshold"), (int, float)) else None

    names = {row["station_id"]: short_name(row.get("name", row["station_id"])) for row in catalog}
    pinned = pick_alert(alerts, st.session_state.get("alert_id"))
    if st.session_state.get("alert_id") and pinned is None:
        st.caption("That alert is no longer in the recent feed. Showing this hour instead.")
        st.session_state.alert_id = None

    ordered = ordered_hours(telemetry)
    runs = split_runs(ordered)
    latest = latest_payload(station)
    _adopt_external_pin(pinned, st.session_state.get("replay_ts"))
    hour = _shown_hour(ordered, pinned, latest)
    pinned_here = pinned is not None and hour is not None and stamp_key(pinned.get("timestamp")) == stamp_key(hour.get("timestamp"))
    alert = pinned if pinned_here else hour_alert(alerts, (hour or latest).get("timestamp"))
    on_live = hour is not None and stamp_key(hour.get("timestamp")) == stamp_key(latest.get("timestamp"))
    warming = bool(hour and hour.get("warming_up"))
    _time_bar(ordered, runs, hour, latest)

    _identity(station, names, hour, on_live=on_live, pinned_here=pinned_here, pinned=pinned)
    if warming and hour is not None:
        window = cluster_around(ordered, hour.get("timestamp"))
        st.markdown(
            warmup_html(collected_hours(window), fmt_stamp(hour.get("timestamp"))),
            unsafe_allow_html=True,
        )
    else:
        _verdict(station, alerts, hour, latest, pinned if pinned_here else None, on_live=on_live)
    st.markdown(readings_html(hour or latest, warming=warming), unsafe_allow_html=True)

    health_col, buddy_col = st.columns(2, gap="medium")
    with health_col:
        st.markdown(health_html(station), unsafe_allow_html=True)
    with buddy_col:
        st.markdown(buddy_html(station, names, hour), unsafe_allow_html=True)

    mark_at = (hour or latest).get("timestamp")
    window = _charts(ordered, mark_at, "This hour" if mark_at else None, warming=warming)
    gap = feed_gap(hour or latest)
    if gap and alert is None and not warming:
        st.markdown(
            section_html(
                "Why this hour",
                f"IMD did not send {feed_gap_words(gap)} for most stations this hour. "
                "The three tiers need the full hour, so v2 was not called. The raw hour is stored, "
                "no alert is opened and 7-day sensor health is not charged. "
                "This is a feed problem, not a sensor problem.",
            ),
            unsafe_allow_html=True,
        )
        _exports(station, window, hour, alert, names)
    elif not warming:
        timing = _timing_for(client, station_id, hour or latest)
        _root_cause(hour, alert, timing, threshold=threshold, names=names)
        _exports(station, window, hour, alert, names)
    else:
        st.markdown(
            section_html(
                "Why this hour",
                "No verdict yet. The 24th hourly value is the first v2 label.",
            ),
            unsafe_allow_html=True,
        )


def _add_station_option(
    client: Any, options: dict[str, str], station_id: str
) -> dict[str, str]:
    try:
        row = client.station(station_id)
    except SkyGuardApiError:
        return options
    name = short_name(row.get("name", station_id))
    return {station_id: f"{name}  ·  {station_id}", **options}


def _sync_alert_pin(current: str) -> None:
    if st.session_state.pop("_keep_alert_pin", False):
        st.session_state._station_seen = current
        return
    seen = st.session_state.get("_station_seen")
    if seen is not None and seen != current:
        st.session_state.alert_id = None
        st.session_state.browse_ts = None
        st.session_state._hour_pin = ""
        st.session_state.pop("station_hour", None)
    st.session_state._station_seen = current


def _identity(
    station: dict[str, Any],
    names: dict[str, str],
    hour: dict[str, Any] | None,
    *,
    on_live: bool,
    pinned_here: bool,
    pinned: dict[str, Any] | None,
) -> None:
    if pinned_here and pinned is not None:
        tag = f"Pinned · {alert_status_label(pinned)}"
    elif hour is not None and not on_live:
        tag = f"{hour_caption(hour)} · {fmt_stamp(hour.get('timestamp'))}"
    elif station.get("isolate"):
        tag = "Isolate"
    else:
        tag = status_label(station)
    st.markdown(identity_html(station, tag, names), unsafe_allow_html=True)


def _go_hour(timestamp: str | None) -> None:
    if timestamp is None:
        st.session_state.browse_ts = None
        st.session_state.alert_id = None
        st.session_state.replay_ts = None
        st.session_state._hour_pin = ""
        st.session_state.pop("station_hour", None)
        return
    st.session_state.browse_ts = timestamp
    st.session_state.station_hour = timestamp


def _adopt_external_pin(pinned: dict[str, Any] | None, replay_ts: Any) -> None:
    """A new alert or replay chooses the hour. Browsing after that stays put."""
    if pinned is not None:
        token = stamp_key(pinned.get("timestamp"))
        raw = pinned.get("timestamp")
    elif replay_ts:
        token = stamp_key(replay_ts)
        raw = replay_ts
    else:
        token = ""
        raw = None
    if st.session_state.get("_hour_pin") == token:
        return
    st.session_state._hour_pin = token
    if not token:
        return
    st.session_state.browse_ts = None
    st.session_state.station_hour = raw


def _shown_hour(
    ordered: list[dict[str, Any]],
    pinned: dict[str, Any] | None,
    latest: dict[str, Any],
) -> dict[str, Any] | None:
    browse = hour_telemetry(ordered, st.session_state.get("browse_ts"))
    if st.session_state.get("browse_ts") and browse is None:
        st.session_state.browse_ts = None
    if browse is not None:
        return browse
    if pinned is not None:
        match = hour_telemetry(ordered, pinned.get("timestamp"))
        if match is not None:
            return match
    replay = hour_telemetry(ordered, st.session_state.get("replay_ts"))
    if replay is not None:
        return replay
    match = hour_telemetry(ordered, latest.get("timestamp"))
    if match is not None:
        return match
    return ordered[-1] if ordered else None


def _option_matching(options: list[str], timestamp: Any) -> str | None:
    key = stamp_key(timestamp)
    if not key:
        return None
    for option in options:
        if stamp_key(option) == key:
            return option
    return None


def _time_bar(
    ordered: list[dict[str, Any]],
    runs: list[list[dict[str, Any]]],
    hour: dict[str, Any] | None,
    latest: dict[str, Any],
) -> None:
    if not ordered or hour is None:
        return
    shown = str(hour.get("timestamp"))
    index = run_index(runs, shown)
    run = runs[index]
    earlier = adjacent_hour(ordered, shown, -1)
    later = adjacent_hour(ordered, shown, 1)
    on_latest = stamp_key(shown) == stamp_key(latest.get("timestamp")) and later is None
    previous_run = runs[index - 1][-1] if index > 0 else None
    next_run = runs[index + 1][0] if index + 1 < len(runs) else None

    st.markdown(
        section_html(
            "Stored hours",
            "Earlier and later walk every stored hour. The chart stays on this continuous run, so a long gap is not drawn as a line.",
        ),
        unsafe_allow_html=True,
    )
    back, forward, latest_col = st.columns(3, gap="small")
    with back:
        st.button(
            "Earlier",
            width="stretch",
            disabled=earlier is None,
            on_click=_go_hour,
            args=(None if earlier is None else str(earlier.get("timestamp")),),
            key="hour_earlier",
        )
    with forward:
        st.button(
            "Later",
            width="stretch",
            disabled=later is None,
            on_click=_go_hour,
            args=(None if later is None else str(later.get("timestamp")),),
            key="hour_later",
        )
    with latest_col:
        st.button(
            "Latest hour",
            width="stretch",
            disabled=on_latest and st.session_state.get("browse_ts") is None and st.session_state.get("replay_ts") is None and st.session_state.get("alert_id") is None,
            on_click=_go_hour,
            args=(None,),
            key="hour_latest",
        )
    if len(runs) > 1:
        prev_col, next_col = st.columns(2, gap="small")
        with prev_col:
            target = None if previous_run is None else str(previous_run.get("timestamp"))
            st.button(
                "Previous run",
                width="stretch",
                disabled=previous_run is None,
                on_click=_go_hour,
                args=(target,),
                key="hour_prev_run",
            )
        with next_col:
            st.button(
                "Next run",
                width="stretch",
                disabled=next_run is None,
                on_click=_go_hour,
                args=(None if next_run is None else str(next_run.get("timestamp")),),
                key="hour_next_run",
            )

    options = [str(row.get("timestamp")) for row in run]
    labels = {str(row.get("timestamp")): f"{fmt_stamp(row.get('timestamp'))} · {hour_caption(row)}" for row in run}
    canonical = _option_matching(options, shown) or options[-1]
    widget = st.session_state.get("station_hour")
    last_shown = st.session_state.get("_shown_rendered")
    widget_in_run = _option_matching(options, widget)
    following = st.session_state.get("browse_ts") is None
    if widget_in_run is None or (
        following and stamp_key(widget) == stamp_key(last_shown) and stamp_key(shown) != stamp_key(widget)
    ):
        st.session_state.station_hour = canonical
    picked = st.selectbox(
        "Hour in this run",
        options=options,
        format_func=lambda value: labels.get(value, value),
        key="station_hour",
    )
    if stamp_key(picked) != stamp_key(shown):
        st.session_state.browse_ts = picked
        st.rerun()
    st.session_state._shown_rendered = shown

    start = fmt_stamp(run[0].get("timestamp"))
    end = fmt_stamp(run[-1].get("timestamp"))
    span = start if start == end else f"{start} – {end}"
    st.caption(
        f"Run {index + 1} of {len(runs)} · {span} · {len(run)} hour{'s' if len(run) != 1 else ''}. "
        f"Showing {fmt_stamp(shown)} · {hour_caption(hour)}."
    )


def _reading_meta(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    humidity = row.get("rhum_observed")
    if humidity is None:
        humidity = row.get("rhum_pct")
    if "temp_observed" not in row and isinstance(row.get("observed"), dict):
        observed = row.get("observed") or {}
        return (
            f" · T {fmt_value(observed.get('temp_c'))}°C"
            f" · P {fmt_value(observed.get('pres_hpa'))} hPa"
            f" · H {fmt_value(observed.get('rhum_pct'))}%"
        )
    return (
        f" · T {fmt_value(row.get('temp_observed'))}°C"
        f" · P {fmt_value(row.get('pres_observed'))} hPa"
        f" · H {fmt_value(humidity)}%"
    )


def _verdict(
    station: dict[str, Any],
    alerts: list[dict[str, Any]],
    hour: dict[str, Any] | None,
    latest: dict[str, Any],
    pinned: dict[str, Any] | None,
    *,
    on_live: bool,
) -> None:
    name = short_name(station.get("name", station["station_id"]))
    live_label = status_label(station)

    if hour is None:
        text = "No hour stored yet. The live poll or a replay will light this station."
        meta = "No telemetry yet"
        kicker = f"{name} · idle"
        kind = "idle"
    elif pinned is not None:
        kind = alert_kind(pinned)
        stamp = fmt_stamp(pinned.get("timestamp"))
        text = pinned.get("explainability_text") or f"{name} · {alert_status_label(pinned)}"
        kicker = f"Pinned from Alerts · {alert_status_label(pinned)} · {name} · {station['station_id']}"
        meta = (
            f"{stamp} · {pinned.get('fault_type', '')} · confidence "
            f"{fmt_value(pinned.get('confidence_score'), 2)} · {pinned.get('severity', '')}"
            f"{_reading_meta(hour)}"
        )
    else:
        matched = hour_alert(alerts, hour.get("timestamp"))
        kind = alert_kind(matched) if matched is not None else hour_kind(hour)
        stamp = fmt_stamp(hour.get("timestamp"))
        if on_live and not (matched and matched.get("explainability_text")) and not hour.get("explainability_text"):
            text = {
                "clean": f"{name} is tracking with its neighbors. No hardware alert this hour.",
                "warming": f"{name} is warming up. This raw hour is stored. A verdict waits for 24 hourly values.",
                "feedgap": (
                    f"IMD did not send {feed_gap_words(feed_gap(hour))} for most stations this hour. "
                    "Stored raw, not scored, sensor health not charged."
                ),
                "unknown": (
                    "Not enough same-hour neighbors for a buddy check. "
                    "Honesty over a fake spatial call."
                ),
                "idle": "No hour stored yet. The live poll or a replay will light this station.",
            }.get(kind, f"{name} · {live_label}")
            meta = stamp
        else:
            text = (
                (matched or {}).get("explainability_text")
                or hour.get("explainability_text")
                or f"{name} · {hour_caption(hour)}"
            )
            meta = stamp
            if matched and matched.get("fault_type"):
                meta = (
                    f"{matched.get('fault_type')} · confidence {fmt_value(matched.get('confidence_score'), 2)}"
                    f" · {matched.get('severity', '')} · {meta}"
                )
        meta += _reading_meta(hour)
        kicker = (
            f"This hour · {live_label} · {name}"
            if on_live
            else f"Stored hour · {hour_caption(hour)} · {name}"
        )

    st.markdown(
        f"""<div class="sg-verdict sg-verdict-{kind}">
        <div class="sg-verdict-kicker">{escape(kicker)}</div>
        <div class="sg-verdict-text">{escape(text)}</div>
        <div class="sg-verdict-meta">{escape(meta)}</div>
        </div>""",
        unsafe_allow_html=True,
    )
    if hour is not None and not on_live:
        observed = latest.get("observed") or {}
        st.caption(
            f"Latest hour is {live_label} · {fmt_stamp(latest.get('timestamp'))}"
            f" · T {fmt_value(observed.get('temp_c'))}°C"
            f" · P {fmt_value(observed.get('pres_hpa'))} hPa"
            f" · H {fmt_value(observed.get('rhum_pct'))}%."
            " Health above is the 7-day index. Latest hour returns there."
        )


def _charts(
    telemetry: list[dict[str, Any]],
    mark_at: Any | None,
    mark_label: str | None,
    *,
    warming: bool,
) -> list[dict[str, Any]]:
    window = cluster_around(telemetry, mark_at)
    if warming:
        caption = (
            f"Solid = raw T, P, and H. {collected_hours(window)} of {WINDOW_HOURS} hours in this run. "
            "No dashed overlay until QC."
        )
    else:
        caption = (
            "Solid = raw T, P, and H for this run. The dashed correction follows the sensor and leaves it on an hour with an imputed interval. The band covers that hour. The marker is the hour selected above."
        )
    st.markdown(section_html("Observed", caption), unsafe_allow_html=True)
    if window and len(window) != len(telemetry):
        st.caption("This chart is that continuous run, not the gap to a later live hour.")
    if not window:
        st.info("No telemetry yet for this station.")
        return []
    figures = telemetry_figures(window, mark_at=mark_at if mark_label else None, mark_label=mark_label)
    st.plotly_chart(figures[0], theme=None, width="stretch")
    left, right = st.columns(2, gap="medium")
    with left:
        st.plotly_chart(figures[1], theme=None, width="stretch")
    with right:
        st.plotly_chart(figures[2], theme=None, width="stretch")
    if not warming:
        ribbon = verdict_ribbon_html(window, mark_at)
        if ribbon:
            st.html(ribbon)
    return window


def _timing_for(client: Any, station_id: str, hour: dict[str, Any] | None) -> dict[str, Any] | None:
    if not hour or hour.get("warming_up") or not hour.get("timestamp"):
        return None
    try:
        return client.timing(station_id, str(hour["timestamp"]), wait_s=0)
    except SkyGuardApiError:
        return None


def _root_cause(
    hour: dict[str, Any] | None,
    alert: dict[str, Any] | None,
    timing: dict[str, Any] | None,
    *,
    threshold: float | None = None,
    names: dict[str, str] | None = None,
) -> None:
    st.markdown(
        section_html(
            "Why this hour",
            "The verdict sentence, then the three checks in the order QC ran them, then what the neighbors said and when the error entered the window.",
        ),
        unsafe_allow_html=True,
    )
    if hour and hour.get("warming_up"):
        st.caption("Warming up. The raw hour is stored. There is no verdict until 24 hourly values exist.")
        return
    if not hour and not alert:
        st.caption("No scored hour yet.")
        return

    reason = (hour or {}).get("explainability_text") or (alert or {}).get("explainability_text")
    st.markdown(f"**{reason}**" if reason else "No reason stored for this hour.")

    st.html(decision_trace_html(hour, alert, threshold))

    bars = contribution_html(alert)
    if bars:
        st.caption("Channel share of the reconstruction error on this hour. Not SHAP.")
        st.markdown(bars, unsafe_allow_html=True)
        if alert and is_weather(alert.get("label"), alert.get("fault_type")):
            st.caption("Neighbors agreed. This hour does not lower sensor health.")

    label = (hour or {}).get("label") or (alert or {}).get("label")
    table = neighbor_table_html(hour, names or {}, label)
    if table:
        st.html(table)

    _timing_block(timing)


def _timing_block(timing: dict[str, Any] | None) -> None:
    if not timing:
        return
    status = timing.get("status")
    if status == "pending":
        st.caption("TIMING is still running for this hour. The attribution chart appears when it is ready.")
        return
    if status != "ready":
        return
    body = timing.get("timing") if isinstance(timing.get("timing"), dict) else {}
    reason = body.get("reason")
    if reason:
        st.markdown(reason)
    figure = timing_figure(timing)
    if figure is not None:
        st.plotly_chart(figure, theme=None, width="stretch")
    line = timing_channels_line(timing)
    if line:
        st.caption(line + ". Integrated-gradients share of the LSTM score, computed off the ingest path.")


def _exports(
    station: dict[str, Any],
    window: list[dict[str, Any]],
    hour: dict[str, Any] | None,
    alert: dict[str, Any] | None,
    names: dict[str, str],
) -> None:
    if not window and not hour:
        return
    sid = str(station.get("station_id") or "station")
    stamp = stamp_key((hour or {}).get("timestamp")).replace(":", "") or "hour"
    st.markdown(
        section_html(
            "Take it with you",
            "Raw rows stay raw in the file. Predicted columns are filled only on hours QC corrected.",
        ),
        unsafe_allow_html=True,
    )
    left, mid, right = st.columns(3, gap="medium")
    with mid:
        st.link_button(
            "QC'd archive (CSV, 30 days)",
            get_client().export_url(sid, hours=24 * 30),
            width="stretch",
            help="GET /export: every stored hour with a WMO-style qc_flag (0 good · 1 probably good · 2 suspect · 3 erroneous · 9 not checked).",
        )
    with left:
        st.download_button(
            "Download this run (CSV)",
            data=run_csv(station, window),
            file_name=f"skyguard_{sid}_{stamp}.csv",
            mime="text/csv",
            width="stretch",
            disabled=not window,
            help="Every stored hour in the run shown above, observed and overlay columns side by side.",
        )
    with right:
        st.download_button(
            "Technician note (TXT)",
            data=technician_note(station, hour, alert, names),
            file_name=f"skyguard_{sid}_{stamp}_note.txt",
            mime="text/plain",
            width="stretch",
            disabled=hour is None,
            help="Plain-text summary of this hour for a maintenance ticket.",
        )
