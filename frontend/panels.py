"""HTML fragments for Station and Control. Strings only — no Streamlit."""

from __future__ import annotations

from html import escape
from typing import Any

from chrome import fmt_value
from status import (
    CHANNEL_WORD,
    LABEL_TEXT,
    PIPELINE_LABEL,
    alert_kind,
    alert_status_label,
    feed_gap,
    feed_gap_label,
    health_color,
    is_feed_gap,
    is_warming,
    latest_payload,
    marker_color,
    pipeline_label,
    short_name,
    status_label,
    verdict_kind,
    verdict_kind_from_key,
)
from theme import CLEAN, FEEDGAP, HARDWARE, SLATE, WARMING, WEATHER

WINDOW_HOURS = 24

CHANNELS = (
    ("temp_c", "temp_observed", "temp_imputed", "Temperature", "°C"),
    ("pres_hpa", "pres_observed", "pres_imputed", "Pressure", "hPa"),
    ("rhum_pct", "rhum_observed", "rhum_imputed", "Humidity", "%"),
)

KIND_COLOR = {
    "clean": CLEAN,
    "weather": WEATHER,
    "hardware": HARDWARE,
    "unknown": SLATE,
    "warming": WARMING,
    "feedgap": FEEDGAP,
    "idle": SLATE,
}

STORIES: tuple[dict[str, str], ...] = (
    {
        "id": "clean",
        "title": "Clean hour",
        "short": "Clean",
        "kind": "clean",
        "claim": "A normal Mumbai hour should stay trusted.",
        "mutation": "None. The fixture hour is ingested as recorded.",
        "stations": "Santa Cruz, Colaba, Juhu, Alibag, Safdarjung",
        "look_for": "CLEAN on the demo set. No dashed correction. No 90% band.",
        "health": "Unchanged.",
    },
    {
        "id": "hardware",
        "title": "55 °C at Santa Cruz",
        "short": "Lone 55 °C",
        "kind": "hardware",
        "claim": "A lone broken sensor is not a heatwave.",
        "mutation": "Santa Cruz only → 55 °C / 95% / 980 hPa.",
        "stations": "Mumbai four ingested. Only Santa Cruz is mutated.",
        "look_for": "HARDWARE on Santa Cruz. Neighbors stay clean. Dashed correction and band on temperature.",
        "health": "May drop. A weather hour would not.",
    },
    {
        "id": "weather",
        "title": "+8 °C across Mumbai",
        "short": "Mumbai +8 °C",
        "kind": "weather",
        "claim": "The same heat on neighbors is genuine weather.",
        "mutation": "+8 °C on Santa Cruz, Colaba, and Juhu. Alibag stays on the fixture hour.",
        "stations": "Mumbai four ingested. Three stations share the rise.",
        "look_for": "GENUINE WEATHER. No band. Neighbors agree.",
        "health": "Unchanged. Weather never counts against the sensor.",
    },
    {
        "id": "freeze",
        "title": "12-hour freeze",
        "short": "Freeze",
        "kind": "hardware",
        "claim": "A stuck temperature is a sensor fault, not still air.",
        "mutation": "Santa Cruz temperature held for 12 hours at the fixture’s last value.",
        "stations": "Santa Cruz only.",
        "look_for": "HARDWARE or PHYSICAL FAULT. Correction appears if the hour is distrusted.",
        "health": "May drop.",
    },
    {
        "id": "comms",
        "title": "Missing temperature",
        "short": "Missing T",
        "kind": "hardware",
        "claim": "A dropped channel is a comms gap, not a calm hour.",
        "mutation": "Santa Cruz temperature is null on the last hour.",
        "stations": "Santa Cruz only.",
        "look_for": "A missing T reading and a hardware / comms label.",
        "health": "May drop.",
    },
)


CUSTOM_EVENTS: tuple[dict[str, Any], ...] = (
    {
        "id": "SPIKE",
        "title": "Spike",
        "kind": "hardware",
        "target": "station",
        "needs_channel": True,
        "default_hours": 1,
        "claim": "One channel jumps on one station. Neighbors stay on the real hour.",
        "look_for": "HARDWARE on the selected station if neighbors disagree. Band if distrusted.",
        "health": "May drop.",
    },
    {
        "id": "FREEZE",
        "title": "Freeze",
        "kind": "hardware",
        "target": "station",
        "needs_channel": True,
        "default_hours": 12,
        "claim": "A stuck channel is a sensor fault, not still air.",
        "look_for": "HARDWARE or PHYSICAL FAULT on the selected station.",
        "health": "May drop.",
    },
    {
        "id": "DRIFT",
        "title": "Drift",
        "kind": "hardware",
        "target": "station",
        "needs_channel": True,
        "default_hours": 48,
        "claim": "A slow bias accumulates. The raw line stays; QC should distrust it.",
        "look_for": "HARDWARE after the window sees the slope. Band if distrusted.",
        "health": "May drop.",
    },
    {
        "id": "COMM_ERROR",
        "title": "Missing packet",
        "kind": "hardware",
        "target": "station",
        "needs_channel": False,
        "default_hours": 1,
        "claim": "A dropped channel is a comms gap, not a calm hour.",
        "look_for": "A null reading and a hardware / comms label.",
        "health": "May drop.",
    },
    {
        "id": "GENUINE_WEATHER",
        "title": "Neighborhood weather",
        "kind": "weather",
        "target": "neighborhood",
        "needs_channel": False,
        "default_hours": 3,
        "claim": "The same shock on a station and its buddies is weather, not a lone fault.",
        "look_for": "GENUINE WEATHER. No band. Health unchanged.",
        "health": "Unchanged.",
    },
)

CHANNEL_CHOICES = (
    ("temp_c", "Temperature"),
    ("pres_hpa", "Pressure"),
    ("rhum_pct", "Humidity"),
)


