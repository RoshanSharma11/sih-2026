import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from skyguard.api.main import create_app
from skyguard.imd.client import ImdClient, ImdCredentials
from skyguard.imd.poller import (
    bucket_hour,
    detect_feed_gap,
    parse_channel,
    poll_once,
    rows_to_payloads,
)
from skyguard.schemas import Channel


def test_empty_imd_strings_are_null_and_time_buckets_to_the_utc_hour() -> None:
    assert parse_channel("") is None
    assert parse_channel("  ") is None
    assert parse_channel(None) is None
    assert parse_channel("26.3") == 26.3
    hour = bucket_hour("2026-09-27", "17:15:00")
    assert hour == datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)


def test_rows_match_aws_id_and_keep_missing_channels() -> None:
    payloads = rows_to_payloads(
        [
            {
                "ID": "55fdd400",
                "DATE": "2026-09-27",
                "TIME": "17:15:00",
                "CURR_TEMP": None,
                "RH": "",
                "MSLP": "1003.0",
            },
            {"ID": "NOT-IN-CATALOG", "DATE": "2026-09-27", "TIME": "17:15:00", "CURR_TEMP": "40"},
        ],
        {"55FDD400": ["42182"]},
    )
    assert len(payloads) == 1
    assert payloads[0].station_id == "42182"
    assert payloads[0].temp_c is None
    assert payloads[0].rhum_pct is None
    assert payloads[0].pres_hpa == 1003.0
    assert payloads[0].timestamp == datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)


def test_one_aws_id_feeds_every_catalog_station_that_shares_it() -> None:
    payloads = rows_to_payloads(
        [
            {
                "ID": "B489D032",
                "DATE": "2026-09-27",
                "TIME": "17:00:00",
                "CURR_TEMP": "30",
                "RH": "60",
                "MSLP": "1000",
            }
        ],
        {"B489D032": ["42872", "42874"]},
    )
    assert {item.station_id for item in payloads} == {"42872", "42874"}


def test_token_refreshes_before_expiry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={"access_token": f"t{calls['n']}", "expires_in": 120, "token_type": "Bearer"},
        )

    start = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)
    now = {"t": start}
    client = ImdClient(
        ImdCredentials("key", "user@example.com", "secret", "http://token.test", "http://aws.test"),
        transport=httpx.MockTransport(handler),
        clock=lambda: now["t"],
    )
    try:
        assert client.access_token() == "t1"
        now["t"] = start + timedelta(seconds=30)
        assert client.access_token() == "t1"
        now["t"] = start + timedelta(seconds=60)
        assert client.access_token() == "t2"
        assert calls["n"] == 2
    finally:
        client.close()


