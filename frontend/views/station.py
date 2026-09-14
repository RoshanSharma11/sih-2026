"""Station page: overlay charts, hour inspector, verdict, contribution, health."""

from __future__ import annotations

from typing import Any

import streamlit as st

from api import SkyGuardApiError, merge_station
from charts import contribution_html, telemetry_figures
from chrome import (
    DEFAULT_VIEW,
    fmt_value,
    get_client,
    offline_help,
    overlay_banner,
    page_header,
    show_flash,
    station_options,
)
from status import (
    SKIP_TEXT,
    channel_label,
    channel_unit,
    confidence_text,
    fault_label,
    hour_alert,
    hour_telemetry,
    is_weather,
    pick_alert,
    pipeline_label,
    primary_channel,
    row_kind,
    row_matches_pending,
    severity_text,
    short_name,
    stamp_key,
    stamp_label,
    status_label,
)


def render_station() -> None:
    show_flash()
    client = get_client()
    health = client.health()
    page_header(
        "Station",
        "Inspect any hour. Solid = observed (never overwritten). Dashed = predicted reconstruction.",
        health,
    )
    view_ids = list(st.session_state.get("view_ids") or DEFAULT_VIEW)
    try:
        view_rows = client.stations(ids=view_ids)
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return

    options = station_options(view_rows)
    current = st.session_state.get("station_id")
    if current and current not in options:
        options = _add_station_option(client, options, current)
    if not options:
        st.info("Add stations to the Network view set to inspect a series.")
        return

    if current not in options:
        current = next(iter(options))
        st.session_state.station_id = current

    _sync_station_change(current)
    st.selectbox(
        "Station",
        options=list(options.keys()),
        format_func=lambda sid: options.get(sid, sid),
        key="station_id",
    )
    try:
        telemetry = client.telemetry(current)
        alerts = client.alerts(current, limit=200)
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return
    _hour_controls(telemetry, alerts)
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
        telemetry = client.telemetry(station_id)
        alerts = client.alerts(station_id, limit=200)
        overlays = client.demo_status().get("overlays") or []
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return

    overlay_banner(overlays)
    _apply_pending_inspect()
    _maybe_latch(station_id, telemetry, alerts)

    pinned = pick_alert(alerts, st.session_state.get("alert_id"))
    if pinned is not None and not st.session_state.get("inspect_key"):
        st.session_state.inspect_key = stamp_key(pinned.get("timestamp"))
        st.session_state.inspect_mode = "inspect"
        st.session_state.event_latched = True

    hour, live_row = _resolve_hour(client, station_id, telemetry)
    hour = _enrich_hour(hour, alerts)
    waiting = st.session_state.get("inspect_mode") == "event" and not st.session_state.get(
        "event_latched"
    )
    if waiting:
        st.info("Overlay armed. Waiting for the next streamed hour to score.")
    if _is_inspecting(live_row, hour):
        st.caption(
            f"Inspecting {stamp_label(None if hour is None else hour.get('timestamp'))} · "
            f"live hour is {status_label(station)}."
        )
    _identity(station, hour)
    _verdict(station, hour, live_row)
    _facts(hour)
    _health_and_buddies(station, hour)
    _charts(station_id, telemetry, None if hour is None else hour.get("timestamp"))
    _explain(hour)


def _apply_pending_inspect() -> None:
    pending = st.session_state.pop("_pending_inspect_key", None)
    if pending is None:
        return
    st.session_state.inspect_key = pending
    mode = st.session_state.pop("_pending_inspect_mode", None)
    if mode:
        st.session_state.inspect_mode = mode
    if st.session_state.pop("_pending_inspect_latch", False):
        st.session_state.event_latched = True
        st.session_state.alert_id = None
    st.rerun()


def _follow_live(live_stamp: str | None) -> None:
    st.session_state.inspect_mode = "live"
    st.session_state.event_latched = False
    st.session_state.pending_kind = None
    st.session_state.pending_stations = []
    st.session_state.alert_id = None
    if live_stamp:
        st.session_state.inspect_key = live_stamp


