"""Evidence for one scored hour: the three-tier trace, neighbor agreement, verdict ribbon, exports.

Strings and plain data only — no Streamlit. Everything here is derived from fields that
already exist on GET /stations/{id}/telemetry, GET /alerts, GET /healthz, and
GET /stations/{id}/timing. Nothing is invented; the agree bands are the v2 constants
(AGREE_TEMP / AGREE_RHUM / AGREE_PRES in v2/config.py) shown as display context.
"""

from __future__ import annotations

import csv
import io
from html import escape
from typing import Any

from chrome import fmt_value
from panels import CHANNELS, channel_values, fmt_stamp, hour_caption, hour_kind, interval_pair
from status import short_name, stamp_key
from theme import CLEAN, FEEDGAP, HARDWARE, LINE, SLATE, WARMING, WEATHER

# v2 Tier 3 agreement bands (|observed − neighbor blend|). Display context, not an API field.
AGREE_BAND = {"temp_c": 3.0, "rhum_pct": 8.0, "pres_hpa": 2.0}

RIBBON_HOURS = 24

KIND_COLOR = {
    "clean": CLEAN,
    "weather": WEATHER,
    "hardware": HARDWARE,
    "unknown": SLATE,
    "warming": WARMING,
    "feedgap": FEEDGAP,
    "idle": LINE,
}

_STATE_COLOR = {
    "passed": CLEAN,
    "flagged": WEATHER,
    "failed": HARDWARE,
    "agree": WEATHER,
    "disagree": HARDWARE,
    "skipped": SLATE,
    "not_run": SLATE,
}

_STATE_TEXT = {
    "passed": "Passed",
    "flagged": "Flagged",
    "failed": "Failed",
    "agree": "Neighbors agree",
    "disagree": "Neighbors disagree",
    "skipped": "Skipped",
    "not_run": "Not run",
}


def _label_of(hour: dict[str, Any] | None, alert: dict[str, Any] | None) -> str | None:
    for row in (hour, alert):
        if row and row.get("label"):
            return str(row["label"])
    for row in (hour, alert):
        if row and row.get("pipeline_status"):
            return str(row["pipeline_status"])
    return None


def _missing_channels(observed: dict[str, Any]) -> list[str]:
    names = {"temp_c": "temperature", "pres_hpa": "pressure", "rhum_pct": "humidity"}
    return [names[key] for key in ("temp_c", "pres_hpa", "rhum_pct") if observed.get(key) is None]


CORROBORATED_MARK = "Corroborated by neighbors"


def is_corroborated_clean(hour: dict[str, Any] | None) -> bool:
    """A CLEAN hour the LSTM flagged but calm, agreeing neighbours vouched for (v2 shared-shock rule)."""
    if not hour or hour.get("label") != "CLEAN":
        return False
    return CORROBORATED_MARK in str(hour.get("explainability_text") or "")


