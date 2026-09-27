import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from skyguard.api.main import create_app
from skyguard.imd.client import ImdClient, ImdCredentials
from skyguard.imd.poller import bucket_hour, parse_channel, poll_once, rows_to_payloads


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
