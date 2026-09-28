"""Station page: identity, readings, warmup progress, overlay charts, root cause."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from api import SkyGuardApiError, merge_station
from charts import cluster_around, contribution_html, telemetry_figures, timing_figure
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
    verdict_kind,
)


def render_station() -> None:
    show_flash()
    client = get_client()
    health = client.health()
    page_header(
        "Station",
        "Raw T / P / H stay on the tiles. A predicted overlay appears only when this hour is distrusted.",
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

    replay_hour = hour_telemetry(telemetry, st.session_state.get("replay_ts"))
    focus = None if pinned is not None else replay_hour
    latest = latest_payload(station)
    hour = _focus_hour(station, telemetry, pinned, focus)
    alert = pinned if pinned is not None else hour_alert(alerts, (hour or latest).get("timestamp"))
    warming = bool((hour or latest).get("warming_up")) and pinned is None and focus is None

    _identity(station, pinned, focus, names)
    if warming:
        window = cluster_around(telemetry, latest.get("timestamp"))
        st.markdown(
            warmup_html(collected_hours(window), fmt_stamp(latest.get("timestamp"))),
            unsafe_allow_html=True,
        )
    else:
        _verdict(station, alerts, telemetry, pinned, focus)
    st.markdown(readings_html(hour or latest, warming=warming), unsafe_allow_html=True)

    health_col, buddy_col = st.columns(2, gap="medium")
    with health_col:
        st.markdown(health_html(station), unsafe_allow_html=True)
    with buddy_col:
        st.markdown(buddy_html(station, names, hour), unsafe_allow_html=True)

    if pinned is not None:
        mark_at, mark_label = pinned.get("timestamp"), "Pinned alert"
    elif focus is not None:
        mark_at, mark_label = focus.get("timestamp"), "Replay hour"
    else:
        mark_at, mark_label = latest.get("timestamp"), None
    window = _charts(telemetry, mark_at, mark_label, warming=warming)
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
    st.session_state._station_seen = current


def _identity(
    station: dict[str, Any],
    pinned: dict[str, Any] | None,
    focus: dict[str, Any] | None,
    names: dict[str, str],
) -> None:
    if pinned is not None:
        tag = f"Pinned · {alert_status_label(pinned)}"
    elif focus is not None:
        tag = f"Replay · {hour_caption(focus)}"
    elif station.get("isolate"):
        tag = "Isolate"
    else:
        tag = status_label(station)
    st.markdown(identity_html(station, tag, names), unsafe_allow_html=True)


def _clear_focus() -> None:
    st.session_state.alert_id = None
    st.session_state.replay_ts = None
    st.rerun()


def _verdict(
    station: dict[str, Any],
    alerts: list[dict[str, Any]],
    telemetry: list[dict[str, Any]],
    pinned: dict[str, Any] | None,
    focus: dict[str, Any] | None = None,
) -> None:
    latest = latest_payload(station)
    name = short_name(station.get("name", station["station_id"]))
    live_label = status_label(station)

    if pinned is not None:
        kind = alert_kind(pinned)
        stamp = fmt_stamp(pinned.get("timestamp"))
        text = pinned.get("explainability_text") or f"{name} · {alert_status_label(pinned)}"
        kicker = f"Pinned from Alerts · {alert_status_label(pinned)} · {name} · {station['station_id']}"
        meta = (
            f"{stamp} · {pinned.get('fault_type', '')} · confidence "
            f"{fmt_value(pinned.get('confidence_score'), 2)} · {pinned.get('severity', '')}"
        )
        hour = hour_telemetry(telemetry, pinned.get("timestamp"))
        if hour:
            meta += (
                f" · T {fmt_value(hour.get('temp_observed'))}°C"
                f" · P {fmt_value(hour.get('pres_observed'))} hPa"
                f" · H {fmt_value(hour.get('rhum_pct') if hour.get('rhum_pct') is not None else hour.get('rhum_observed'))}%"
            )
        elif latest.get("observed") and stamp_key(latest.get("timestamp")) == stamp_key(pinned.get("timestamp")):
            observed = latest.get("observed") or {}
            meta += (
                f" · T {fmt_value(observed.get('temp_c'))}°C"
                f" · P {fmt_value(observed.get('pres_hpa'))} hPa"
                f" · H {fmt_value(observed.get('rhum_pct'))}%"
            )
    elif focus is not None:
        matched = hour_alert(alerts, focus.get("timestamp"))
        kind = alert_kind(matched) if matched is not None else hour_kind(focus)
        stamp = fmt_stamp(focus.get("timestamp"))
        text = (
            (matched or {}).get("explainability_text")
            or focus.get("explainability_text")
            or f"{name} · {hour_caption(focus)}"
        )
        kicker = f"Replay · {hour_caption(focus)} · {name}"
        meta = (
            f"{stamp}"
            f" · T {fmt_value(focus.get('temp_observed'))}°C"
            f" · P {fmt_value(focus.get('pres_observed'))} hPa"
            f" · H {fmt_value(focus.get('rhum_observed'))}%"
        )
        if matched and matched.get("fault_type"):
            meta = f"{matched.get('fault_type')} · {meta}"
    elif latest:
        kind = verdict_kind(station)
        matched = hour_alert(alerts, latest.get("timestamp"))
        if matched and matched.get("explainability_text"):
            text = matched["explainability_text"]
            meta = (
                f"{matched.get('fault_type', '')} · confidence {fmt_value(matched.get('confidence_score'), 2)}"
                f" · {matched.get('severity', '')}"
            )
        else:
            text = {
                "clean": f"{name} is tracking with its neighbors. No hardware alert this hour.",
                "warming": f"{name} is warming up. This raw hour is stored. A verdict waits for 24 hourly values.",
                "feedgap": (
                    f"IMD did not send {feed_gap_words(feed_gap(latest))} for most stations this hour. "
                    "Stored raw, not scored, sensor health not charged."
                ),
                "unknown": (
                    "Not enough same-hour neighbors for a buddy check. "
                    "Honesty over a fake spatial call."
                ),
                "idle": "No hour stored yet. The live poll or a replay will light this station.",
            }.get(kind, f"{name} · {live_label}")
            meta = fmt_stamp(latest.get("timestamp"))
        kicker = f"This hour · {live_label} · {name}"
        observed = latest.get("observed") or {}
        if observed:
            meta += (
                f" · T {fmt_value(observed.get('temp_c'))}°C"
                f" · P {fmt_value(observed.get('pres_hpa'))} hPa"
                f" · H {fmt_value(observed.get('rhum_pct'))}%"
            )
    else:
        text = "No hour stored yet. The live poll or a replay will light this station."
        meta = "No telemetry yet"
        kicker = f"{name} · idle"
        kind = "idle"

    st.markdown(
        f"""<div class="sg-verdict sg-verdict-{kind}">
        <div class="sg-verdict-kicker">{escape(kicker)}</div>
        <div class="sg-verdict-text">{escape(text)}</div>
        <div class="sg-verdict-meta">{escape(meta)}</div>
        </div>""",
        unsafe_allow_html=True,
    )
    if pinned is not None or focus is not None:
        live_kind = verdict_kind(station)
        same_hour = stamp_key(latest.get("timestamp")) == stamp_key(
            (pinned or focus or {}).get("timestamp")
        )
        if not same_hour:
            observed = latest.get("observed") or {}
            st.caption(
                f"Live hour is {live_label}"
                f" · T {fmt_value(observed.get('temp_c'))}°C"
                f" · P {fmt_value(observed.get('pres_hpa'))} hPa"
                f" · H {fmt_value(observed.get('rhum_pct'))}%."
                " Health above is the 7-day index."
            )
        elif live_kind != kind:
            st.caption(f"Live hour is {live_label}. Health above is the 7-day index.")
        if st.button("Show live hour", key="clear_alert_pin"):
            _clear_focus()


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
            "Solid = raw T, P, and H. The dashed correction follows the sensor and leaves it on an hour with an imputed interval. The band covers that hour."
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


def _focus_hour(
    station: dict[str, Any],
    telemetry: list[dict[str, Any]],
    pinned: dict[str, Any] | None,
    focus: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if pinned is not None:
        hour = hour_telemetry(telemetry, pinned.get("timestamp"))
        if hour is not None:
            return hour
    if focus is not None:
        return focus
    latest = latest_payload(station)
    hour = hour_telemetry(telemetry, latest.get("timestamp"))
    return hour or (telemetry[-1] if telemetry else None)


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
    left, right = st.columns(2, gap="medium")
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