def _add_station_option(
    client: Any, options: dict[str, str], station_id: str
) -> dict[str, str]:
    try:
        row = client.station(station_id)
    except SkyGuardApiError:
        return options
    name = short_name(row.get("name", station_id))
    return {station_id: f"{name}  ·  {station_id}", **options}


def _sync_station_change(current: str) -> None:
    if st.session_state.pop("_keep_alert_pin", False):
        st.session_state._station_seen = current
        return
    seen = st.session_state.get("_station_seen")
    if seen is not None and seen != current:
        st.session_state.alert_id = None
        if st.session_state.get("inspect_mode") == "event":
            st.session_state.event_latched = False
            st.session_state.inspect_key = None
        else:
            st.session_state.inspect_key = None
    st.session_state._station_seen = current


def _maybe_latch(station_id: str, telemetry: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> None:
    if st.session_state.get("inspect_mode") != "event":
        return
    if st.session_state.get("event_latched"):
        return
    pending = set(st.session_state.get("pending_stations") or [])
    if pending and station_id not in pending:
        return
    kind = st.session_state.get("pending_kind")
    injected = [row for row in telemetry if row.get("demo_injected") == kind]
    matches = injected or [row for row in telemetry if row_matches_pending(row, kind)]
    if not matches:
        return
    row = matches[-1]
    st.session_state.inspect_key = stamp_key(row.get("timestamp"))
    st.session_state.event_latched = True
    matched = hour_alert(alerts, row.get("timestamp"))
    st.session_state.alert_id = None if matched is None else matched.get("alert_id")
    st.rerun()


def _on_hour_pick() -> None:
    st.session_state.inspect_mode = "inspect"
    st.session_state.event_latched = True
    st.session_state.inspect_key = st.session_state.get("hour_pick")
    st.session_state.alert_id = None


def _following_live() -> bool:
    mode = st.session_state.get("inspect_mode") or "live"
    return mode == "live" or (mode == "event" and not st.session_state.get("event_latched"))


def _resolve_hour(
    client: Any, station_id: str, telemetry: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    live_row = telemetry[-1] if telemetry else None
    if _following_live():
        return live_row, live_row
    key = st.session_state.get("inspect_key") or st.session_state.get("hour_pick")
    hour = hour_telemetry(telemetry, key) if key else live_row
    if hour is None and key:
        try:
            hour = client.hour(station_id, key)
        except SkyGuardApiError:
            hour = live_row
    return hour, live_row


def _hour_label(key: str, by_key: dict[str, dict[str, Any]]) -> str:
    stamp = stamp_label(key)
    row = by_key.get(key)
    if not row or not row.get("is_anomaly"):
        return stamp
    fault = fault_label(row.get("fault_type")) if row.get("fault_type") else pipeline_label(
        row.get("label") or row.get("pipeline_status")
    )
    return f"{stamp}  ·  {fault}"


def _hour_controls(telemetry: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> None:
    del alerts
    by_key = {stamp_key(row.get("timestamp")): row for row in telemetry}
    keys = [key for key in by_key if key]
    if not keys:
        st.caption("No telemetry yet. Start the streamer, then pick an hour here.")
        return
    inspect = st.session_state.get("inspect_key")
    if _following_live():
        st.session_state.hour_pick = keys[-1]
    elif inspect and inspect in keys:
        st.session_state.hour_pick = inspect
    elif st.session_state.get("hour_pick") not in keys:
        st.session_state.hour_pick = keys[-1]
    detections = [key for key, row in by_key.items() if row.get("is_anomaly")]
    detections.reverse()
    picker, jump, follow = st.columns([2.4, 1.6, 0.9])
    with picker:
        st.selectbox(
            "Inspect hour",
            options=keys,
            format_func=lambda key: _hour_label(key, by_key),
            key="hour_pick",
            on_change=_on_hour_pick,
            help="Red hours are labeled in this list. The list does not refresh while open.",
        )
    with jump:
        if detections:
            st.selectbox(
                "Jump to detection",
                options=["", *detections],
                format_func=lambda key: "Select a flagged hour" if key == "" else _hour_label(key, by_key),
                key="detection_pick",
                on_change=_on_detection_pick,
            )
        else:
            st.caption("No flagged hours in this series yet.")
    with follow:
        st.write("")
        live_stamp = stamp_key(telemetry[-1].get("timestamp")) if telemetry else None
        st.button(
            "Follow live",
            width="stretch",
            disabled=_following_live(),
            on_click=_follow_live,
            args=(live_stamp,),
        )
    st.caption("Flagged hours are marked in the dropdown. Pick one, or click a rose/amber point on the chart.")


def _on_detection_pick() -> None:
    picked = st.session_state.get("detection_pick")
    if not picked:
        return
    st.session_state.inspect_mode = "inspect"
    st.session_state.event_latched = True
    st.session_state.inspect_key = picked
    st.session_state.alert_id = None


def _enrich_hour(
    hour: dict[str, Any] | None, alerts: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if hour is None:
        return None
    matched = hour_alert(alerts, hour.get("timestamp"))
    if matched is None:
        return hour
    filled = dict(hour)
    if filled.get("confidence") is None:
        filled["confidence"] = matched.get("confidence_score")
    if not filled.get("severity"):
        filled["severity"] = matched.get("severity")
    if not filled.get("explainability_text"):
        filled["explainability_text"] = matched.get("explainability_text")
    if not filled.get("fault_type"):
        filled["fault_type"] = matched.get("fault_type")
    for key in ("contribution_temp", "contribution_pres", "contribution_rhum"):
        if filled.get(key) is None:
            filled[key] = matched.get(key)
    if filled.get("label") is None:
        filled["label"] = matched.get("label")
    return filled


def _is_inspecting(live_row: dict[str, Any] | None, hour: dict[str, Any] | None) -> bool:
    if hour is None or live_row is None:
        return False
    return stamp_key(hour.get("timestamp")) != stamp_key(live_row.get("timestamp"))


def _identity(station: dict[str, Any], hour: dict[str, Any] | None) -> None:
    name = short_name(station.get("name", station["station_id"]))
    if hour is not None:
        tag = f"Inspected · {pipeline_label(hour.get('label') or hour.get('pipeline_status'))}"
        if hour.get("demo_injected"):
            tag += f" · demo {fault_label(hour.get('demo_injected'))}"
    elif station.get("isolate"):
        tag = "Isolate · Tier 3 skipped"
    else:
        tag = status_label(station)
    st.markdown(f"**{name}** `{station['station_id']}` · {tag}")


def _verdict(
    station: dict[str, Any],
    hour: dict[str, Any] | None,
    live_row: dict[str, Any] | None,
) -> None:
    name = short_name(station.get("name", station["station_id"]))
    if hour is None:
        text = "Waiting for the clean streamer. Seed + hourly ingest will light this station."
        meta = "No telemetry yet"
        kicker = f"{name} · idle"
        kind = "idle"
    else:
        kind = row_kind(hour)
        stamp = stamp_label(hour.get("timestamp"))
        inspecting = _is_inspecting(live_row, hour)
        kicker = (
            f"{'Inspected hour' if inspecting else 'This hour'} · "
            f"{pipeline_label(hour.get('label') or hour.get('pipeline_status'))} · {name} · {station['station_id']}"
        )
        text = hour.get("explainability_text") or {
            "clean": f"{name} is tracking with its neighbors. No hardware alert this hour.",
            "unknown": (
                "Not enough same-hour neighbors for a buddy check, or the 24h window is still filling. "
                "Honesty over a fake spatial call."
            ),
            "idle": "Waiting for the clean streamer.",
        }.get(kind, f"{name} · {pipeline_label(hour.get('label'))}")
        meta = (
            f"{stamp} · {fault_label(hour.get('fault_type'))} · confidence "
            f"{confidence_text(hour)} · {severity_text(hour)}"
        )
        humidity = hour.get("rhum_pct")
        if humidity is None:
            humidity = hour.get("rhum_observed")
        meta += (
            f" · T {fmt_value(hour.get('temp_observed'))}°C"
            f" · P {fmt_value(hour.get('pres_observed'))} hPa"
            f" · H {fmt_value(humidity)}%"
        )
        if hour.get("demo_injected"):
            meta += f" · demo {fault_label(hour.get('demo_injected'))}"
    st.markdown(
        f"""<div class="sg-verdict sg-verdict-{kind}">
        <div class="sg-verdict-kicker">{kicker}</div>
        <div class="sg-verdict-text">{text}</div>
        <div class="sg-verdict-meta">{meta}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def _facts(hour: dict[str, Any] | None) -> None:
    if hour is None:
        return
    channel = primary_channel(hour)
    observed, predicted = _channel_pair(hour, channel)
    unit = channel_unit(channel)
    if is_weather(hour.get("label"), hour.get("fault_type")):
        health_hit = "No — genuine weather"
    elif hour.get("is_anomaly"):
        health_hit = "Yes — sensor"
    else:
        health_hit = "None"
    items = (
        ("Verdict", pipeline_label(hour.get("label") or hour.get("pipeline_status"))),
        ("Fault", fault_label(hour.get("fault_type")) if hour.get("fault_type") else "None"),
        ("Channel", channel_label(channel) if hour.get("is_anomaly") else "All within band"),
        ("Observed", f"{fmt_value(observed)}{unit}" if channel else "—"),
        ("Predicted", f"{fmt_value(predicted)}{unit}" if channel else "—"),
        ("Neighbors", _neighbor_text(hour.get("tier3"))),
        ("Confidence", confidence_text(hour)),
        ("Severity", severity_text(hour)),
        ("Health impact", health_hit),
    )
    cells = "".join(
        f'<div class="sg-fact"><div class="sg-fact-label">{label}</div>'
        f'<div class="sg-fact-value">{value}</div></div>'
        for label, value in items
    )
    st.markdown(f'<div class="sg-facts">{cells}</div>', unsafe_allow_html=True)


def _channel_pair(hour: dict[str, Any], channel: str | None) -> tuple[Any, Any]:
    mapping = {
        "temp_c": ("temp_observed", "temp_imputed"),
        "pres_hpa": ("pres_observed", "pres_imputed"),
        "rhum_pct": ("rhum_observed", "rhum_imputed"),
    }
    keys = mapping.get(channel or "", ("temp_observed", "temp_imputed"))
    return hour.get(keys[0]), hour.get(keys[1])


def _neighbor_text(tier3: Any) -> str:
    if not isinstance(tier3, dict) or not tier3:
        return "—"
    if not tier3.get("performed"):
        skip = tier3.get("reason_skip")
        return SKIP_TEXT.get(str(skip), "Skipped") if skip else "Not run"
    count = tier3.get("usable_count") or 0
    if tier3.get("neighbors_agree"):
        return f"Agreed · {count} stations"
    return f"Disagreed · {count} stations"


def _health_and_buddies(station: dict[str, Any], hour: dict[str, Any] | None) -> None:
    health = station.get("health_score")
    status = station.get("status")
    m1, m2, m3 = st.columns(3)
    m1.metric("Health (7-day, live)", f"{health:.0f}" if isinstance(health, (int, float)) else "—")
    m2.metric("Station status", status or "—")
    hour_label = (
        pipeline_label(hour.get("label") or hour.get("pipeline_status")) if hour else status_label(station)
    )
    m3.metric("Inspected hour", hour_label)
    st.caption("The 7-day health index ignores genuine weather. Isolates and one-buddy hours stay unconfirmed.")

    buddies = station.get("buddy_ids") or []
    if station.get("isolate"):
        st.markdown('<span class="sg-chip sg-chip-idle">Isolate</span>', unsafe_allow_html=True)
        st.caption("Fewer than two buddies on the ML graph. Tier 3 will not run.")
        return
    chips = "".join(f'<span class="sg-buddy">{sid}</span>' for sid in buddies)
    st.markdown(
        f'<p class="sg-caption" style="margin-bottom:0.35rem">1-hop buddies</p>{chips}',
        unsafe_allow_html=True,
    )


def _charts(station_id: str, telemetry: list[dict[str, Any]], mark_at: Any | None) -> None:
    st.markdown("##### Observed vs predicted")
    st.caption(
        "Solid = raw (never overwritten). Dashed = reconstruction. "
        "Marker color is the QC label for that hour. Click a point to inspect it."
    )
    if not telemetry:
        st.info("No telemetry yet for this station. Start the clean streamer, then wait one poll.")
        return
    for index, fig in enumerate(telemetry_figures(telemetry, mark_at=mark_at)):
        event = st.plotly_chart(
            fig,
            theme=None,
            width="stretch",
            on_select="rerun",
            selection_mode="points",
            key=f"sg_chart_{station_id}_{index}",
            config={"displayModeBar": False},
        )
        _apply_chart_selection(event)


def _apply_chart_selection(event: Any) -> None:
    stamp = _chart_x(event)
    if not stamp:
        return
    key = stamp_key(stamp)
    if not st.session_state.get("_chart_armed"):
        st.session_state._chart_armed = True
        st.session_state._chart_pick = key
        return
    if not key or st.session_state.get("_chart_pick") == key:
        return
    st.session_state._chart_pick = key
    st.session_state._pending_inspect_key = key
    st.session_state._pending_inspect_mode = "inspect"
    st.session_state._pending_inspect_latch = True


def _chart_x(event: Any) -> Any:
    selection = getattr(event, "selection", None)
    points = getattr(selection, "points", None) if selection is not None else None
    if not points:
        return None
    point = points[0]
    if isinstance(point, dict):
        return point.get("x")
    return getattr(point, "x", None)


def _explain(hour: dict[str, Any] | None) -> None:
    html = contribution_html(hour)
    if html:
        st.markdown("##### Why this hour")
        st.caption("Channel share of reconstruction error. Not SHAP.")
        st.markdown(html, unsafe_allow_html=True)
        if hour and is_weather(hour.get("label"), hour.get("fault_type")):
            st.caption("Neighbors agreed. This alert does not lower sensor health.")
    _tier_expander(hour)


def _tier_expander(hour: dict[str, Any] | None) -> None:
    if hour is None:
        return
    tier1 = hour.get("tier1") or {}
    tier2 = hour.get("tier2") or {}
    tier3 = hour.get("tier3") or {}
    if not any((tier1, tier2, tier3)):
        return
    with st.expander("How we know"):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("**Tier 1 · physical rules**")
            if not tier1:
                st.caption("Not stored for this hour.")
            else:
                st.write("Passed" if tier1.get("passed") else "Failed")
                for item in tier1.get("violations") or []:
                    st.caption(str(item))
                if not tier1.get("violations"):
                    st.caption("Range, step, and missing-channel checks passed.")
        with col2:
            st.markdown("**Tier 2 · LSTM reconstruction**")
            if not tier2:
                st.caption("Not stored for this hour.")
            else:
                st.write("Ran" if tier2.get("ran") else "Did not run")
                mse = fmt_value(tier2.get("window_mse"), 4)
                thr = fmt_value(tier2.get("threshold"), 4)
                st.caption(f"Window MSE {mse} · threshold {thr}")
        with col3:
            st.markdown("**Tier 3 · buddy check**")
            if not tier3:
                st.caption("Not stored for this hour.")
            else:
                st.write(_neighbor_text(tier3))
                ids = tier3.get("buddy_ids") or []
                if ids:
                    st.caption("Buddies: " + ", ".join(str(item) for item in ids))
                residual = tier3.get("residual") or {}
                bits = []
                for key, label in (("temp_c", "T"), ("pres_hpa", "P"), ("rhum_pct", "H")):
                    val = residual.get(key)
                    if val is not None:
                        bits.append(f"{label} {fmt_value(val)}")
                if bits:
                    st.caption("Residual " + " · ".join(bits))