def _catalog(path) -> None:
    path.write_text(
        json.dumps(
            {
                "stations": [
                    {
                        "station_id": "42182",
                        "name": "Safdarjung",
                        "latitude": 28.58,
                        "longitude": 77.2,
                        "aws_id": "55FDD400",
                        "isolate": True,
                        "buddy_ids": [],
                    },
                    {
                        "station_id": "43003",
                        "name": "Santa Cruz",
                        "latitude": 19.12,
                        "longitude": 72.85,
                        "aws_id": "B489804E",
                        "isolate": True,
                        "buddy_ids": [],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def test_poll_ingests_matches_and_skips_duplicate_hours(tmp_path) -> None:
    stations = tmp_path / "stations.json"
    _catalog(stations)
    app = create_app(db_path=tmp_path / "test.db", stations_path=stations, buddy_edges_path=tmp_path / "none.json")

    def fetch(state_id: int):
        if state_id == 7:
            raise RuntimeError("delhi down")
        if state_id == 21:
            return [
                {
                    "ID": "B489804E",
                    "DATE": "2026-09-27",
                    "TIME": "17:15:00",
                    "CURR_TEMP": "26.3",
                    "RH": "70",
                    "MSLP": "1013.2",
                }
            ]
        return []

    with TestClient(app) as client:
        first = poll_once(app, fetch, state_ids=(7, 21))
        assert first.matched == 1
        assert first.stored == 1
        assert first.duplicates == 0
        assert first.errors
        body = client.get("/healthz").json()
        assert body["imd"]["matched"] == 1
        assert body["imd"]["last_success"]
        assert "delhi down" in body["imd"]["last_error"]
        latest = client.get("/stations/43003").json()["latest"]
        assert latest["observed"]["temp_c"] == 26.3
        assert latest["timestamp"].startswith("2026-09-27T17:00:00")

        second = poll_once(app, fetch, state_ids=(7, 21))
        assert second.stored == 0
        assert second.duplicates == 1
        assert second.matched == 1


def _rows(ids: list[str], rh: str | None) -> list[dict]:
    return [
        {
            "ID": aws,
            "DATE": "2026-09-27",
            "TIME": "17:15:00",
            "CURR_TEMP": "26.3",
            "RH": rh,
            "MSLP": "1013.2",
        }
        for aws in ids
    ]


def test_detect_feed_gap_needs_a_network_wide_share() -> None:
    hour = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)
    index = {f"A{i}": [f"S{i}"] for i in range(6)}
    # one station missing humidity: sensor problem, not a gap
    one = rows_to_payloads(_rows(["A0"], "") + _rows(["A1", "A2", "A3", "A4", "A5"], "70"), index)
    assert detect_feed_gap(one) == {}
    # four of six missing humidity: feed gap on rhum_pct only
    most = rows_to_payloads(_rows(["A0", "A1", "A2", "A3"], "") + _rows(["A4", "A5"], "70"), index)
    assert detect_feed_gap(most) == {hour: [Channel.RHUM_PCT]}
    # two stations is too few to call a gap
    tiny = rows_to_payloads(_rows(["A0", "A1"], ""), index)
    assert detect_feed_gap(tiny) == {}


# Real catalog ids: the v2 engine rejects stations without a train scaler.
_GAP_STATIONS = ("43003", "43057", "42182", "43371")


def test_feed_gap_hour_is_stored_raw_and_never_charged_to_the_sensor(tmp_path) -> None:
    stations = tmp_path / "stations.json"
    stations.write_text(
        json.dumps(
            {
                "stations": [
                    {
                        "station_id": station_id,
                        "name": f"Station {station_id}",
                        "latitude": 19.0 + i * 0.01,
                        "longitude": 72.8,
                        "aws_id": f"A{i}",
                        "isolate": True,
                        "buddy_ids": [],
                    }
                    for i, station_id in enumerate(_GAP_STATIONS)
                ]
            }
        ),
        encoding="utf-8",
    )
    app = create_app(db_path=tmp_path / "test.db", stations_path=stations, buddy_edges_path=tmp_path / "none.json")

    def fetch(state_id: int):
        return _rows(["A0", "A1", "A2"], "") + _rows(["A3"], "70")

    with TestClient(app) as client:
        start = datetime(2026, 9, 26, 17, 0, tzinfo=timezone.utc)
        client.post(
            "/stations/43003/seed",
            json={
                "observations": [
                    {
                        "timestamp": (start + timedelta(hours=i)).isoformat(),
                        "temp_c": 26.0,
                        "pres_hpa": 1010.0,
                        "rhum_pct": 70.0,
                    }
                    for i in range(24)
                ]
            },
        ).raise_for_status()

        outcome = poll_once(app, fetch, state_ids=(21,))
        assert outcome.stored == 4
        assert outcome.feed_gap == {"rhum_pct": 3}
        body = client.get("/healthz").json()
        assert body["imd"]["feed_gap"] == {"rhum_pct": 3}

        # warmed station in the gap: raw stored, not scored, health untouched
        detail = client.get("/stations/43003").json()
        assert detail["latest"]["feed_gap"] == ["rhum_pct"]
        assert detail["latest"]["label"] is None
        assert detail["latest"]["warming_up"] is False
        assert detail["latest"]["observed"]["rhum_pct"] is None
        assert detail["health_score"] == 100.0
        assert client.get("/alerts").json() == []
        rows = client.get("/stations/43003/telemetry", params={"hours": 48}).json()
        assert rows[-1]["feed_gap"] == ["rhum_pct"]

        # the station that did report humidity is not marked as a gap
        assert client.get("/stations/43371").json()["latest"]["feed_gap"] == []


def test_hourly_polls_align_to_the_poll_minute_and_back_off_doubles() -> None:
    from skyguard.imd.poller import backoff_seconds, next_aligned

    now = datetime(2026, 9, 28, 12, 5, tzinfo=timezone.utc)
    assert next_aligned(now, 3600.0, minute=20) == datetime(2026, 9, 28, 12, 20, tzinfo=timezone.utc)
    late = datetime(2026, 9, 28, 12, 25, tzinfo=timezone.utc)
    assert next_aligned(late, 3600.0, minute=20) == datetime(2026, 9, 28, 13, 20, tzinfo=timezone.utc)
    # sub-hourly (tests / demos) is plain interval
    assert next_aligned(now, 300.0) == now + timedelta(seconds=300)
    assert [backoff_seconds(n) for n in range(0, 5)] == [0.0, 3600.0, 7200.0, 14400.0, 14400.0]


def test_poller_learns_matched_states_and_stops_the_cycle_on_429(tmp_path) -> None:
    from skyguard.imd.poller import LIVE_STATE_IDS, ImdPoller, states_for_poll

    stations = tmp_path / "stations.json"
    _catalog(stations)
    app = create_app(db_path=tmp_path / "test.db", stations_path=stations, buddy_edges_path=tmp_path / "none.json")
    calls: list[int] = []

    def fetch(state_id: int):
        calls.append(state_id)
        if state_id == 21:
            return _rows(["B489804E"], "70")
        if state_id == 7:
            return _rows(["55FDD400"], "70")
        return []

    clock = {"now": datetime(2026, 9, 28, 12, 5, tzinfo=timezone.utc)}
    poller = ImdPoller(app, interval_seconds=3600.0, poll_minute=20, clock=lambda: clock["now"])
    with TestClient(app) as client:
        # first cycle scans every state and remembers where the 48 live
        next_at = poller.run_cycle(fetch)
        assert len(calls) == len(LIVE_STATE_IDS)
        assert next_at == datetime(2026, 9, 28, 12, 20, tzinfo=timezone.utc)
        session = app.state.session_factory()
        try:
            assert states_for_poll(session) == (7, 21)
        finally:
            session.close()
        body = client.get("/healthz").json()["imd"]
        assert body["states_polled"] == len(LIVE_STATE_IDS)
        assert body["next_poll"].startswith("2026-09-28T12:20:00")
        assert body["rate_limited_until"] is None

        # second cycle touches only those two states
        calls.clear()
        clock["now"] = datetime(2026, 9, 28, 12, 20, tzinfo=timezone.utc)
        poller.run_cycle(fetch)
        assert sorted(calls) == [7, 21]

        # a 429 ends the cycle after one call and pushes the next poll out an hour
        calls.clear()

        def limited(state_id: int):
            calls.append(state_id)
            raise RuntimeError(f"IMD aws_data sid={state_id} HTTP 429: Hourly API limit exceeded")

        clock["now"] = datetime(2026, 9, 28, 13, 20, tzinfo=timezone.utc)
        next_at = poller.run_cycle(limited)
        assert calls == [7]
        assert next_at == datetime(2026, 9, 28, 14, 20, tzinfo=timezone.utc)
        body = client.get("/healthz").json()["imd"]
        assert body["rate_limited_until"].startswith("2026-09-28T14:20:00")
        assert "HTTP 429" in body["last_error"]

        # a second strike doubles the wait
        clock["now"] = datetime(2026, 9, 28, 14, 20, tzinfo=timezone.utc)
        next_at = poller.run_cycle(limited)
        assert next_at == datetime(2026, 9, 28, 16, 20, tzinfo=timezone.utc)

        # a clean cycle clears the backoff
        clock["now"] = datetime(2026, 9, 28, 16, 20, tzinfo=timezone.utc)
        poller.run_cycle(fetch)
        assert client.get("/healthz").json()["imd"]["rate_limited_until"] is None