def decision_steps(
    hour: dict[str, Any] | None,
    alert: dict[str, Any] | None,
    threshold: float | None,
) -> list[dict[str, Any]]:
    """Three rows: physics, LSTM, buddy check. Each has state, headline, detail."""
    hour = hour or {}
    label = _label_of(hour, alert)
    observed, _imputed = channel_values(hour)
    fault = str((alert or {}).get("fault_type") or "")

    # Tier 1 — physical rules
    thermo = hour.get("thermo") if isinstance(hour.get("thermo"), dict) else {}
    missing = _missing_channels(observed) if observed else []
    if label == "PHYSICAL_FAULT":
        state = "failed"
        if missing:
            head = "Missing packet · " + ", ".join(missing)
        elif thermo and thermo.get("passed") is False:
            head = "Dew point above air temperature"
        elif fault == "FREEZE":
            head = "Channel frozen for 12 hours"
        elif fault:
            head = f"Hard rule failed · {fault.replace('_', ' ').title()}"
        else:
            head = "Hard physical rule failed"
        detail = "No neighbor needed. Confidence 1.0. Health counts this hour."
    else:
        state = "passed"
        head = "Range, step, freeze, and dew point all plausible"
        detail = "Nothing physically impossible about this hour on its own."
    if thermo and thermo.get("dewpoint_c") is not None:
        detail += (
            f" Dew point {fmt_value(thermo.get('dewpoint_c'))} °C · "
            f"Td−T {fmt_value(thermo.get('td_minus_t'))} °C."
        )
    tier1 = {"n": 1, "title": "Physical rules", "state": state, "head": head, "detail": detail}

    # Tier 2 — LSTM reconstruction score
    score = hour.get("tier2_score")
    corroborated = is_corroborated_clean(hour)
    ratio = None
    if isinstance(score, (int, float)) and isinstance(threshold, (int, float)) and threshold > 0:
        ratio = float(score) / float(threshold)
    if score is None:
        state = "not_run"
        head = "No reconstruction score stored"
        detail = "The window was not scored, or this hour predates the v2 path."
    elif label == "CLEAN" and corroborated:
        state = "flagged"
        head = f"Score {float(score):.4f} is over the threshold"
        detail = "Unusual for this station’s own climate, but see the buddy check below."
    elif label == "CLEAN":
        state = "passed"
        head = f"Score {float(score):.4f} is under the frozen 2023 threshold"
        detail = "The last 24 hours look like this station’s own climate."
    else:
        state = "flagged"
        head = f"Score {float(score):.4f} is over the threshold"
        detail = "The window does not look like this station’s climate. Unusual is not yet broken."
    if ratio is not None:
        detail += f" That is {ratio:.1f}× the operating score {float(threshold):.6f}."
    tier2 = {
        "n": 2,
        "title": "LSTM autoencoder",
        "state": state,
        "head": head,
        "detail": detail,
        "ratio": ratio,
    }

    # Tier 3 — spatial consensus
    corr = hour.get("tier3_corr") if isinstance(hour.get("tier3_corr"), dict) else {}
    method = hour.get("tier3_method")
    n_used = len(corr)
    method_bit = f" · {method}" if method else ""
    if label == "GENUINE_WEATHER_EVENT":
        state, head = "agree", f"{n_used or 'Two or more'} neighbors share the shock{method_bit}"
        detail = "Correlation-weighted neighbors moved with this station. Weather, not a sensor. Health unchanged."
    elif label == "HARDWARE_ANOMALY" and fault == "DRIFT":
        drift = hour.get("tier3_drift") if isinstance(hour.get("tier3_drift"), dict) else {}
        hours = drift.get("hours")
        last = drift.get("last")
        extra = ""
        if hours and last is not None:
            extra = f" Residual {last:+.1f} over {hours} h."
        state, head = "disagree", "Slow bias versus neighbors"
        detail = (
            "The LSTM reconstructs a slow calibration shift, so last-hour score can stay under "
            "the threshold. The residual against the neighbour blend has been accumulating."
            f"{extra} Overlay is the blend, not a rewrite of a storm."
        )
    elif label == "HARDWARE_ANOMALY":
        state, head = "disagree", f"{n_used or 'Two or more'} neighbors did not move{method_bit}"
        detail = "The blend of nearby stations sits far from this reading. The sensor is distrusted and a corrected hour is drawn."
    elif label == "UNCONFIRMED_ANOMALY":
        state, head = "skipped", "Fewer than two usable neighbors this hour"
        detail = "QC refused to guess weather versus hardware. Not a model error."
    elif label == "PHYSICAL_FAULT":
        state, head = "skipped", "Not needed after a hard rule"
        detail = "A frozen or missing channel is hardware without a neighbor vote."
    elif label == "CLEAN" and corroborated:
        state, head = "agree", f"{n_used or 'Two or more'} neighbors agree and stayed calm{method_bit}"
        detail = (
            "The blend sits with this reading and did not move itself (no shared shock). "
            "The LSTM found the pattern unusual; nothing happened. Corroborated clean, no alert."
        )
    elif label == "CLEAN":
        state, head = "not_run", "Not required on a clean hour"
        detail = "Neighbors are only asked when the LSTM is suspicious."
    else:
        state, head = "not_run", "No verdict yet"
        detail = "Waiting for a scored hour."
    tier3 = {"n": 3, "title": "Buddy check", "state": state, "head": head, "detail": detail}
    return [tier1, tier2, tier3]