def story_spec(story_id: str) -> dict[str, str]:
    for row in STORIES:
        if row["id"] == story_id:
            return row
    return STORIES[1]


def event_spec(kind: str) -> dict[str, Any]:
    for row in CUSTOM_EVENTS:
        if row["id"] == kind:
            return row
    return CUSTOM_EVENTS[0]


def inject_targets(station: dict[str, Any] | None, kind: str) -> list[str]:
    spec = event_spec(kind)
    if not station:
        return []
    sid = str(station["station_id"])
    if spec["target"] == "neighborhood":
        buddies = [str(buddy) for buddy in (station.get("buddy_ids") or []) if buddy]
        return [sid, *[buddy for buddy in buddies if buddy != sid]]
    return [sid]


def build_inject_body(
    *,
    kind: str,
    station_id: str,
    channel: str | None,
    duration_hours: int,
) -> dict[str, Any]:
    spec = event_spec(kind)
    hours = max(1, int(duration_hours))
    body: dict[str, Any] = {
        "target": spec["target"],
        "station_id": station_id,
        "kind": spec["id"],
        "duration_hours": hours,
    }
    if spec["needs_channel"]:
        allowed = {key for key, _label in CHANNEL_CHOICES}
        body["channel"] = channel if channel in allowed else "temp_c"
    return body


def event_preview_html(
    spec: dict[str, Any],
    station: dict[str, Any] | None,
    names: dict[str, str],
    channel: str | None,
    hours: int,
) -> str:
    color = KIND_COLOR.get(spec["kind"], SLATE)
    sid = "" if not station else str(station["station_id"])
    name = "—" if not station else names.get(sid, sid)
    targets = inject_targets(station, spec["id"])
    who = ", ".join(escape(names.get(tid, tid)) for tid in targets) or "—"
    channel_label = dict(CHANNEL_CHOICES).get(channel or "", "Temperature")
    mutation = (
        f"{escape(spec['title'])} on {escape(name)} for {hours} hour{'s' if hours != 1 else ''}."
    )
    if spec["needs_channel"]:
        mutation = f"{escape(channel_label)} {mutation}"
    isolate_note = ""
    if spec["target"] == "neighborhood" and station and station.get("isolate"):
        isolate_note = (
            "<div><dt>Note</dt><dd>This site is an isolate. Weather versus hardware cannot be called here.</dd></div>"
        )
    return (
        f'<div class="sg-preview" style="border-left-color:{color}">'
        f'<div class="sg-verdict-kicker">Custom event · {escape(spec["title"])}</div>'
        f'<div class="sg-verdict-text">{escape(spec["claim"])}</div>'
        f'<dl class="sg-preview-dl">'
        f"<div><dt>Mutation</dt><dd>{mutation} Armed on the next ingested hour — not a replay.</dd></div>"
        f"<div><dt>Stations</dt><dd>{who}</dd></div>"
        f"<div><dt>Look for</dt><dd>{escape(spec['look_for'])}</dd></div>"
        f"<div><dt>Health</dt><dd>{escape(spec['health'])}</dd></div>"
        f"{isolate_note}</dl></div>"
    )


def overlay_cards_html(overlays: list[dict[str, Any]], names: dict[str, str]) -> str:
    if not overlays:
        return (
            '<div class="sg-card"><div class="sg-verdict-kicker">Armed overlays</div>'
            '<p class="sg-caption" style="margin:0.4rem 0 0 0">'
            "None armed. A custom event waits for the next live or streamed hour. "
            "Mumbai replay scores immediately and clears its own arm."
            "</p></div>"
        )
    cards: list[str] = []
    for row in overlays:
        kind = str(row.get("kind") or "")
        spec = event_spec(kind)
        color = KIND_COLOR.get(spec["kind"], SLATE)
        ids = [str(sid) for sid in (row.get("station_ids") or [])]
        who = ", ".join(escape(names.get(sid, sid)) for sid in ids) or "—"
        channel = row.get("channel")
        extra = f" · {escape(dict(CHANNEL_CHOICES).get(str(channel), str(channel)))}" if channel else ""
        hours = row.get("remaining_hours", "—")
        cards.append(
            f'<div class="sg-result" style="border-left-color:{color}">'
            f'<div class="sg-result-top"><strong>{escape(spec["title"])}{extra}</strong>'
            f'<span class="sg-chip" style="color:{color};border-color:{color}">{escape(str(hours))}h left</span></div>'
            f'<div class="sg-result-meta">{who}</div></div>'
        )
    return (
        '<div class="sg-card"><div class="sg-verdict-kicker">Armed overlays</div>'
        f'<div class="sg-results">{"".join(cards)}</div></div>'
    )


def fmt_stamp(value: Any) -> str:
    if value is None or value == "":
        return "—"
    text = str(value).replace("T", " ").replace("+00:00", "Z")
    if text.endswith("Z"):
        text = text[:-1] + " UTC"
    if "." in text:
        head, tail = text.split(".", 1)
        tail = tail.split(" ", 1)
        text = head + (" " + tail[1] if len(tail) == 2 else "")
    return text


