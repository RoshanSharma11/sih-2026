"""Pull IMD state snapshots and post matched hours through the product ingest path."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from skyguard.db.models import Station
from skyguard.engine.pipeline import feed_gap_for, ingest_observation
from skyguard.errors import DuplicateObservation
from skyguard.imd.client import ImdClient, load_credentials
from skyguard.schemas import Channel, IngestPayload

# Public state ids from the IMD AWS reference. These are the states that contain
# the 48 stations in stations_judge48.csv. `sid` is the state; row `ID` is aws_id.
LIVE_STATE_IDS = (
    1,  # Telangana
    2,  # Andhra Pradesh
    4,  # Kerala
    5,  # Uttar Pradesh
    7,  # Delhi
    8,  # Rajasthan
    9,  # Gujarat
    12,  # Chhattisgarh
    16,  # Tripura
    19,  # Goa
    21,  # Maharashtra
    22,  # Haryana
    24,  # Assam
    25,  # Tamil Nadu
    26,  # West Bengal
    31,  # Uttarakhand
    33,  # Puducherry
    35,  # Andaman and Nicobar
    36,  # Daman and Diu
)

FetchState = Callable[[int], list[dict[str, Any]]]

# IMD rows carry TIME hh:15 in practice; hh:20 catches the fresh hour once.
DEFAULT_POLL_SECONDS = 3600.0
DEFAULT_POLL_MINUTE = 20
# Re-scan every state this often so a station that moves to a new `sid` is found again.
FULL_SCAN_EVERY = 24
RATE_LIMIT_MARK = "HTTP 429"
BACKOFF_BASE_SECONDS = 3600.0
BACKOFF_MAX_SECONDS = 4 * 3600.0


@dataclass
class ImdStatus:
    last_success: datetime | None = None
    last_error: str | None = None
    matched: int = 0
    stored: int = 0
    duplicates: int = 0
    feed_gap: dict[str, int] = field(default_factory=dict)
    next_poll: datetime | None = None
    states_polled: int = 0
    rate_limited_until: datetime | None = None


@dataclass
class PollOutcome:
    matched: int = 0
    stored: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)
    feed_gap: dict[str, int] = field(default_factory=dict)
    states_polled: int = 0
    rate_limited: bool = False


FEED_GAP_MIN_SHARE = 0.5
FEED_GAP_MIN_STATIONS = 3


def detect_feed_gap(
    payloads: list[IngestPayload],
    min_share: float = FEED_GAP_MIN_SHARE,
    min_stations: int = FEED_GAP_MIN_STATIONS,
) -> dict[datetime, list[Channel]]:
    """Channels the feed left empty on at least `min_share` of matched stations, per hour.

    One station missing humidity is a sensor problem. Forty stations missing humidity in
    the same hour is the feed. The second case must not become forty COMMUNICATION faults.
    """
    by_hour: dict[datetime, list[IngestPayload]] = {}
    for payload in payloads:
        by_hour.setdefault(payload.timestamp, []).append(payload)
    gaps: dict[datetime, list[Channel]] = {}
    for hour, group in by_hour.items():
        if len(group) < min_stations:
            continue
        missing: list[Channel] = []
        for channel, getter in (
            (Channel.TEMP_C, lambda p: p.temp_c),
            (Channel.PRES_HPA, lambda p: p.pres_hpa),
            (Channel.RHUM_PCT, lambda p: p.rhum_pct),
        ):
            nulls = sum(1 for p in group if getter(p) is None)
            if nulls / len(group) >= min_share:
                missing.append(channel)
        if missing:
            gaps[hour] = missing
    return gaps


def parse_channel(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text == "" or text.upper() in {"NA", "NULL", "NAN", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def bucket_hour(date_text: object, time_text: object) -> datetime | None:
    """IMD DATE+TIME is UTC. Floor to the hour and keep the Z offset."""
    if date_text is None or time_text is None:
        return None
    date_raw = str(date_text).strip()
    time_raw = str(time_text).strip()
    if not date_raw or not time_raw:
        return None
    try:
        parsed = datetime.strptime(f"{date_raw} {time_raw}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(minute=0, second=0, microsecond=0, tzinfo=timezone.utc)


def rows_to_payloads(
    rows: list[dict[str, Any]],
    aws_to_stations: dict[str, list[str]],
) -> list[IngestPayload]:
    """Match IMD `ID` to every catalog station with that `aws_id`. Empty channels stay null."""
    latest: dict[str, IngestPayload] = {}
    for row in rows:
        aws_id = str(row.get("ID") or "").strip().upper()
        station_ids = aws_to_stations.get(aws_id) or []
        if not station_ids:
            continue
        timestamp = bucket_hour(row.get("DATE"), row.get("TIME"))
        if timestamp is None:
            continue
        for station_id in station_ids:
            latest[station_id] = IngestPayload(
                station_id=station_id,
                timestamp=timestamp,
                temp_c=parse_channel(row.get("CURR_TEMP")),
                pres_hpa=parse_channel(row.get("MSLP")),
                rhum_pct=parse_channel(row.get("RH")),
            )
    return [latest[station_id] for station_id in sorted(latest)]


def aws_index(session: Session) -> dict[str, list[str]]:
    rows = session.execute(select(Station.station_id, Station.aws_id)).all()
    index: dict[str, list[str]] = {}
    for station_id, aws_id in rows:
        if not aws_id:
            continue
        index.setdefault(str(aws_id).strip().upper(), []).append(station_id)
    return index


def states_for_poll(session: Session) -> tuple[int, ...]:
    """States that held a matched station last time. Every state until we have learned any."""
    rows = session.scalars(
        select(Station.aws_state_id).where(Station.aws_state_id.is_not(None)).distinct()
    ).all()
    learned = tuple(sorted({int(value) for value in rows}))
    return learned or LIVE_STATE_IDS


def remember_states(session: Session, station_states: dict[str, int]) -> None:
    for station_id, state_id in station_states.items():
        session.execute(
            update(Station).where(Station.station_id == station_id).values(aws_state_id=state_id)
        )


def is_rate_limited(message: str) -> bool:
    return RATE_LIMIT_MARK in message


def backoff_seconds(strikes: int) -> float:
    """1 h after the first 429, doubling to a 4 h cap. One 429 ends the whole cycle."""
    if strikes <= 0:
        return 0.0
    return min(BACKOFF_BASE_SECONDS * (2 ** (strikes - 1)), BACKOFF_MAX_SECONDS)


def next_aligned(now: datetime, interval_seconds: float, minute: int = DEFAULT_POLL_MINUTE) -> datetime:
    """Next poll time. Hourly polls land on hh:MM so one call per hour sees the new IMD hour."""
    if interval_seconds >= 3600.0:
        step_hours = max(1, int(interval_seconds // 3600))
        slot = now.replace(minute=minute, second=0, microsecond=0)
        while slot <= now:
            slot += timedelta(hours=step_hours)
        return slot
    return now + timedelta(seconds=interval_seconds)


def poll_once(
    app,
    fetch_state: FetchState,
    state_ids: tuple[int, ...] | None = None,
) -> PollOutcome:
    """Ingest one snapshot. A duplicate hour is skipped; it does not stop the loop.

    `state_ids=None` polls only the states that matched a catalog station before
    (`states_for_poll`). A 429 ends the cycle at once so the hourly budget is not spent
    on calls that will also fail.
    """
    session = app.state.session_factory()
    try:
        index = aws_index(session)
        if state_ids is None:
            state_ids = states_for_poll(session)
    finally:
        session.close()

    outcome = PollOutcome()
    payloads: list[IngestPayload] = []
    station_states: dict[str, int] = {}
    for state_id in state_ids:
        outcome.states_polled += 1
        try:
            rows = fetch_state(state_id)
        except Exception as exc:
            message = str(exc).replace("\n", " ")[:240]
            outcome.errors.append(message)
            if is_rate_limited(message):
                outcome.rate_limited = True
                break
            continue
        matched_here = rows_to_payloads(rows, index)
        for payload in matched_here:
            station_states[payload.station_id] = state_id
        payloads.extend(matched_here)
    outcome.matched = len({payload.station_id for payload in payloads})
    if station_states:
        session = app.state.session_factory()
        try:
            remember_states(session, station_states)
            session.commit()
        finally:
            session.close()

    gaps = detect_feed_gap(payloads)
    for payload in payloads:
        gap = gaps.get(payload.timestamp) or []
        for channel in feed_gap_for(payload, gap):
            outcome.feed_gap[channel.value] = outcome.feed_gap.get(channel.value, 0) + 1
        _ingest_payload(app, payload, outcome, feed_gap=gap)

    status: ImdStatus = app.state.imd_status
    status.states_polled = outcome.states_polled
    if outcome.errors and outcome.matched == 0 and not outcome.stored and not outcome.duplicates:
        status.last_error = outcome.errors[-1]
    else:
        status.last_success = datetime.now(timezone.utc)
        status.matched = outcome.matched
        status.stored = outcome.stored
        status.duplicates = outcome.duplicates
        status.feed_gap = dict(outcome.feed_gap)
        status.last_error = outcome.errors[-1] if outcome.errors else None
    return outcome


def _ingest_payload(
    app, payload: IngestPayload, outcome: PollOutcome, feed_gap: list[Channel] | None = None
) -> None:
    session = app.state.session_factory()
    try:
        ingest_observation(
            session,
            payload,
            app.state.catalog_ready,
            app.state.windows,
            demo=app.state.demo,
            qc_engine=app.state.qc_engine,
            feed_gap=feed_gap,
        )
        session.commit()
        outcome.stored += 1
    except DuplicateObservation:
        session.rollback()
        outcome.duplicates += 1
    except Exception as exc:
        session.rollback()
        outcome.errors.append(f"{payload.station_id}: {exc}".replace("\n", " ")[:240])
    finally:
        session.close()


class ImdPoller:
    """Hourly, aligned, budget-aware loop.

    First poll runs at start-up and scans every state; later polls scan only the states
    that matched, and every `FULL_SCAN_EVERY` polls do a full scan again. A 429 ends the
    cycle and pushes the next poll out by `backoff_seconds` (1 h, 2 h, 4 h cap).
    """

    def __init__(
        self,
        app,
        interval_seconds: float = DEFAULT_POLL_SECONDS,
        poll_minute: int = DEFAULT_POLL_MINUTE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.app = app
        self.interval_seconds = interval_seconds
        self.poll_minute = poll_minute
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.polls = 0
        self.strikes = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: ImdClient | None = None

    def state_ids_for_cycle(self) -> tuple[int, ...] | None:
        if self.polls % FULL_SCAN_EVERY == 0:
            return LIVE_STATE_IDS
        return None

    def run_cycle(self, fetch_state: FetchState) -> datetime:
        """One poll, then the time of the next one. Pure apart from the poll itself."""
        status: ImdStatus = self.app.state.imd_status
        try:
            outcome = poll_once(self.app, fetch_state, state_ids=self.state_ids_for_cycle())
        except Exception as exc:
            status.last_error = str(exc).replace("\n", " ")[:240]
            outcome = PollOutcome(errors=[status.last_error])
        self.polls += 1
        now = self.clock()
        if outcome.rate_limited:
            self.strikes += 1
            wait = backoff_seconds(self.strikes)
            next_at = max(now + timedelta(seconds=wait), next_aligned(now, self.interval_seconds, self.poll_minute))
            status.rate_limited_until = next_at
        else:
            self.strikes = 0
            status.rate_limited_until = None
            next_at = next_aligned(now, self.interval_seconds, self.poll_minute)
        status.next_poll = next_at
        return next_at

    def start(self) -> None:
        credentials = load_credentials()
        if not credentials.complete:
            app_status: ImdStatus = self.app.state.imd_status
            app_status.last_error = "IMD credentials are not set"
            return
        self._client = ImdClient(credentials)
        self._thread = threading.Thread(target=self._loop, name="imd-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._client is not None:
            self._client.close()

    def _loop(self) -> None:
        assert self._client is not None
        while not self._stop.is_set():
            next_at = self.run_cycle(self._client.fetch_state)
            wait = max(1.0, (next_at - self.clock()).total_seconds())
            if self._stop.wait(wait):
                break


def poll_enabled(db_path_overridden: bool) -> bool:
    """The default API process polls. Tests that pass their own database do not."""
    if db_path_overridden:
        return False
    return os.environ.get("SKYGUARD_IMD_POLL", "1").strip() != "0"


def poll_interval_seconds() -> float:
    raw = os.environ.get("SKYGUARD_IMD_POLL_SECONDS", str(int(DEFAULT_POLL_SECONDS))).strip()
    try:
        return max(30.0, float(raw))
    except ValueError:
        return DEFAULT_POLL_SECONDS


def poll_minute() -> int:
    raw = os.environ.get("SKYGUARD_IMD_POLL_MINUTE", str(DEFAULT_POLL_MINUTE)).strip()
    try:
        return min(59, max(0, int(raw)))
    except ValueError:
        return DEFAULT_POLL_MINUTE