def decision_trace_html(
    hour: dict[str, Any] | None,
    alert: dict[str, Any] | None,
    threshold: float | None,
) -> str:
    steps = decision_steps(hour, alert, threshold)
    rows: list[str] = []
    for step in steps:
        color = _STATE_COLOR.get(step["state"], SLATE)
        chip = _STATE_TEXT.get(step["state"], step["state"])
        rows.append(
            f'<div class="sg-trace-step">'
            f'<div class="sg-trace-n" style="border-color:{color};color:{color}">{step["n"]}</div>'
            f'<div class="sg-trace-body">'
            f'<div class="sg-trace-head"><span class="sg-trace-title">{escape(step["title"])}</span>'
            f'<span class="sg-chip" style="color:{color};border-color:{color}">{escape(chip)}</span></div>'
            f'<div class="sg-trace-line">{escape(step["head"])}</div>'
            f'<div class="sg-trace-detail">{escape(step["detail"])}</div>'
            f"</div></div>"
        )
    return f'<div class="sg-trace">{"".join(rows)}</div>'


def neighbor_rows(hour: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Per channel: observed, neighbor blend, delta, band, inside."""
    if not hour:
        return []
    mix = hour.get("tier3_mix") if isinstance(hour.get("tier3_mix"), dict) else None
    if not mix:
        return []
    observed, _imputed = channel_values(hour)
    rows: list[dict[str, Any]] = []
    for public, _obs, _imp, label, unit in CHANNELS:
        blend = mix.get(public)
        raw = observed.get(public)
        band = AGREE_BAND[public]
        delta = None
        inside = None
        if isinstance(blend, (int, float)) and isinstance(raw, (int, float)):
            delta = float(raw) - float(blend)
            inside = abs(delta) <= band
        rows.append(
            {
                "channel": public,
                "label": label,
                "unit": unit,
                "observed": raw,
                "blend": blend,
                "delta": delta,
                "band": band,
                "inside": inside,
            }
        )
    return rows


def neighbor_table_html(
    hour: dict[str, Any] | None,
    names: dict[str, str],
    label: str | None = None,
) -> str:
    rows = neighbor_rows(hour)
    if not rows:
        return ""
    corr = (hour or {}).get("tier3_corr") if isinstance((hour or {}).get("tier3_corr"), dict) else {}
    method = (hour or {}).get("tier3_method") or "cw_idw"
    cells: list[str] = []
    for row in rows:
        if row["inside"] is None:
            verdict, color = "—", SLATE
        elif row["inside"]:
            verdict, color = "inside band", WEATHER
        else:
            verdict, color = "outside band", HARDWARE
        delta = "—"
        if row["delta"] is not None:
            sign = "+" if row["delta"] > 0 else ""
            delta = f"{sign}{fmt_value(row['delta'])}"
        cells.append(
            f"<tr><td>{escape(row['label'])}</td>"
            f'<td class="sg-mono">{fmt_value(row["observed"])} {escape(row["unit"])}</td>'
            f'<td class="sg-mono">{fmt_value(row["blend"])} {escape(row["unit"])}</td>'
            f'<td class="sg-mono">{escape(delta)}</td>'
            f'<td class="sg-mono">± {fmt_value(row["band"])}</td>'
            f'<td><span class="sg-chip" style="color:{color};border-color:{color}">{verdict}</span></td></tr>'
        )
    who = ", ".join(
        f"{escape(names.get(bid, bid))} (r {fmt_value(r, 2)})" for bid, r in sorted(corr.items())
    )
    if label == "GENUINE_WEATHER_EVENT":
        summary = "Agreement on the channels carrying the error: weather. The raw reading is kept and no correction is drawn."
    elif label == "HARDWARE_ANOMALY":
        summary = "Disagreement on the channels carrying the error: hardware. The dashed correction and band come from this hour’s overlay."
    else:
        summary = "Agreement is judged on the channels that carry the reconstruction error, not all three."
    who_line = f'<p class="sg-caption" style="margin:0.35rem 0 0 0">Blend of {who} · {escape(str(method))}.</p>' if who else ""
    return (
        '<div class="sg-card sg-neighbor">'
        '<div class="sg-verdict-kicker">What the neighbors said</div>'
        '<table class="sg-table"><thead><tr>'
        "<th>Channel</th><th>This sensor</th><th>Neighbor blend</th><th>Δ</th><th>Agree band</th><th></th>"
        f'</tr></thead><tbody>{"".join(cells)}</tbody></table>'
        f'<p class="sg-caption" style="margin:0.55rem 0 0 0">{escape(summary)}</p>{who_line}'
        "</div>"
    )


def ribbon_hours(
    window: list[dict[str, Any]],
    focus_ts: Any | None,
    hours: int = RIBBON_HOURS,
) -> list[dict[str, Any]]:
    """The last `hours` rows ending at the focus hour (or the end of the run)."""
    if not window:
        return []
    key = stamp_key(focus_ts)
    end = len(window)
    if key:
        for index, row in enumerate(window):
            if stamp_key(row.get("timestamp")) == key:
                end = index + 1
                break
    start = max(0, end - hours)
    return window[start:end]


def verdict_ribbon_html(
    window: list[dict[str, Any]],
    focus_ts: Any | None,
    hours: int = RIBBON_HOURS,
) -> str:
    rows = ribbon_hours(window, focus_ts, hours)
    if not rows:
        return ""
    key = stamp_key(focus_ts)
    cells: list[str] = []
    counts = {"clean": 0, "weather": 0, "hardware": 0, "unknown": 0, "warming": 0, "feedgap": 0}
    for row in rows:
        kind = hour_kind(row)
        counts[kind] = counts.get(kind, 0) + 1
        color = KIND_COLOR.get(kind, LINE)
        focus = " sg-ribbon-focus" if key and stamp_key(row.get("timestamp")) == key else ""
        title = f"{fmt_stamp(row.get('timestamp'))} · {hour_caption(row)}"
        cells.append(f'<i class="sg-ribbon-cell{focus}" style="background:{color}" title="{escape(title)}"></i>')
    pad = "".join('<i class="sg-ribbon-cell" style="background:transparent;border:1px dashed #E2E8F0"></i>' for _ in range(hours - len(rows)))
    bits = [f"{counts['clean']} clean"]
    if counts["weather"]:
        bits.append(f"{counts['weather']} weather")
    if counts["hardware"]:
        bits.append(f"{counts['hardware']} hardware")
    if counts["unknown"]:
        bits.append(f"{counts['unknown']} unconfirmed")
    if counts["warming"]:
        bits.append(f"{counts['warming']} warming")
    if counts["feedgap"]:
        bits.append(f"{counts['feedgap']} feed gap")
    return (
        '<div class="sg-ribbon">'
        '<div class="sg-meter-head"><span>Last 24 verdicts</span>'
        f'<span>{escape(" · ".join(bits))}</span></div>'
        f'<div class="sg-ribbon-row">{pad}{"".join(cells)}</div>'
        '<p class="sg-caption" style="margin:0.4rem 0 0 0">One cell per stored hour, oldest on the left. '
        "The outlined cell is the hour shown above. Hover a cell for its label.</p>"
        "</div>"
    )


def timing_channels_line(timing: dict[str, Any] | None) -> str:
    body = (timing or {}).get("timing") if isinstance((timing or {}).get("timing"), dict) else {}
    attr = body.get("channel_attr") if isinstance(body.get("channel_attr"), dict) else {}
    if not attr:
        return ""
    names = {"temp_c": "temperature", "rhum_pct": "humidity", "pres_hpa": "pressure"}
    parts = []
    for key, value in sorted(attr.items(), key=lambda kv: -(kv[1] or 0)):
        try:
            parts.append(f"{names.get(key, key)} {float(value) * 100:.0f}%")
        except (TypeError, ValueError):
            continue
    return "Attribution by channel · " + " · ".join(parts) if parts else ""


def run_csv(station: dict[str, Any], window: list[dict[str, Any]]) -> str:
    """The continuous run as CSV. Raw columns first; overlay columns are clearly named."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "station_id",
            "station_name",
            "timestamp_utc",
            "temp_c_observed",
            "pres_hpa_observed",
            "rhum_pct_observed",
            "label",
            "warming_up",
            "temp_c_predicted",
            "pres_hpa_predicted",
            "rhum_pct_predicted",
            "temp_c_band_low",
            "temp_c_band_high",
            "reason",
        ]
    )
    name = short_name(str(station.get("name") or station.get("station_id") or ""))
    for row in window:
        observed, imputed = channel_values(row)
        band = interval_pair(row, "temp_c")
        has_band = band is not None
        writer.writerow(
            [
                station.get("station_id"),
                name,
                row.get("timestamp"),
                observed.get("temp_c"),
                observed.get("pres_hpa"),
                observed.get("rhum_pct"),
                row.get("label") or ("warming_up" if row.get("warming_up") else ""),
                bool(row.get("warming_up")),
                imputed.get("temp_c") if has_band else "",
                imputed.get("pres_hpa") if has_band else "",
                imputed.get("rhum_pct") if has_band else "",
                band[0] if band else "",
                band[1] if band else "",
                row.get("explainability_text") or "",
            ]
        )
    return buffer.getvalue()


