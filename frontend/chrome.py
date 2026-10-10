"""Shared session, client, header, KPIs, offline help."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st
from api import SkyGuardApiError, SkyGuardClient
from status import short_name
from theme import CLEAN, CSS, FEEDGAP, HARDWARE, SLATE, WARMING, WEATHER

_PAGES: dict[str, Any] = {}
_ASSETS = Path(__file__).resolve().parent / "assets"
_WORDMARK = _ASSETS / "skyguard-wordmark.svg"
_MARK = _ASSETS / "skyguard-mark.svg"

SAFDARJUNG = "42182"
SANTACRUZ = "43003"
COLABA = "43057"
JUHU = "43002"
ALIBAG = "43058"
RATNAGIRI = "43110"
DEMO_FOCUS = [RATNAGIRI, SANTACRUZ, COLABA, JUHU, ALIBAG, SAFDARJUNG]
DEFAULT_VIEW = list(DEMO_FOCUS)


def render_html(html: str) -> None:
    """Insert HTML without Markdown collapsing spaces between words."""
    st.html(html)


def inject_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    if _WORDMARK.exists():
        st.logo(
            str(_WORDMARK),
            icon_image=str(_MARK) if _MARK.exists() else None,
            size="large",
        )


def render_sidebar(
    operations: list[Any],
    demo: list[Any],
    guide: list[Any],
) -> None:
    with st.sidebar:
        st.markdown(
            '<p class="sg-brand-sub">Live QC for Indian AWS</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="sg-nav-section">Operations</div>', unsafe_allow_html=True
        )
        for page in operations:
            st.page_link(page, width="stretch")
        st.markdown('<div class="sg-nav-section">Demo</div>', unsafe_allow_html=True)
        for page in demo:
            st.page_link(page, width="stretch")
        st.markdown('<div class="sg-nav-section">Guide</div>', unsafe_allow_html=True)
        for page in guide:
            st.page_link(page, width="stretch")
        st.markdown(
            """<div class="sg-sidebar-foot">
            <strong>SIH PS 26073</strong><br>
            48 live stations · 24-hour warm-up
            </div>""",
            unsafe_allow_html=True,
        )


def register_pages(pages: dict[str, Any]) -> None:
    _PAGES.update(pages)
    st.session_state["_pages"] = dict(pages)


def go_page(name: str) -> None:
    page = _PAGES.get(name) or (st.session_state.get("_pages") or {}).get(name)
    if page is None:
        raise RuntimeError(f"Unknown page {name!r}. Register it in app.py.")
    st.switch_page(page)


def focus_station(station_id: str, alert_id: Any | None = None) -> None:
    st.session_state.station_id = str(station_id)
    st.session_state.alert_id = alert_id
    st.session_state._keep_alert_pin = alert_id is not None


def init_session() -> None:
    saved = st.session_state.get("_pages")
    if saved and not _PAGES:
        _PAGES.update(saved)
    if "view_ids" not in st.session_state:
        st.session_state.view_ids = list(DEFAULT_VIEW)
    if "station_id" not in st.session_state:
        st.session_state.station_id = RATNAGIRI
    if "include_buddies" not in st.session_state:
        st.session_state.include_buddies = True
    if "flash" not in st.session_state:
        st.session_state.flash = None
    if "alerts_station_only" not in st.session_state:
        st.session_state.alerts_station_only = False
    if "alerts_kind" not in st.session_state:
        st.session_state.alerts_kind = "all"
    if "alert_id" not in st.session_state:
        st.session_state.alert_id = None
    if "replay_ts" not in st.session_state:
        st.session_state.replay_ts = None
    if "replay_last" not in st.session_state:
        st.session_state.replay_last = None
    if "control_story" not in st.session_state:
        st.session_state.control_story = "hardware"
    if "inject_kind" not in st.session_state:
        st.session_state.inject_kind = "SPIKE"
    if "inject_channel" not in st.session_state:
        st.session_state.inject_channel = "temp_c"
    if "inject_hours" not in st.session_state:
        st.session_state.inject_hours = 1


@st.cache_resource
def get_client() -> SkyGuardClient:
    return SkyGuardClient()


@st.cache_data(ttl=120, show_spinner=False)
def catalog_stations() -> list[dict[str, Any]]:
    return get_client().stations()


@st.cache_data(ttl=300, show_spinner=False)
def cached_buddy_map() -> dict[str, Any]:
    return get_client().buddy_map()


def flash(message: str, kind: str = "ok") -> None:
    st.session_state.flash = {"message": message, "kind": kind}


def fire_inject(body: dict[str, Any]) -> None:
    try:
        status = get_client().inject(body)
    except SkyGuardApiError as exc:
        flash(str(exc), kind="bad")
        return
    st.session_state.inject_last = {"body": body, "status": status}
    station_id = body.get("station_id")
    if station_id:
        focus_station(str(station_id))
    hours = body.get("duration_hours", 1)
    flash(
        f"Armed {body['kind']} for {hours}h. Play on 1 June 2024 scores every armed event in order."
    )


def fire_replay(story: str, *, open_station: bool = False) -> None:
    try:
        body = get_client().replay(story)
    except SkyGuardApiError as exc:
        flash(str(exc), kind="bad")
        return
    focus_station(SANTACRUZ)
    end = body.get("end")
    st.session_state.replay_ts = None if end is None else str(end)
    payload = dict(body) if isinstance(body, dict) else {}
    payload["story"] = story
    st.session_state.replay_last = payload
    santa = next(
        (
            row
            for row in payload.get("results") or []
            if row.get("station_id") == SANTACRUZ
        ),
        None,
    )
    if santa and santa.get("warming_up"):
        flash("Santa Cruz is warming up. The raw hour is stored.")
    else:
        label = None if santa is None else santa.get("label")
        flash(f"Replay {story} · Santa Cruz {label or 'scored'}.")
    if open_station:
        go_page("station")


def fire_play() -> None:
    try:
        body = get_client().play()
    except SkyGuardApiError as exc:
        flash(str(exc), kind="bad")
        return
    station_ids = [str(station_id) for station_id in body.get("station_ids") or []]
    focus_station(station_ids[-1] if station_ids else SANTACRUZ)
    end = body.get("end")
    st.session_state.replay_ts = None if end is None else str(end)
    st.session_state.browse_ts = None
    st.session_state._hour_pin = ""
    hours = body.get("scored_hours") or 0
    flash(
        f"Played {hours} scored hours from 1 June 2024. Each armed event follows the one before it."
    )
    go_page("station")


def fire_reset() -> None:
    try:
        get_client().reset()
        st.session_state.inject_last = None
        flash("Overlays cleared.")
    except SkyGuardApiError as exc:
        flash(str(exc), kind="bad")


def show_flash() -> None:
    note = st.session_state.flash
    if not note:
        return
    if note["kind"] == "bad":
        st.error(note["message"])
    else:
        st.success(note["message"])
    st.session_state.flash = None


def page_header(
    title: str,
    subtitle: str,
    health: dict[str, Any] | None = None,
    *,
    show_status: bool = True,
) -> None:
    if not show_status:
        st.markdown(
            '<div class="sg-kicker">SkyGuard · live QC</div>', unsafe_allow_html=True
        )
        st.title(title)
        st.markdown(f'<p class="sg-sub">{subtitle}</p>', unsafe_allow_html=True)
        return
    left, right = st.columns([3, 2])
    with left:
        st.markdown(
            '<div class="sg-kicker">SkyGuard · live QC</div>', unsafe_allow_html=True
        )
        st.title(title)
        st.markdown(f'<p class="sg-sub">{subtitle}</p>', unsafe_allow_html=True)
    with right:
        st.write("")
        chips: list[str] = []
        if health is None:
            chips.append('<span class="sg-chip sg-chip-idle">API unknown</span>')
        elif health.get("ok"):
            chips.append('<span class="sg-chip sg-chip-ok">API live</span>')
            if health.get("model_loaded"):
                chips.append('<span class="sg-chip sg-chip-ok">Model loaded</span>')
            else:
                chips.append('<span class="sg-chip sg-chip-bad">Model missing</span>')
            n_stations = health.get("n_stations")
            if isinstance(n_stations, int) and n_stations:
                chips.append(f'<span class="sg-chip">{n_stations} stations</span>')
        else:
            chips.append('<span class="sg-chip sg-chip-bad">API down</span>')
        st.markdown(
            f'<div class="sg-health">{"".join(chips)}</div>', unsafe_allow_html=True
        )


def kpi_strip(counts: dict[str, int]) -> None:
    items = (
        ("Clean", counts.get("clean", 0), CLEAN),
        ("Weather", counts.get("weather", 0), WEATHER),
        ("Hardware", counts.get("hardware", 0), HARDWARE),
        ("Unconfirmed", counts.get("unconfirmed", 0), SLATE),
        ("Warming", counts.get("warming", 0), WARMING),
        ("Feed gap", counts.get("feedgap", 0), FEEDGAP),
        ("Waiting", counts.get("idle", 0), SLATE),
    )
    cells = "".join(
        f'<div class="sg-kpi" style="border-top-color:{color}">'
        f'<div class="sg-kpi-label">{label}</div>'
        f'<div class="sg-kpi-value" style="color:{color}">{value}</div></div>'
        for label, value, color in items
    )
    st.markdown(f'<div class="sg-kpis">{cells}</div>', unsafe_allow_html=True)


def legend() -> None:
    st.markdown(
        f"""<div class="sg-legend">
        <span><i class="sg-dot" style="background:{CLEAN}"></i> Clean</span>
        <span><i class="sg-dot" style="background:{WEATHER}"></i> Genuine weather</span>
        <span><i class="sg-dot" style="background:{HARDWARE}"></i> Hardware</span>
        <span><i class="sg-dot" style="background:{SLATE}"></i> Unconfirmed</span>
        <span><i class="sg-dot" style="background:{WARMING}"></i> Warming up</span>
        <span><i class="sg-dot" style="background:{FEEDGAP}"></i> Feed gap</span>
        </div>""",
        unsafe_allow_html=True,
    )


def offline_help(error: str) -> None:
    st.error(error)
    st.code(
        "python scripts/run_api.py\npython scripts/run_dashboard.py",
        language="text",
    )


def station_options(catalog: list[dict[str, Any]]) -> dict[str, str]:
    return {
        row["station_id"]: f"{short_name(row['name'])}  ·  {row['station_id']}"
        for row in catalog
    }


def fmt_value(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)
