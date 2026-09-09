"""Shared session, client, header, KPIs, offline help."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from api import SkyGuardApiError, SkyGuardClient
from status import short_name
from theme import CLEAN, HARDWARE, SLATE, WEATHER, CSS

_PAGES: dict[str, Any] = {}
_ASSETS = Path(__file__).resolve().parent / "assets"
_WORDMARK = _ASSETS / "skyguard-wordmark.svg"
_MARK = _ASSETS / "skyguard-mark.svg"

PALAM = "42181"
SAFDARJUNG = "42182"
PALAM_BUDDY = "42139"
SANTACRUZ = "43003"
DEFAULT_VIEW = [PALAM, SAFDARJUNG, PALAM_BUDDY, SANTACRUZ]

HERO_STORM = {"target": "neighborhood", "station_id": PALAM, "kind": "GENUINE_WEATHER"}
HERO_SPIKE = {"target": "station", "station_id": PALAM, "kind": "SPIKE", "channel": "temp_c"}


def inject_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    if _WORDMARK.exists():
        st.logo(str(_WORDMARK), icon_image=str(_MARK) if _MARK.exists() else None, size="large")


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
        st.markdown('<div class="sg-nav-section">Operations</div>', unsafe_allow_html=True)
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
            151-station catalog · buddy graph QC
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
        st.session_state.station_id = PALAM
    if "include_buddies" not in st.session_state:
        st.session_state.include_buddies = True
    if "flash" not in st.session_state:
        st.session_state.flash = None
    if "alerts_station_only" not in st.session_state:
        st.session_state.alerts_station_only = False
    if "alert_id" not in st.session_state:
        st.session_state.alert_id = None


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
        get_client().inject(body)
        flash(f"Armed {body['kind']}. Watch the next streamed hour.")
    except SkyGuardApiError as exc:
        flash(str(exc), kind="bad")


def fire_reset() -> None:
    try:
        get_client().reset()
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


def sync_stream_filter() -> None:
    view_ids = list(st.session_state.get("view_ids") or DEFAULT_VIEW)
    include = bool(st.session_state.get("include_buddies", True))
    try:
        get_client().set_stream_filter(view_ids, include)
    except SkyGuardApiError as exc:
        flash(str(exc), kind="bad")


def page_header(title: str, subtitle: str, health: dict[str, Any] | None = None) -> None:
    left, right = st.columns([3, 2])
    with left:
        st.markdown('<div class="sg-kicker">SkyGuard · live QC</div>', unsafe_allow_html=True)
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
        st.markdown(f'<div class="sg-health">{"".join(chips)}</div>', unsafe_allow_html=True)


def kpi_strip(counts: dict[str, int]) -> None:
    items = (
        ("Clean", counts.get("clean", 0), CLEAN),
        ("Weather", counts.get("weather", 0), WEATHER),
        ("Hardware", counts.get("hardware", 0), HARDWARE),
        ("Unconfirmed", counts.get("unconfirmed", 0), SLATE),
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
        </div>""",
        unsafe_allow_html=True,
    )


def offline_help(error: str) -> None:
    st.error(error)
    st.code(
        "python scripts/run_api.py\n"
        "python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 "
        "--start 2024-07-01T00:00:00Z --stations 42181 --with-buddies\n"
        "python scripts/run_dashboard.py",
        language="text",
    )


def station_options(catalog: list[dict[str, Any]]) -> dict[str, str]:
    return {
        row["station_id"]: f"{short_name(row['name'])}  ·  {row['station_id']}" for row in catalog
    }


def view_picker(catalog: list[dict[str, Any]]) -> None:
    options = station_options(catalog)
    known = [sid for sid in st.session_state.view_ids if sid in options]
    if known != st.session_state.view_ids:
        st.session_state.view_ids = known or list(DEFAULT_VIEW)
    st.multiselect(
        "View set",
        options=list(options.keys()),
        format_func=lambda sid: options.get(sid, sid),
        key="view_ids",
        help="Charts and the map show only these stations. Ingest still adds 1-hop buddies when enabled.",
        on_change=sync_stream_filter,
    )
    st.checkbox(
        "Include 1-hop buddies in ingest",
        key="include_buddies",
        help="Leave on so Tier 3 can still run. Turning this off lands hours as UNCONFIRMED_ANOMALY.",
        on_change=sync_stream_filter,
    )
    st.markdown(
        '<p class="sg-caption">Map and charts show this handful of stations. '
        "Neighbors still stream in the background so buddy QC can run. "
        "A CLI <code>--stations</code> streamer overrides this filter.</p>",
        unsafe_allow_html=True,
    )


def fmt_value(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)