def technician_note(
    station: dict[str, Any],
    hour: dict[str, Any] | None,
    alert: dict[str, Any] | None,
    names: dict[str, str],
) -> str:
    """Plain-text maintenance note an operator can paste into a ticket."""
    sid = str(station.get("station_id") or "")
    name = short_name(str(station.get("name") or sid))
    observed, imputed = channel_values(hour)
    label = _label_of(hour, alert)
    caption = hour_caption(hour) if hour else "No verdict"
    reason = (hour or {}).get("explainability_text") or (alert or {}).get("explainability_text") or "—"
    fault = (alert or {}).get("fault_type") or "—"
    conf = (alert or {}).get("confidence_score")
    lines = [
        f"SkyGuard QC note · {name} ({sid})",
        f"AWS: {station.get('aws_name') or '—'} · {station.get('aws_id') or '—'}",
        f"Hour (UTC): {fmt_stamp((hour or {}).get('timestamp'))}",
        f"Verdict: {caption}" + (f" [{label}]" if label else ""),
        f"Fault type: {fault}" + (f" · confidence {fmt_value(conf, 2)}" if conf is not None else ""),
        "",
        "Raw readings (never overwritten):",
        f"  T {fmt_value(observed.get('temp_c'))} °C · P {fmt_value(observed.get('pres_hpa'))} hPa · "
        f"H {fmt_value(observed.get('rhum_pct'))} %",
    ]
    band = interval_pair(hour, "temp_c")
    if band is not None:
        lines.append(
            f"Suggested correction: T {fmt_value(imputed.get('temp_c'))} °C "
            f"(90% band {fmt_value(band[0])}–{fmt_value(band[1])})"
        )
    lines += ["", f"Reason: {reason}"]
    for row in neighbor_rows(hour):
        if row["delta"] is None:
            continue
        where = "inside" if row["inside"] else "outside"
        lines.append(
            f"  {row['label']}: sensor {fmt_value(row['observed'])} vs neighbors {fmt_value(row['blend'])} "
            f"{row['unit']} · Δ {fmt_value(row['delta'])} · {where} the ±{fmt_value(row['band'])} band"
        )
    corr = (hour or {}).get("tier3_corr") if isinstance((hour or {}).get("tier3_corr"), dict) else {}
    if corr:
        lines.append("Neighbors: " + ", ".join(f"{names.get(b, b)} ({b})" for b in sorted(corr)))
    health = station.get("health_score")
    lines += [
        "",
        f"7-day sensor health: {fmt_value(health, 0)} · {station.get('status') or '—'} (weather hours excluded)",
    ]
    if label == "GENUINE_WEATHER_EVENT":
        lines.append("Action: none. Neighbors agree; this is weather. Do not dispatch.")
    elif label == "HARDWARE_ANOMALY" and str(fault) == "DRIFT":
        lines.append(
            "Action: inspect calibration on the flagged channel. The residual vs neighbors "
            "has been accumulating; this is not a one-hour spike. Keep the raw record."
        )
    elif label in {"HARDWARE_ANOMALY", "PHYSICAL_FAULT"}:
        lines.append("Action: inspect the flagged channel. Keep the raw record; use the correction downstream.")
    elif label == "UNCONFIRMED_ANOMALY":
        lines.append("Action: watch. Too few neighbors to separate weather from hardware this hour.")
    return "\n".join(lines) + "\n"
