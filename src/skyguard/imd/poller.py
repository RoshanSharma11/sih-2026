"""Pull IMD state snapshots and post matched hours through the product ingest path."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
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


@dataclass
class ImdStatus:
    last_success: datetime | None = None
    last_error: str | None = None
    matched: int = 0
    stored: int = 0
    duplicates: int = 0
    feed_gap: dict[str, int] = field(default_factory=dict)


@dataclass
class PollOutcome:
    matched: int = 0
    stored: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)
    feed_gap: dict[str, int] = field(default_factory=dict)


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


def poll_once(
    app,
    fetch_state: FetchState,
    state_ids: tuple[int, ...] = LIVE_STATE_IDS,
) -> PollOutcome:
    """Ingest one snapshot. A duplicate hour is skipped; it does not stop the loop."""
    session = app.state.session_factory()
    try:
        index = aws_index(session)
    finally:
        session.close()

    outcome = PollOutcome()
    payloads: list[IngestPayload] = []
    for state_id in state_ids:
        try:
            rows = fetch_state(state_id)
        except Exception as exc:
            outcome.errors.append(str(exc).replace("\n", " ")[:240])
            continue
        payloads.extend(rows_to_payloads(rows, index))
    outcome.matched = len({payload.station_id for payload in payloads})

    gaps = detect_feed_gap(payloads)
    for payload in payloads:
        gap = gaps.get(payload.timestamp) or []
        for channel in feed_gap_for(payload, gap):
            outcome.feed_gap[channel.value] = outcome.feed_gap.get(channel.value, 0) + 1
        _ingest_payload(app, payload, outcome, feed_gap=gap)

    status: ImdStatus = app.state.imd_status
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
    def __init__(self, app, interval_seconds: float = 900.0) -> None:
        self.app = app
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: ImdClient | None = None

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
            try:
                poll_once(self.app, self._client.fetch_state)
            except Exception as exc:
                self.app.state.imd_status.last_error = str(exc).replace("\n", " ")[:240]
            if self._stop.wait(self.interval_seconds):
                break


def poll_enabled(db_path_overridden: bool) -> bool:
    """The default API process polls. Tests that pass their own database do not."""
    if db_path_overridden:
        return False
    return os.environ.get("SKYGUARD_IMD_POLL", "1").strip() != "0"


def poll_interval_seconds() -> float:
    raw = os.environ.get("SKYGUARD_IMD_POLL_SECONDS", "900").strip()
    try:
        return max(30.0, float(raw))
    except ValueError:
        return 900.0
