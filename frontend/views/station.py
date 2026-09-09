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
    is_weather,
    latest_payload,
    short_name,
    status_label,
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
    if not options:
        st.info("Add stations to the Network view set to inspect a series.")
        return

    current = st.session_state.get("station_id")
    if current not in options:
        current = next(iter(options))
        st.session_state.station_id = current

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
        alerts = client.alerts(station_id)
    except SkyGuardApiError as exc:
        offline_help(str(exc))
        return

    _identity(station)
    _verdict(station, alerts)
    _health_and_buddies(station)
    _charts(telemetry)
    _explain(alerts)


def _identity(station: dict[str, Any]) -> None:
    name = short_name(station.get("name", station["station_id"]))
    isolate = station.get("isolate")
    tag = "Isolate · Tier 3 skipped" if isolate else status_label(station)
    st.markdown(
        f"**{name}** `{station['station_id']}` · {tag}",
    )


def _verdict(station: dict[str, Any], alerts: list[dict[str, Any]]) -> None:
    latest = latest_payload(station)
    alert = alerts[0] if alerts else None
    fault = None if alert is None else alert.get("fault_type")
    kind = verdict_kind(station, fault)
    name = short_name(station.get("name", station["station_id"]))

    if alert and alert.get("explainability_text"):
        text = alert["explainability_text"]
        meta = (
            f"{alert.get('fault_type', '')} · confidence {fmt_value(alert.get('confidence_score'), 2)}"
            f" · {alert.get('severity', '')}"
        )
        kicker = f"{status_label(station)} · {name} · {station['station_id']}"
    elif latest:
        text = {
            "clean": f"{name} is tracking with its neighbors. No hardware alert this hour.",
            "unknown": (
                "Not enough same-hour neighbors for a buddy check, or the 24h window is still filling. "
                "Honesty over a fake spatial call."
            ),
            "idle": "Waiting for the clean streamer. Seed + hourly ingest will light this station.",
        }.get(kind, f"{name} · {status_label(station)}")
        meta = f"health {fmt_value(station.get('health_score'), 0)} · {station.get('status', '')}"
        kicker = f"{status_label(station)} · {name}"
    else:
        text = "Waiting for the clean streamer. Seed + hourly ingest will light this station."
        meta = "No telemetry yet"
        kicker = f"{name} · idle"
        kind = "idle"

    observed = latest.get("observed") or {}
    if observed:
        meta += (
            f" · T {fmt_value(observed.get('temp_c'))}°C"
            f" · P {fmt_value(observed.get('pres_hpa'))} hPa"
            f" · H {fmt_value(observed.get('rhum_pct'))}%"
        )

    st.markdown(
        f"""<div class="sg-verdict sg-verdict-{kind}">
        <div class="sg-verdict-kicker">{kicker}</div>
        <div class="sg-verdict-text">{text}</div>
        <div class="sg-verdict-meta">{meta}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def _health_and_buddies(station: dict[str, Any]) -> None:
    health = station.get("health_score")
    status = station.get("status")
    m1, m2, m3 = st.columns(3)
    m1.metric("Health (7-day)", f"{health:.0f}" if isinstance(health, (int, float)) else "—")
    m2.metric("Station status", status or "—")
    m3.metric("This hour", status_label(station))
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


def _charts(telemetry: list[dict[str, Any]]) -> None:
    st.markdown("##### Observed vs predicted")
    st.caption("Solid = raw (never overwritten). Dashed = reconstruction overlay.")
    if not telemetry:
        st.info("No telemetry yet for this station. Start the clean streamer, then wait one poll.")
        return
    for fig in telemetry_figures(telemetry):
        st.plotly_chart(fig, theme=None, width="stretch")


def _explain(alerts: list[dict[str, Any]]) -> None:
    alert = alerts[0] if alerts else None
    html = contribution_html(alert)
    if not html:
        return
    st.markdown("##### Why this hour")
    st.caption("Channel share of reconstruction error from the latest alert. Not SHAP.")
    st.markdown(html, unsafe_allow_html=True)
    if alert and is_weather(alert.get("label"), alert.get("fault_type")):
        st.caption("Neighbors agreed. This alert does not lower sensor health.")
