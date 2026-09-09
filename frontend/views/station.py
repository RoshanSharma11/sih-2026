"""Station page: overlay charts, verdict, contribution, health, buddies."""

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
    page_header,
    show_flash,
    station_options,
)
from status import (
    alert_kind,
    alert_status_label,
    hour_alert,
    hour_telemetry,
    is_weather,
    latest_payload,
    pick_alert,
    short_name,
    status_label,
    stamp_key,
    verdict_kind,
)


def render_station() -> None:
    show_flash()
    client = get_client()
    health = client.health()
    page_header(
        "Station",
        "Observed T / P / H stay on the chart. Predicted values are a dashed overlay.",
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
        telemetry = client.telemetry(station_id)
        alerts = client.alerts(station_id, limit=200)
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return

    pinned = pick_alert(alerts, st.session_state.get("alert_id"))
    if st.session_state.get("alert_id") and pinned is None:
        st.caption("That alert is no longer in the recent feed. Showing this hour instead.")
        st.session_state.alert_id = None

    _identity(station, pinned)
    _verdict(station, alerts, telemetry, pinned)
    _health_and_buddies(station, pinned)
    _charts(telemetry, None if pinned is None else pinned.get("timestamp"))
    _explain(pinned if pinned is not None else hour_alert(alerts, latest_payload(station).get("timestamp")))


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


def _identity(station: dict[str, Any], pinned: dict[str, Any] | None) -> None:
    name = short_name(station.get("name", station["station_id"]))
    isolate = station.get("isolate")
    if pinned is not None:
        tag = f"Pinned alert · {alert_status_label(pinned)}"
    elif isolate:
        tag = "Isolate · Tier 3 skipped"
    else:
        tag = status_label(station)
    st.markdown(
        f"**{name}** `{station['station_id']}` · {tag}",
    )


def _verdict(
    station: dict[str, Any],
    alerts: list[dict[str, Any]],
    telemetry: list[dict[str, Any]],
    pinned: dict[str, Any] | None,
) -> None:
    latest = latest_payload(station)
    name = short_name(station.get("name", station["station_id"]))
    live_label = status_label(station)

    if pinned is not None:
        kind = alert_kind(pinned)
        stamp = str(pinned.get("timestamp", "")).replace("T", " ").replace("Z", " UTC")
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
                "unknown": (
                    "Not enough same-hour neighbors for a buddy check, or the 24h window is still filling. "
                    "Honesty over a fake spatial call."
                ),
                "idle": "Waiting for the clean streamer. Seed + hourly ingest will light this station.",
            }.get(kind, f"{name} · {live_label}")
            meta = f"health {fmt_value(station.get('health_score'), 0)} · {station.get('status', '')}"
        kicker = f"This hour · {live_label} · {name}"
        observed = latest.get("observed") or {}
        if observed:
            meta += (
                f" · T {fmt_value(observed.get('temp_c'))}°C"
                f" · P {fmt_value(observed.get('pres_hpa'))} hPa"
                f" · H {fmt_value(observed.get('rhum_pct'))}%"
            )
    else:
        text = "Waiting for the clean streamer. Seed + hourly ingest will light this station."
        meta = "No telemetry yet"
        kicker = f"{name} · idle"
        kind = "idle"

    st.markdown(
        f"""<div class="sg-verdict sg-verdict-{kind}">
        <div class="sg-verdict-kicker">{kicker}</div>
        <div class="sg-verdict-text">{text}</div>
        <div class="sg-verdict-meta">{meta}</div>
        </div>""",
        unsafe_allow_html=True,
    )
    if pinned is not None:
        live_kind = verdict_kind(station)
        if live_kind != kind or stamp_key(latest.get("timestamp")) != stamp_key(pinned.get("timestamp")):
            st.caption(
                f"Live hour is {live_label}. Health below is the 7-day index, not this alert."
            )
        if st.button("Show live hour", key="clear_alert_pin"):
            st.session_state.alert_id = None
            st.rerun()


def _health_and_buddies(station: dict[str, Any], pinned: dict[str, Any] | None) -> None:
    health = station.get("health_score")
    status = station.get("status")
    m1, m2, m3 = st.columns(3)
    m1.metric("Health (7-day)", f"{health:.0f}" if isinstance(health, (int, float)) else "—")
    m2.metric("Station status", status or "—")
    hour_label = alert_status_label(pinned) if pinned is not None else status_label(station)
    m3.metric("This hour" if pinned is None else "Pinned hour", hour_label)
    st.caption("Health ignores genuine weather. Isolates and one-buddy hours stay unconfirmed.")

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


def _charts(telemetry: list[dict[str, Any]], mark_at: Any | None) -> None:
    st.markdown("##### Observed vs predicted")
    if mark_at is not None:
        st.caption("Solid = raw (never overwritten). Dashed = reconstruction. Dotted line = the alert you opened.")
    else:
        st.caption("Solid = raw (never overwritten). Dashed = reconstruction overlay.")
    if not telemetry:
        st.info("No telemetry yet for this station. Start the clean streamer, then wait one poll.")
        return
    for fig in telemetry_figures(telemetry, mark_at=mark_at):
        st.plotly_chart(fig, theme=None, width="stretch")


def _explain(alert: dict[str, Any] | None) -> None:
    html = contribution_html(alert)
    if not html:
        return
    st.markdown("##### Why this hour")
    if st.session_state.get("alert_id") and alert and str(alert.get("alert_id")) == str(st.session_state.get("alert_id")):
        st.caption("Channel share of reconstruction error from the pinned alert. Not SHAP.")
    else:
        st.caption("Channel share of reconstruction error from this hour’s alert. Not SHAP.")
    st.markdown(html, unsafe_allow_html=True)
    if alert and is_weather(alert.get("label"), alert.get("fault_type")):
        st.caption("Neighbors agreed. This alert does not lower sensor health.")