def channel_values(row: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if not row:
        return {}, {}
    observed = row.get("observed") if isinstance(row.get("observed"), dict) else None
    imputed = row.get("imputed") if isinstance(row.get("imputed"), dict) else None
    if observed is not None:
        return observed, imputed or {}
    humidity = row.get("rhum_observed")
    if humidity is None:
        humidity = row.get("rhum_pct")
    return (
        {
            "temp_c": row.get("temp_observed"),
            "pres_hpa": row.get("pres_observed"),
            "rhum_pct": humidity,
        },
        {
            "temp_c": row.get("temp_imputed"),
            "pres_hpa": row.get("pres_imputed"),
            "rhum_pct": row.get("rhum_imputed"),
        },
    )


def interval_pair(row: dict[str, Any] | None, channel: str) -> tuple[float, float] | None:
    if not row:
        return None
    interval = row.get("imputed_interval")
    if not isinstance(interval, dict):
        return None
    pair = interval.get(channel)
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return None
    try:
        return float(pair[0]), float(pair[1])
    except (TypeError, ValueError):
        return None


def hour_kind(row: dict[str, Any] | None) -> str:
    if not row:
        return "idle"
    if row.get("warming_up"):
        return "warming"
    if is_feed_gap(row):
        return "feedgap"
    return verdict_kind_from_key(row.get("label") or row.get("pipeline_status"), row.get("fault_type"))


def hour_caption(row: dict[str, Any] | None) -> str:
    if not row:
        return "Waiting"
    if row.get("warming_up"):
        return "Warming up"
    if is_feed_gap(row):
        return feed_gap_label(row)
    key = row.get("label") or row.get("pipeline_status")
    if key in LABEL_TEXT:
        return LABEL_TEXT[key]
    if key in PIPELINE_LABEL:
        return PIPELINE_LABEL[key]
    return pipeline_label(key)


def collected_hours(window: list[dict[str, Any]]) -> int:
    return min(len(window), WINDOW_HOURS)


def identity_html(
    station: dict[str, Any],
    tag: str,
    names: dict[str, str] | None = None,
) -> str:
    names = names or {}
    name = escape(short_name(station.get("name", station["station_id"])))
    sid = escape(str(station["station_id"]))
    aws = escape(str(station.get("aws_name") or "—"))
    aws_id = escape(str(station.get("aws_id") or "—"))
    elevation = station.get("elevation_m")
    elev = f"{fmt_value(elevation, 0)} m" if isinstance(elevation, (int, float)) else "—"
    lat = station.get("latitude")
    lon = station.get("longitude")
    coords = "—"
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        coords = f"{lat:.2f}°N  {lon:.2f}°E"
    isolate = bool(station.get("isolate"))
    buddies = station.get("buddy_ids") or []
    if isolate:
        relation = "Isolate · no buddies in the live 48"
    elif buddies:
        labels = ", ".join(escape(names.get(bid, bid)) for bid in buddies)
        relation = f"{len(buddies)} buddies · {labels}"
    else:
        relation = "No buddy list"
    return (
        f'<div class="sg-identity">'
        f'<div><div class="sg-identity-name">{name}</div>'
        f'<div class="sg-identity-meta">{sid} · AWS {aws} · {aws_id} · {elev} · {coords}</div>'
        f'<div class="sg-identity-meta">{relation}</div></div>'
        f'<div class="sg-identity-tag">{escape(tag)}</div>'
        f"</div>"
    )


def warmup_html(collected: int, stamp: str) -> str:
    collected = max(0, min(int(collected), WINDOW_HOURS))
    remaining = WINDOW_HOURS - collected
    width = (collected / WINDOW_HOURS) * 100
    dots = "".join(
        f'<i class="{"sg-dot-on" if index < collected else "sg-dot-off"}"></i>'
        for index in range(WINDOW_HOURS)
    )
    when = f" Latest hour {escape(stamp)}." if stamp and stamp != "—" else ""
    return (
        f'<div class="sg-warmup">'
        f'<div class="sg-warmup-head"><span>Collecting the 24-hour window</span>'
        f'<span class="sg-warmup-count">{collected} / {WINDOW_HOURS}</span></div>'
        f'<div class="sg-bar"><i style="width:{width:.1f}%;background:{WARMING}"></i></div>'
        f'<div class="sg-window">{dots}</div>'
        f'<p class="sg-caption" style="margin:0.55rem 0 0 0">'
        f"Raw T / P / H are stored. v2 does not score until hour 24. "
        f"{remaining} hour{'s' if remaining != 1 else ''} remaining.{when}"
        f"</p></div>"
    )


def readings_html(
    row: dict[str, Any] | None,
    *,
    warming: bool = False,
) -> str:
    observed, imputed = channel_values(row)
    tiles: list[str] = []
    for public, _obs_key, _imp_key, label, unit in CHANNELS:
        raw = observed.get(public)
        pred = imputed.get(public)
        band = interval_pair(row, public)
        show_pred = band is not None and not warming
        value = fmt_value(raw)
        missing = raw is None
        if missing and public in feed_gap(row):
            sub = "Not sent by IMD this hour · feed gap, not a sensor fault"
        elif missing:
            sub = "Channel missing this hour"
        elif warming:
            sub = "Stored raw · no predicted overlay until QC"
        else:
            sub = "Observed · raw never overwritten"
        extra = ""
        if show_pred:
            delta = ""
            if isinstance(raw, (int, float)) and isinstance(pred, (int, float)):
                sign = "+" if pred - raw > 0 else ""
                delta = f" · Δ {sign}{fmt_value(pred - raw)}"
            lo_hi = ""
            if band is not None:
                lo_hi = f" · band {fmt_value(band[0])}–{fmt_value(band[1])}"
            extra = (
                f'<div class="sg-reading-pred">Predicted {fmt_value(pred)} {escape(unit)}'
                f"{escape(delta)}{escape(lo_hi)}</div>"
            )
        tiles.append(
            f'<div class="sg-reading{" sg-reading-gap" if missing else ""}">'
            f'<div class="sg-reading-label">{escape(label)}</div>'
            f'<div class="sg-reading-value">{escape(value)}<span>{escape(unit)}</span></div>'
            f'<div class="sg-reading-sub">{escape(sub)}</div>{extra}</div>'
        )
    return f'<div class="sg-readings">{"".join(tiles)}</div>'


def health_html(station: dict[str, Any]) -> str:
    score = station.get("health_score")
    status = station.get("status") or "—"
    color = health_color(status if isinstance(score, (int, float)) else None)
    width = 0.0
    shown = "—"
    if isinstance(score, (int, float)):
        width = max(0.0, min(float(score), 100.0))
        shown = f"{score:.0f}"
    return (
        f'<div class="sg-meter">'
        f'<div class="sg-meter-head"><span>7-day health</span>'
        f'<span style="color:{color}">{escape(shown)} · {escape(str(status))}</span></div>'
        f'<div class="sg-bar"><i style="width:{width:.1f}%;background:{color}"></i></div>'
        f'<p class="sg-caption" style="margin:0.45rem 0 0 0">'
        f"Sensor flag rate over 168 hours. Genuine weather does not count."
        f"</p></div>"
    )


def buddy_html(
    station: dict[str, Any],
    names: dict[str, str],
    hour: dict[str, Any] | None = None,
) -> str:
    if station.get("isolate"):
        return (
            '<div class="sg-meter"><div class="sg-meter-head"><span>Buddy check</span>'
            '<span>Isolate</span></div>'
            '<p class="sg-caption" style="margin:0.45rem 0 0 0">'
            "No buddies inside the live 48. Weather versus hardware cannot be called here."
            "</p></div>"
        )
    buddies = station.get("buddy_ids") or []
    corr = hour.get("tier3_corr") if hour and isinstance(hour.get("tier3_corr"), dict) else {}
    mix = hour.get("tier3_mix") if hour and isinstance(hour.get("tier3_mix"), dict) else {}
    method = (hour or {}).get("tier3_method")
    chips: list[str] = []
    for buddy_id in buddies:
        label = escape(names.get(buddy_id, buddy_id))
        score = corr.get(buddy_id)
        extra = f" · r {fmt_value(score, 2)}" if score is not None else ""
        chips.append(
            f'<span class="sg-buddy">{label}<em>{escape(str(buddy_id))}{escape(extra)}</em></span>'
        )
    if not chips:
        chips.append('<span class="sg-caption">No 1-hop buddies listed.</span>')
    blend = ""
    if mix:
        blend = (
            f' Blend T {fmt_value(mix.get("temp_c"))} °C · '
            f'P {fmt_value(mix.get("pres_hpa"))} hPa · '
            f'H {fmt_value(mix.get("rhum_pct"))}%.'
        )
    method_line = f" {escape(str(method))}." if method else ""
    return (
        f'<div class="sg-meter"><div class="sg-meter-head"><span>1-hop buddies</span>'
        f"<span>{len(buddies)}</span></div>"
        f'<div class="sg-buddy-row">{"".join(chips)}</div>'
        f'<p class="sg-caption" style="margin:0.45rem 0 0 0">'
        f"QC needs two usable same-hour neighbors.{method_line}{escape(blend)}"
        f"</p></div>"
    )


def poll_html(imd: dict[str, Any], n_stations: int = 48) -> str:
    matched = imd.get("matched")
    last_success = fmt_stamp(imd.get("last_success"))
    last_error = imd.get("last_error")
    limited_until = imd.get("rate_limited_until")
    if limited_until:
        kind = "bad"
        state = f"IMD rate limit · paused until {fmt_stamp(limited_until)}"
    elif last_error:
        kind = "bad"
        state = "Poll failed"
    elif imd.get("last_success"):
        kind = "ok"
        state = "Poll ok"
    else:
        kind = "idle"
        state = "Waiting for first poll"
    count = matched if isinstance(matched, int) else "—"
    error = f'<div class="sg-poll-error">{escape(str(last_error))}</div>' if last_error else ""
    gap = feed_gap_sentence(imd)
    gap_line = f'<div class="sg-poll-meta" style="color:{FEEDGAP}">{escape(gap)}</div>' if gap else ""
    return (
        f'<div class="sg-poll sg-poll-{kind}">'
        f'<div class="sg-poll-state">{escape(state)}</div>'
        f'<div class="sg-poll-meta">{escape(str(count))} of {n_stations} matched'
        f" · last success {escape(last_success)}{escape(poll_budget_line(imd))}</div>{gap_line}{error}</div>"
    )


def webhook_html(webhook: dict[str, Any]) -> str:
    """One line under the poll strip: where pages go and whether the last one landed."""
    if not webhook.get("configured"):
        return (
            '<div class="sg-poll sg-poll-idle"><div class="sg-poll-state">Paging off</div>'
            '<div class="sg-poll-meta">Set SKYGUARD_WEBHOOK_URL to POST DEGRADED / CRITICAL transitions '
            "and HIGH hardware alerts to a pager, Slack, or a ticketing hook. Weather never pages.</div></div>"
        )
    sent = webhook.get("sent") or 0
    failed = webhook.get("failed") or 0
    error = webhook.get("last_error")
    kind = "bad" if error else "ok"
    state = "Paging on" if not error else "Paging failed"
    bits = [f"{sent} sent", f"{failed} failed"]
    if webhook.get("last_sent"):
        bits.append(f"last {fmt_stamp(webhook['last_sent'])}")
    if webhook.get("last_event"):
        bits.append(str(webhook["last_event"]).replace("_", " "))
    error_html = f'<div class="sg-poll-error">{escape(str(error))}</div>' if error else ""
    return (
        f'<div class="sg-poll sg-poll-{kind}"><div class="sg-poll-state">{state}</div>'
        f'<div class="sg-poll-meta">{escape(" · ".join(bits))}</div>{error_html}</div>'
    )


def poll_budget_line(imd: dict[str, Any]) -> str:
    """` · next poll 13:20 UTC · 12 states` from /healthz.imd. Empty before the first cycle."""
    bits = []
    if imd.get("next_poll"):
        bits.append(f"next poll {fmt_stamp(imd['next_poll'])}")
    states = imd.get("states_polled")
    if isinstance(states, int) and states:
        bits.append(f"{states} state{'s' if states != 1 else ''} called")
    return "".join(f" · {bit}" for bit in bits)


def feed_gap_sentence(imd: dict[str, Any]) -> str:
    """One line from /healthz.imd.feed_gap: which channels the feed dropped and on how many stations."""
    gap = imd.get("feed_gap")
    if not isinstance(gap, dict) or not gap:
        return ""
    matched = imd.get("matched")
    parts = []
    for channel, count in gap.items():
        word = CHANNEL_WORD.get(str(channel), str(channel))
        where = f"{count} of {matched}" if isinstance(matched, int) and matched else str(count)
        parts.append(f"{word} missing on {where} stations")
    return "Feed gap · " + "; ".join(parts)


def feed_gap_banner_html(imd: dict[str, Any]) -> str:
    sentence = feed_gap_sentence(imd)
    if not sentence:
        return ""
    return (
        '<div class="sg-feedgap"><span>'
        f"<b>{escape(sentence)}.</b> IMD did not send that channel in the last poll. "
        "Those hours are stored raw, are not scored, open no alert and do not lower "
        "7-day sensor health. This is the feed, not the sensors."
        "</span></div>"
    )


def story_preview_html(story_id: str) -> str:
    spec = story_spec(story_id)
    color = KIND_COLOR.get(spec["kind"], SLATE)
    return (
        f'<div class="sg-preview" style="border-left-color:{color}">'
        f'<div class="sg-verdict-kicker">Selected · {escape(spec["title"])}</div>'
        f'<div class="sg-verdict-text">{escape(spec["claim"])}</div>'
        f'<dl class="sg-preview-dl">'
        f"<div><dt>Mutation</dt><dd>{escape(spec['mutation'])}</dd></div>"
        f"<div><dt>Stations</dt><dd>{escape(spec['stations'])}</dd></div>"
        f"<div><dt>Look for</dt><dd>{escape(spec['look_for'])}</dd></div>"
        f"<div><dt>Health</dt><dd>{escape(spec['health'])}</dd></div>"
        f"</dl></div>"
    )


def split_lead_result(
    results: list[dict[str, Any]],
    lead_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Put the station the judge should read first. The rest stay a second block."""
    lead = [row for row in results if str(row.get("station_id")) == lead_id]
    rest = [row for row in results if str(row.get("station_id")) != lead_id]
    if not lead:
        return list(results), []
    return lead, rest


def result_cards_html(
    results: list[dict[str, Any]],
    names: dict[str, str],
    story_id: str | None = None,
    *,
    heading: str | None = None,
) -> str:
    spec = story_spec(story_id) if story_id else None
    if heading is None:
        heading = f"Last run · {spec['title']}" if spec else "Last run"
    cards: list[str] = []
    for row in results:
        sid = str(row.get("station_id", ""))
        name = escape(names.get(sid, sid))
        kind = hour_kind(row)
        color = KIND_COLOR.get(kind, SLATE)
        observed, imputed = channel_values(row)
        band = interval_pair(row, "temp_c")
        label = hour_caption(row)
        injected = row.get("demo_injected")
        inject_bit = f" · injected {escape(str(injected))}" if injected else ""
        pred = ""
        if band is not None:
            pred = (
                f' · predicted {fmt_value(imputed.get("temp_c"))} °C'
                f" · band {fmt_value(band[0])}–{fmt_value(band[1])}"
            )
        health = row.get("health_score")
        health_bit = f" · health {fmt_value(health, 0)}" if health is not None else ""
        reason = row.get("explainability_text") or ""
        reason_html = f'<div class="sg-result-reason">{escape(str(reason))}</div>' if reason else ""
        cards.append(
            f'<div class="sg-result" style="border-left-color:{color}">'
            f'<div class="sg-result-top"><strong>{name}</strong>'
            f'<span class="sg-chip" style="color:{color};border-color:{color}">{escape(label)}</span></div>'
            f'<div class="sg-result-meta">{escape(sid)} · '
            f'T {fmt_value(observed.get("temp_c"))} °C · '
            f'P {fmt_value(observed.get("pres_hpa"))} hPa · '
            f'H {fmt_value(observed.get("rhum_pct"))}%'
            f"{pred}{health_bit}{inject_bit}</div>{reason_html}</div>"
        )
    if not cards:
        return (
            f'<div class="sg-card"><div class="sg-verdict-kicker">{escape(heading)}</div>'
            '<p class="sg-caption" style="margin:0.4rem 0 0 0">No scored rows came back.</p></div>'
        )
    return (
        f'<div class="sg-card"><div class="sg-verdict-kicker">{escape(heading)}</div>'
        f'<div class="sg-results">{"".join(cards)}</div></div>'
    )


def section_html(title: str, caption: str | None = None) -> str:
    extra = f'<p class="sg-caption" style="margin:0.25rem 0 0 0">{escape(caption)}</p>' if caption else ""
    return f'<div class="sg-section">{escape(title)}{extra}</div>'


FAULT_LABEL = {
    "SPIKE": "Spike",
    "FREEZE": "Freeze",
    "DRIFT": "Drift",
    "COMM_ERROR": "Missing packet",
    "COMMUNICATION": "Missing packet",
    "GENUINE_WEATHER": "Neighborhood weather",
    "STORM": "Neighborhood weather",
    "UNKNOWN": "Unconfirmed",
    "THERMO": "Thermo failure",
}

ALERT_FILTERS = (
    ("all", "All"),
    ("hardware", "Hardware"),
    ("weather", "Weather"),
    ("unknown", "Unconfirmed"),
)

ACK_FILTERS = (
    ("open", "Open"),
    ("acknowledged", "Acknowledged"),
    ("resolved", "Resolved"),
    ("all", "Everything"),
)

ACK_TEXT = {"open": "Open", "acknowledged": "Acknowledged", "resolved": "Resolved"}


def ack_state(row: dict[str, Any] | None) -> str:
    value = str((row or {}).get("ack_state") or "open")
    return value if value in ACK_TEXT else "open"


def ack_chip_html(row: dict[str, Any]) -> str:
    """Operator state on a card. Nothing for an open alert; who and when otherwise."""
    state = ack_state(row)
    if state == "open":
        return ""
    bits = [ACK_TEXT[state]]
    if row.get("ack_by"):
        bits.append(f"by {row['ack_by']}")
    if row.get("ack_at"):
        bits.append(fmt_stamp(row["ack_at"]))
    note = str(row.get("ack_note") or "").strip()
    text = " · ".join(bits) + (f" — {note}" if note else "")
    return f'<span class="sg-ack sg-ack-{state}">{escape(text)}</span>'


def ack_actions(row: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Buttons an operator sees for this state: (label, next state)."""
    state = ack_state(row)
    if state == "open":
        return [("Acknowledge", "acknowledged"), ("Resolve", "resolved")]
    if state == "acknowledged":
        return [("Resolve", "resolved"), ("Reopen", "open")]
    return [("Reopen", "open")]


def fault_label(fault_type: Any) -> str:
    if not fault_type:
        return "—"
    key = str(fault_type)
    return FAULT_LABEL.get(key, key.replace("_", " ").title())


def alert_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"hardware": 0, "weather": 0, "unknown": 0}
    for row in rows:
        kind = alert_kind(row)
        if kind in counts:
            counts[kind] += 1
        else:
            counts["unknown"] += 1
    return counts


def filter_alerts(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    if kind in {None, "", "all"}:
        return list(rows)
    return [row for row in rows if alert_kind(row) == kind]


def alerts_intro_html() -> str:
    return (
        '<div class="sg-card">'
        '<div class="sg-verdict-kicker">Why this page exists</div>'
        '<div class="sg-verdict-text">The QC inbox. Clean hours never appear here.</div>'
        '<p class="sg-caption" style="margin:0.45rem 0 0.75rem 0">'
        "Each row is one scored hour that was not trusted as clean. "
        "Inspect opens that hour on Station even if the live hour has already moved on."
        "</p>"
        '<div class="sg-alert-legend">'
        f'<div><span class="sg-chip" style="color:{HARDWARE};border-color:{HARDWARE}">Hardware</span>'
        "<p>Sensor or comms. Neighbors disagreed, or a physical rule failed. Health may drop.</p></div>"
        f'<div><span class="sg-chip" style="color:{WEATHER};border-color:{WEATHER}">Weather</span>'
        "<p>Extreme, but neighbors agreed. Amber, never rose. Health unchanged.</p></div>"
        f'<div><span class="sg-chip" style="color:{SLATE};border-color:{SLATE}">Unconfirmed</span>'
        "<p>Not enough same-hour buddies to call weather versus hardware.</p></div>"
        "</div></div>"
    )


def alerts_empty_html(*, filtered: bool) -> str:
    if filtered:
        body = "Nothing in this filter. Switch to All, or play a Mumbai story on Control."
    else:
        body = (
            "No scored exceptions yet. A live hour that fails QC will land here. "
            "Or play a Mumbai story on Control to produce one immediately."
        )
    return (
        '<div class="sg-card"><div class="sg-verdict-kicker">Inbox</div>'
        f'<p class="sg-caption" style="margin:0.4rem 0 0 0">{escape(body)}</p></div>'
    )


def alert_kpis_html(counts: dict[str, int], total: int) -> str:
    items = (
        ("Hardware", counts.get("hardware", 0), HARDWARE),
        ("Weather", counts.get("weather", 0), WEATHER),
        ("Unconfirmed", counts.get("unknown", 0), SLATE),
        ("In this feed", total, SLATE),
    )
    cells = "".join(
        f'<div class="sg-kpi" style="border-top-color:{color}">'
        f'<div class="sg-kpi-label">{label}</div>'
        f'<div class="sg-kpi-value" style="color:{color}">{value}</div></div>'
        for label, value, color in items
    )
    return f'<div class="sg-kpis sg-kpis-4">{cells}</div>'


def _contribution_line(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, label in (
        ("contribution_temp", "T"),
        ("contribution_pres", "P"),
        ("contribution_rhum", "H"),
    ):
        raw = row.get(key)
        if raw is None:
            continue
        try:
            parts.append(f"{label} {float(raw):.0f}%")
        except (TypeError, ValueError):
            continue
    if not parts:
        return ""
    return "Channel share · " + " · ".join(parts)


def alert_card_html(row: dict[str, Any], names: dict[str, str]) -> str:
    sid = str(row.get("station_id", ""))
    name = escape(names.get(sid, sid))
    kind = alert_kind(row)
    color = KIND_COLOR.get(kind, SLATE)
    title = escape(alert_status_label(row))
    fault = escape(fault_label(row.get("fault_type")))
    severity = escape(str(row.get("severity") or "—"))
    confidence = fmt_value(row.get("confidence_score"), 2)
    stamp = escape(fmt_stamp(row.get("timestamp")))
    reason = escape(str(row.get("explainability_text") or "No reason stored for this hour."))
    share = _contribution_line(row)
    share_html = f'<div class="sg-alert-share">{escape(share)}</div>' if share else ""
    health_note = ""
    if kind == "weather":
        health_note = '<div class="sg-alert-note">Neighbors agreed. This hour does not lower sensor health.</div>'
    elif kind == "unknown":
        health_note = '<div class="sg-alert-note">Honesty over a fake buddy call. Health may still drop.</div>'
    done = " sg-alert-done" if ack_state(row) == "resolved" else ""
    return (
        f'<div class="sg-alert{done}" style="border-left-color:{color}">'
        f'<div class="sg-alert-head"><div class="sg-alert-title">{title}</div>'
        f'<span class="sg-chip" style="color:{color};border-color:{color}">{severity}</span></div>'
        f'<div class="sg-alert-who">{name} · {escape(sid)}</div>'
        f'<div class="sg-alert-meta">{stamp} · {fault} · confidence {escape(confidence)}</div>'
        f'<div class="sg-alert-text">{reason}</div>{share_html}{health_note}{ack_chip_html(row)}</div>'
    )


PAGE_STATUSES = {"DEGRADED", "CRITICAL"}


def _health_score(station: dict[str, Any]) -> float:
    score = station.get("health_score")
    try:
        return float(score)
    except (TypeError, ValueError):
        return 100.0


def _latest_hardware_alert(
    alerts: list[dict[str, Any]], station_id: str
) -> dict[str, Any] | None:
    for row in alerts:
        if str(row.get("station_id")) != station_id:
            continue
        if alert_kind(row) == "hardware":
            return row
    return None


_CHANNEL_WORDS = (
    ("temp", "temperature"),
    ("rhum", "humidity"),
    ("pres", "pressure"),
)

_TIER_PREFIXES = (
    "tier 1 physical rule failed:",
    "tier 2 physical rule failed:",
    "tier 3 physical rule failed:",
)


def _reason_channels(text: str) -> list[str]:
    lower = text.lower()
    if "communication:" in lower:
        blob = lower.split("communication:", 1)[1]
        tokens = {part.strip() for part in blob.replace(";", ",").split(",") if part.strip()}
        return [label for key, label in _CHANNEL_WORDS if key in tokens]
    return [label for key, label in _CHANNEL_WORDS if key in lower]


def dispatch_reason(
    text: Any = None,
    fault_type: Any = None,
    hour_label: Any = None,
) -> str:
    """One line for the dispatch board. Never dump COMMUNICATION:temp,rhum."""
    raw = str(text or "").strip()
    fault = str(fault_type or "").strip()
    hour = str(hour_label or "").strip()
    blob = f"{raw} {fault}".upper()
    if "COMMUNICATION" in blob or "COMM_ERROR" in blob:
        channels = _reason_channels(raw)
        if channels:
            return "Missing packet · " + ", ".join(channels)
        return "Missing packet"
    if raw:
        cleaned = raw
        lowered = cleaned.lower()
        for prefix in _TIER_PREFIXES:
            if lowered.startswith(prefix):
                cleaned = cleaned[len(prefix) :].strip()
                break
        sentence = cleaned.split(".")[0].strip()
        if sentence:
            return sentence if len(sentence) <= 88 else sentence[:85].rstrip() + "…"
    return hour or "Needs a look"


def _dispatch_item(
    station: dict[str, Any],
    alerts: list[dict[str, Any]],
    rank: str,
) -> dict[str, Any]:
    sid = str(station["station_id"])
    matched = _latest_hardware_alert(alerts, sid)
    hour_label = status_label(station)
    raw = (matched or {}).get("explainability_text") or ""
    fault = (matched or {}).get("fault_type")
    return {
        "station_id": sid,
        "name": short_name(station.get("name", sid)),
        "health_score": _health_score(station),
        "status": station.get("status") or "HEALTHY",
        "hour_label": hour_label,
        "rank": rank,
        "fault_type": fault,
        "reason": dispatch_reason(raw, fault, hour_label),
        "alert_id": None if matched is None else matched.get("alert_id"),
        "ack_state": ack_state(matched) if matched is not None else None,
    }


def dispatch_lists(
    stations: list[dict[str, Any]],
    alerts: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Page = 7-day DEGRADED/CRITICAL. Watch = rose this hour while still HEALTHY."""
    feed = alerts or []
    page: list[dict[str, Any]] = []
    watch: list[dict[str, Any]] = []
    for station in stations:
        if is_warming(station) or not latest_payload(station):
            continue
        status = str(station.get("status") or "HEALTHY")
        if status in PAGE_STATUSES:
            page.append(_dispatch_item(station, feed, "page"))
            continue
        if verdict_kind(station) == "hardware" and status == "HEALTHY":
            watch.append(_dispatch_item(station, feed, "watch"))
    page.sort(key=lambda row: (0 if row["status"] == "CRITICAL" else 1, row["health_score"]))
    watch.sort(key=lambda row: row["health_score"])
    return {"page": page, "watch": watch}


def dispatch_row_html(row: dict[str, Any]) -> str:
    tone = "sg-dispatch-page" if row.get("rank") == "page" else "sg-dispatch-watch"
    name = escape(str(row.get("name") or row["station_id"]))
    reason = escape(str(row.get("reason") or dispatch_reason(hour_label=row.get("hour_label"))))
    health = fmt_value(row.get("health_score"), 0)
    status = escape(str(row.get("status") or "—"))
    ack = row.get("ack_state")
    ack_bit = f" · {escape(ACK_TEXT.get(str(ack), str(ack)).lower())}" if ack and ack != "open" else ""
    return (
        f'<div class="sg-dispatch-row">'
        f'<div class="sg-dispatch-name {tone}">{name}</div>'
        f'<div class="sg-dispatch-why">{reason}</div>'
        f'<div class="sg-dispatch-meta">7-day {escape(health)} · {status}{ack_bit}</div>'
        "</div>"
    )


def dispatch_panel_html(lists: dict[str, list[dict[str, Any]]]) -> str:
    page = lists.get("page") or []
    watch = lists.get("watch") or []
    if not page and not watch:
        return (
            '<div class="sg-dispatch-head">'
            '<div class="sg-verdict-kicker">Dispatch</div>'
            '<div class="sg-verdict-text">No station needs a technician.</div>'
            '<p class="sg-caption" style="margin:0.4rem 0 0 0">'
            "Weather hours never appear here. A lone spike stays on Watch until 7-day health drops."
            "</p></div>"
        )
    watch_bit = f" · {len(watch)} on watch" if watch else ""
    return (
        '<div class="sg-dispatch-head">'
        '<div class="sg-verdict-kicker">Dispatch</div>'
        f'<div class="sg-verdict-text">{len(page)} need a technician{watch_bit}</div>'
        '<p class="sg-caption" style="margin:0.4rem 0 0 0">'
        "Page follows the 7-day index. Watch is a hardware hour on a station that is still HEALTHY. "
        "Weather never appears here."
        "</p></div>"
    )


def network_intro_html() -> str:
    return (
        '<div class="sg-card sg-network-intro">'
        '<div class="sg-verdict-kicker">This hour on the live 48</div>'
        '<div class="sg-verdict-text">Neighbors that agree stay amber. A sensor that disagrees goes rose.</div>'
        '<p class="sg-caption" style="margin:0.4rem 0 0 0">'
        "Marker color is this hour’s label, not 7-day health. Warming up is not a fault. "
        "Safdarjung has no buddies in this set, so weather versus hardware cannot be called there."
        "</p>"
        f'<div class="sg-legend">'
        f'<span><i class="sg-dot" style="background:{CLEAN}"></i> Clean</span>'
        f'<span><i class="sg-dot" style="background:{WEATHER}"></i> Genuine weather</span>'
        f'<span><i class="sg-dot" style="background:{HARDWARE}"></i> Hardware</span>'
        f'<span><i class="sg-dot" style="background:{SLATE}"></i> Unconfirmed</span>'
        f'<span><i class="sg-dot" style="background:{WARMING}"></i> Warming up</span>'
        f"</div></div>"
    )


def reliability_intro_html() -> str:
    return (
        '<div class="sg-card">'
        '<div class="sg-verdict-kicker">Why this page exists</div>'
        '<div class="sg-verdict-text">Health says whether a sensor is trusted. Reliability says whether the station reports at all.</div>'
        '<p class="sg-caption" style="margin:0.45rem 0 0 0">'
        "Completeness is stored hours over the window. Flag rate is hardware plus unconfirmed over scored hours; "
        "weather never counts against a station. Feed-gap hours are the upstream feed, not the sensor. "
        "A station with fewer than two in-set buddies cannot get a buddy check, so its anomalies stay unconfirmed."
        "</p></div>"
    )


def reliability_kpis_html(network: dict[str, Any]) -> str:
    n = int(network.get("n_stations") or 0)
    items = (
        ("Mean completeness", f"{100 * float(network.get('mean_completeness') or 0):.0f}%", CLEAN),
        ("Stations ≥ 90% complete", f"{network.get('stations_complete', 0)} / {n}", CLEAN),
        ("Degraded or critical", str(network.get("stations_degraded", 0)), HARDWARE),
        ("Isolates (< 2 buddies)", f"{network.get('n_isolates', 0)} / {n}", SLATE),
        ("Feed-gap hours", str(network.get("feed_gap_hours", 0)), FEEDGAP),
    )
    cells = "".join(
        f'<div class="sg-kpi" style="border-top-color:{color}">'
        f'<div class="sg-kpi-label">{escape(label)}</div>'
        f'<div class="sg-kpi-value" style="color:{color};font-size:1.25rem">{escape(value)}</div></div>'
        for label, value, color in items
    )
    return f'<div class="sg-kpis sg-kpis-5">{cells}</div>'


def reliability_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flat rows for st.dataframe. Percentages as 0–1 floats for ProgressColumn."""
    table: list[dict[str, Any]] = []
    for row in rows:
        table.append(
            {
                "Station": short_name(str(row.get("name") or row.get("station_id"))),
                "ID": str(row.get("station_id")),
                "Completeness": float(row.get("completeness") or 0.0),
                "Flag rate": row.get("flag_rate"),
                "Stored": int(row.get("hours_stored") or 0),
                "Scored": int(row.get("hours_scored") or 0),
                "Hardware": int(row.get("hardware") or 0),
                "Weather": int(row.get("weather") or 0),
                "Unconfirmed": int(row.get("unconfirmed") or 0),
                "Feed gap": int(row.get("feed_gap") or 0),
                "Buddies": int(row.get("buddy_count") or 0),
                "7-day health": float(row.get("health_score") or 0.0),
                "Status": str(row.get("status") or ""),
                "Last hour": fmt_stamp(row.get("last_hour")) if row.get("last_hour") else "—",
            }
        )
    return table


def map_head_html(count: int, selected_name: str | None) -> str:
    focus = escape(selected_name) if selected_name else "Mumbai + Safdarjung"
    return (
        f'<div class="sg-map-head"><strong>India · this hour</strong>'
        f"<span>{count} stations · selected {focus}</span></div>"
    )


def roster_row_html(station: dict[str, Any], *, selected: bool = False) -> str:
    sid = str(station["station_id"])
    name = escape(short_name(station.get("name", sid)))
    label = escape(status_label(station))
    color = marker_color(station)
    health = fmt_value(station.get("health_score"), 0)
    klass = "sg-roster-row sg-roster-row-on" if selected else "sg-roster-row"
    return (
        f'<div class="{klass}">'
        f'<i class="sg-dot" style="background:{color};width:0.7rem;height:0.7rem"></i>'
        f"<div><div class=\"sg-roster-name\">{name}</div>"
        f'<div class="sg-roster-meta">{escape(sid)} · health {escape(health)}</div></div>'
        f'<span class="sg-roster-label" style="color:{color}">{label}</span></div>'
    )

