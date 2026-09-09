from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from skyguard.api.main import create_app
from skyguard.data.import_ml_catalog import (
    DEMO_STATION_IDS,
    CatalogImportError,
    import_ml_catalog,
    load_scaler_ids,
)
from skyguard.db.models import Station, StationBuddy


def _write_raw(
    raw: Path,
    *,
    extra_stations: list[dict] | None = None,
    edges: list[tuple[str, str, float]] | None = None,
    hours_for: tuple[str, ...] = (),
) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    stations = [
        {
            "station_id": "42181",
            "station_name": "New Delhi / Palam",
            "latitude": 28.5667,
            "longitude": 77.1167,
            "elevation_m": 220.0,
        },
        {
            "station_id": "42182",
            "station_name": "New Delhi / Safdarjung",
            "latitude": 28.5833,
            "longitude": 77.2,
            "elevation_m": 211.0,
        },
        {
            "station_id": "42189",
            "station_name": "Delhi Ridge",
            "latitude": 28.65,
            "longitude": 77.22,
            "elevation_m": 216.0,
        },
        {
            "station_id": "43003",
            "station_name": "Bombay / Santacruz",
            "latitude": 19.1167,
            "longitude": 72.85,
            "elevation_m": 8.0,
        },
        {
            "station_id": "43057",
            "station_name": "Bombay / Colaba",
            "latitude": 18.9,
            "longitude": 72.8167,
            "elevation_m": 10.0,
        },
    ]
    if extra_stations:
        stations.extend(extra_stations)
    pd.DataFrame(stations).to_csv(raw / "stations.csv", index=False)

    if edges is None:
        edges = [
            ("42181", "42182", 8.4),
            ("42181", "42189", 12.1),
            ("42182", "42181", 8.4),
            ("42182", "42189", 7.0),
            ("42189", "42181", 12.1),
            ("42189", "42182", 7.0),
            ("43003", "43057", 24.0),
            ("43057", "43003", 24.0),
        ]
    pd.DataFrame(
        edges,
        columns=["primary_station_id", "buddy_station_id", "distance_km"],
    ).to_csv(raw / "buddy_edges.csv", index=False)

    for station_id in hours_for:
        pd.DataFrame(
            {
                "timestamp": ["2024-07-01T00:00:00Z", "2024-07-01T01:00:00Z"],
                "temp": [30.0, 31.0],
                "rhum": [70.0, 71.0],
                "pres": [1005.0, 1004.0],
            }
        ).to_csv(raw / f"{station_id}.csv", index=False)


def test_demo_stations_have_scalers() -> None:
    scaler_ids = load_scaler_ids()
    assert scaler_ids, "ml/ml/artifacts/scalers.json must ship with the repo"
    for station_id in DEMO_STATION_IDS:
        assert station_id in scaler_ids


def test_import_missing_raw_is_explicit(tmp_path) -> None:
    try:
        import_ml_catalog(raw_dir=tmp_path / "empty", convert_station_hours=False)
    except CatalogImportError as exc:
        assert "stations.csv" in str(exc)
        assert "MISSING" in str(exc)
    else:
        raise AssertionError("expected CatalogImportError")


def test_import_writes_catalog_edges_isolates_and_parquet(tmp_path) -> None:
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    _write_raw(raw, hours_for=("42181",))

    result = import_ml_catalog(
        raw_dir=raw,
        stations_path=tmp_path / "stations.json",
        edges_out=tmp_path / "buddy_edges.json",
        processed_dir=processed,
        convert_station_hours=True,
    )

    catalog = json.loads(Path(result["catalog_path"]).read_text(encoding="utf-8"))
    by_id = {row["station_id"]: row for row in catalog["stations"]}
    assert catalog["n_stations"] == 5
    assert by_id["42181"]["name"] == "New Delhi / Palam"
    assert by_id["42181"]["cluster_id"] == "NORTH"
    assert by_id["43003"]["cluster_id"] == "WEST"
    assert by_id["42181"]["isolate"] is False
    assert set(by_id["42181"]["buddy_ids"]) == {"42182", "42189"}
    assert by_id["43003"]["isolate"] is True
    assert by_id["43057"]["isolate"] is True
    assert "43003" in result["isolates"]

    edges = json.loads(Path(result["edges_path"]).read_text(encoding="utf-8"))
    assert edges["n_edges"] == 8

    parquet = pd.read_parquet(processed / "42181.parquet")
    assert list(parquet.columns) == ["timestamp", "temp_c", "pres_hpa", "rhum_pct"]
    assert len(parquet) == 2
    assert result["hours_written"] == ["42181"]
    assert "42182" in result["hours_skipped"]


def test_scaler_ids_subset_of_full_imported_catalog(tmp_path) -> None:
    scaler_ids = load_scaler_ids()
    extra = [
        {
            "station_id": sid,
            "station_name": sid,
            "latitude": 20.0,
            "longitude": 78.0,
            "elevation_m": 100.0,
        }
        for sid in sorted(scaler_ids)
        if sid not in DEMO_STATION_IDS and sid != "42189"
    ]
    raw = tmp_path / "raw"
    _write_raw(raw, extra_stations=extra, edges=[])
    result = import_ml_catalog(
        raw_dir=raw,
        stations_path=tmp_path / "stations.json",
        edges_out=tmp_path / "buddy_edges.json",
        processed_dir=tmp_path / "processed",
        convert_station_hours=False,
    )
    catalog = json.loads(Path(result["catalog_path"]).read_text(encoding="utf-8"))
    imported = {row["station_id"]: row for row in catalog["stations"]}
    assert scaler_ids <= set(imported)
    assert result["missing_catalog"] == []
    for station_id in DEMO_STATION_IDS:
        assert station_id in imported
    # No edges → everyone is an isolate (ML rule: fewer than 2 buddies).
    assert imported["42181"]["isolate"] is True


def test_api_boot_upserts_station_buddies(tmp_path) -> None:
    raw = tmp_path / "raw"
    _write_raw(raw)
    stations_path = tmp_path / "stations.json"
    edges_path = tmp_path / "buddy_edges.json"
    import_ml_catalog(
        raw_dir=raw,
        stations_path=stations_path,
        edges_out=edges_path,
        processed_dir=tmp_path / "processed",
        convert_station_hours=False,
    )
    app = create_app(
        db_path=tmp_path / "test.db",
        stations_path=stations_path,
        buddy_edges_path=edges_path,
    )
    with TestClient(app) as client:
        listed = client.get("/stations")
        assert listed.status_code == 200
        assert {row["station_id"] for row in listed.json()} >= set(DEMO_STATION_IDS)
        palam = next(row for row in listed.json() if row["station_id"] == "42181")
        assert palam["cluster_id"] == "NORTH"

        session = app.state.session_factory()
        try:
            palam_edges = session.query(StationBuddy).filter_by(station_id="42181").all()
            assert {edge.buddy_id for edge in palam_edges} == {"42182", "42189"}
            palam_row = session.get(Station, "42181")
            assert palam_row is not None
            assert palam_row.isolate is False
            west = session.get(Station, "43003")
            assert west is not None
            assert west.isolate is True
        finally:
            session.close()
