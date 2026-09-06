"""Discover Indian AWS candidates and persist hourly T/P/H parquet."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from skyguard.config import (
    ANCHORS,
    FETCH_END,
    FETCH_START,
    PROCESSED_DIR,
    RAW_DIR,
    SEARCH_RADIUS_M,
    STATIONS_PATH,
)
from skyguard.data.catalog import (
    StationRecord,
    catalog_document,
    completeness,
    nearest_cluster,
    passes_threshold,
    select_keepers,
    write_catalog,
)

METEOSTAT_TO_OURS = {"temp": "temp_c", "pres": "pres_hpa", "rhum": "rhum_pct"}


def _nearby_records(latitude: float, longitude: float, radius_m: int, limit: int) -> list[dict]:
    import meteostat as ms

    nearby = ms.stations.nearby(ms.Point(latitude, longitude), radius=radius_m, limit=limit)
    records: list[dict] = []
    for station_id, row in nearby.iterrows():
        records.append(
            {
                "station_id": str(station_id),
                "name": str(row["name"]),
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "elevation_m": None if pd.isna(row["elevation"]) else float(row["elevation"]),
                "cluster_id": nearest_cluster(float(row["latitude"]), float(row["longitude"])),
            }
        )
    return records


def discover_candidates(limit_per_anchor: int = 8, extra_north: bool = False) -> list[dict]:
    seen: dict[str, dict] = {}
    for anchor in ANCHORS:
        for record in _nearby_records(
            anchor["latitude"],
            anchor["longitude"],
            SEARCH_RADIUS_M,
            limit_per_anchor,
        ):
            seen.setdefault(record["station_id"], record)
    if extra_north:
        delhi = ANCHORS[0]
        for record in _nearby_records(delhi["latitude"], delhi["longitude"], 150_000, limit_per_anchor + 6):
            seen.setdefault(record["station_id"], record)
    return list(seen.values())


def _year_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    year = start.year
    while datetime(year, 1, 1) <= end:
        window_start = max(start, datetime(year, 1, 1))
        window_end = min(end, datetime(year, 12, 31, 23, 0, 0))
        windows.append((window_start, window_end))
        year += 1
    return windows


def fetch_hourly(station_id: str, start: datetime, end: datetime) -> pd.DataFrame:
    import meteostat as ms

    chunks: list[pd.DataFrame] = []
    for window_start, window_end in _year_windows(start, end):
        series = ms.hourly(
            station_id,
            window_start,
            window_end,
            parameters=[ms.Parameter.TEMP, ms.Parameter.PRES, ms.Parameter.RHUM],
        )
        chunk = series.fetch()
        if chunk is not None and not chunk.empty:
            chunks.append(chunk)
    frame = pd.concat(chunks).sort_index() if chunks else pd.DataFrame(columns=["temp", "pres", "rhum"])
    frame = frame[~frame.index.duplicated(keep="last")]
    return normalize_hourly(frame, start, end)


def normalize_hourly(frame: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    renamed = frame.rename(columns=METEOSTAT_TO_OURS)
    for channel in METEOSTAT_TO_OURS.values():
        if channel not in renamed.columns:
            renamed[channel] = pd.NA
    index = pd.to_datetime(renamed.index, utc=True)
    renamed = renamed.set_axis(index, axis=0)
    renamed.index.name = "timestamp"
    full = pd.date_range(
        start=pd.Timestamp(start, tz="UTC"),
        end=pd.Timestamp(end, tz="UTC"),
        freq="h",
        name="timestamp",
    )
    return renamed.reindex(full)[["temp_c", "pres_hpa", "rhum_pct"]]


def persist_station(station_id: str, df: pd.DataFrame, processed_dir: Path | None = None) -> tuple[Path, Path]:
    out_dir = processed_dir or PROCESSED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = df.reset_index()
    parquet_path = out_dir / f"{station_id}.parquet"
    clean_path = out_dir / f"{station_id}.clean.parquet"
    raw.to_parquet(parquet_path, index=False)
    raw.dropna(subset=["temp_c", "pres_hpa", "rhum_pct"]).to_parquet(clean_path, index=False)
    return parquet_path, clean_path


def _load_or_fetch(
    station_id: str,
    start: datetime,
    end: datetime,
    force: bool,
) -> pd.DataFrame:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / f"{station_id}.parquet"
    if cache.exists() and not force:
        cached = pd.read_parquet(cache)
        return normalize_hourly(_raw_to_meteostat_shape(cached), start, end)

    df = fetch_hourly(station_id, start, end)
    df.reset_index().to_parquet(cache, index=False)
    return df


def _raw_to_meteostat_shape(cached: pd.DataFrame) -> pd.DataFrame:
    """Accept either mapped or Meteostat column names from the raw cache."""
    frame = cached.copy()
    if "timestamp" in frame.columns:
        frame = frame.set_index("timestamp")
    reverse = {v: k for k, v in METEOSTAT_TO_OURS.items()}
    if set(METEOSTAT_TO_OURS.values()) & set(frame.columns):
        frame = frame.rename(columns=reverse)
    return frame


def run(
    start: datetime = FETCH_START,
    end: datetime = FETCH_END,
    force: bool = False,
    limit_per_anchor: int = 8,
    stations_path: Path | None = None,
) -> Path:
    candidates = discover_candidates(limit_per_anchor=limit_per_anchor)
    scored: list[StationRecord] = []

    def _score_candidate(candidate: dict) -> None:
        try:
            hourly = _load_or_fetch(candidate["station_id"], start, end, force=force)
        except Exception as exc:  # noqa: BLE001 — keep the catalog run going
            print(f"DROP {candidate['station_id']} {candidate['name']} fetch failed: {exc}")
            return
        scores = completeness(hourly, start, end)
        record = StationRecord(
            station_id=candidate["station_id"],
            name=candidate["name"],
            latitude=candidate["latitude"],
            longitude=candidate["longitude"],
            elevation_m=candidate["elevation_m"],
            cluster_id=candidate["cluster_id"],
            completeness=scores,
        )
        if passes_threshold(scores):
            persist_station(record.station_id, hourly)
            scored.append(record)
            print(
                f"KEEP {record.station_id} {record.name} "
                f"T={scores['temp_c']:.2%} P={scores['pres_hpa']:.2%} H={scores['rhum_pct']:.2%}"
            )
        else:
            print(
                f"DROP {record.station_id} {record.name} "
                f"T={scores['temp_c']:.2%} P={scores['pres_hpa']:.2%} H={scores['rhum_pct']:.2%}"
            )

    for candidate in candidates:
        _score_candidate(candidate)

    north_kept = sum(1 for s in scored if s.cluster_id == "NORTH")
    if north_kept < 3:
        print("NORTH has fewer than 3 keepers; expanding Delhi search to 150 km.")
        known = {c["station_id"] for c in candidates}
        for candidate in discover_candidates(limit_per_anchor=limit_per_anchor, extra_north=True):
            if candidate["station_id"] not in known:
                candidates.append(candidate)
                _score_candidate(candidate)

    keepers, notes = select_keepers(scored)
    if len(keepers) < 5:
        shortage = f"Only {len(keepers)} stations met the 85% completeness bar."
        notes = f"{notes} {shortage}".strip() if notes else shortage
    path = write_catalog(
        catalog_document(keepers, notes=notes, start=start, end=end),
        path=stations_path or STATIONS_PATH,
    )
    print(f"Wrote {len(keepers)} stations to {path}")
    if notes:
        print(notes)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and lock the SkyGuard station catalog.")
    parser.add_argument("--force", action="store_true", help="Ignore raw cache and refetch.")
    parser.add_argument("--limit", type=int, default=8, help="Stations to consider per anchor.")
    args = parser.parse_args()
    run(force=args.force, limit_per_anchor=args.limit)


if __name__ == "__main__":
    main()
