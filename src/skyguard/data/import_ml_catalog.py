"""Import ML's 151-station catalog + buddy graph (+ optional hourly CSVs).

Expected files (gitignored, not in the ml-branch pull):

    ml/data/raw/stations.csv
    ml/data/raw/buddy_edges.csv          # or buddy columns on stations.csv
    ml/data/raw/{station_id}.csv        # hourly temp/rhum/pres

Writes data/processed/stations.json, buddy_edges.json, and optional parquet.

    python -m skyguard.data.import_ml_catalog
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from skyguard.config import (
    BUDDY_EDGES_PATH,
    ML_RAW_DIR,
    ML_SCALERS_PATH,
    PROCESSED_DIR,
    STATIONS_PATH,
)
from skyguard.data.catalog import nearest_cluster, write_catalog

DEMO_STATION_IDS = ("42181", "42182", "43003", "43057")
HOUR_MAP = {"temp": "temp_c", "rhum": "rhum_pct", "pres": "pres_hpa"}
PUBLIC_HOURS = ("temp_c", "pres_hpa", "rhum_pct")


class CatalogImportError(FileNotFoundError):
    pass


def load_scaler_ids(path: Path | None = None) -> set[str]:
    target = path or ML_SCALERS_PATH
    if not target.exists():
        return set()
    payload = json.loads(target.read_text(encoding="utf-8"))
    return {str(key) for key in payload}


def expected_raw_files(raw_dir: Path | None = None) -> dict[str, Path]:
    root = raw_dir or ML_RAW_DIR
    return {
        "stations.csv": root / "stations.csv",
        "buddy_edges.csv": root / "buddy_edges.csv",
    }


def _missing_raw_message(raw_dir: Path) -> str:
    expected = expected_raw_files(raw_dir)
    lines = [
        f"ML raw catalog not found under {raw_dir}.",
        "Copy the ML training dump here (gitignored; do not commit the CSVs):",
    ]
    for name, path in expected.items():
        mark = "ok" if path.exists() else "MISSING"
        lines.append(f"  [{mark}] {path}")
    lines.append(f"  [optional] {raw_dir / '{station_id}.csv'} hourly series")
    return "\n".join(lines)


def _pick_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    lower = {str(col).lower(): col for col in df.columns}
    for name in candidates:
        if name in df.columns:
            return name
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _series_str(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def load_stations_table(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"station_id": str})
    if "station_id" not in df.columns:
        raise CatalogImportError(f"{path} has no station_id column")
    df["station_id"] = df["station_id"].astype(str)
    return df


def _parse_buddy_lists(ids_raw: object, dist_raw: object) -> list[dict[str, Any]]:
    ids = [part.strip() for part in _series_str(ids_raw).split(";") if part.strip()]
    dists = [part.strip() for part in _series_str(dist_raw).split(";") if part.strip()]
    out: list[dict[str, Any]] = []
    for buddy_id, dist in zip(ids, dists):
        try:
            out.append({"station_id": buddy_id, "distance_km": float(dist)})
        except ValueError:
            continue
    return out


def graph_from_edges_csv(path: Path, exported: set[str]) -> dict[str, list[dict[str, Any]]]:
    graph: dict[str, list[dict[str, Any]]] = {sid: [] for sid in exported}
    if not path.exists():
        return graph
    edges = pd.read_csv(path, dtype=str)
    seen: dict[str, set[str]] = defaultdict(set)
    for _, row in edges.iterrows():
        left = str(row.get("primary_station_id") or row.get("station_id") or "")
        right = str(row.get("buddy_station_id") or row.get("buddy_id") or "")
        if left not in exported or right not in exported:
            continue
        try:
            distance = float(row["distance_km"])
        except (KeyError, TypeError, ValueError):
            continue
        if right not in seen[left]:
            graph[left].append({"station_id": right, "distance_km": distance})
            seen[left].add(right)
    return graph


def graph_from_station_columns(catalog: pd.DataFrame, exported: set[str]) -> dict[str, list[dict[str, Any]]]:
    ids_col = _pick_column(catalog, ("buddy_station_ids", "buddy_ids"))
    dist_col = _pick_column(catalog, ("buddy_distances_km", "buddy_distances"))
    graph: dict[str, list[dict[str, Any]]] = {sid: [] for sid in exported}
    if ids_col is None or dist_col is None:
        return graph
    for _, row in catalog.iterrows():
        sid = str(row["station_id"])
        usable = [
            item
            for item in _parse_buddy_lists(row.get(ids_col), row.get(dist_col))
            if item["station_id"] in exported
        ]
        graph[sid] = usable
    return graph


def build_buddy_graph(
    catalog: pd.DataFrame,
    edges_path: Path | None,
) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
    exported = set(catalog["station_id"].astype(str))
    if edges_path is not None and edges_path.exists():
        graph = graph_from_edges_csv(edges_path, exported)
        if any(graph.values()):
            isolates = {sid for sid in exported if len(graph.get(sid, [])) < 2}
            return graph, isolates
    graph = graph_from_station_columns(catalog, exported)
    isolates = {sid for sid in exported if len(graph.get(sid, [])) < 2}
    return graph, isolates


def _float_or_none(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def catalog_rows(
    table: pd.DataFrame,
    graph: dict[str, list[dict[str, Any]]],
    isolates: set[str],
) -> list[dict[str, Any]]:
    name_col = _pick_column(table, ("station_name", "name", "Name"))
    lat_col = _pick_column(table, ("latitude", "lat", "Latitude"))
    lon_col = _pick_column(table, ("longitude", "lon", "Longitude"))
    elev_col = _pick_column(table, ("elevation_m", "elevation", "elev", "Elevation"))
    if lat_col is None or lon_col is None:
        raise CatalogImportError(
            "stations.csv needs latitude and longitude columns (latitude/lat, longitude/lon)."
        )

    rows: list[dict[str, Any]] = []
    for _, raw in table.iterrows():
        station_id = str(raw["station_id"])
        latitude = float(raw[lat_col])
        longitude = float(raw[lon_col])
        name = _series_str(raw[name_col]) if name_col else ""
        buddies = graph.get(station_id, [])
        rows.append(
            {
                "station_id": station_id,
                "name": name or station_id,
                "latitude": latitude,
                "longitude": longitude,
                "elevation_m": _float_or_none(raw[elev_col] if elev_col else None),
                "cluster_id": nearest_cluster(latitude, longitude),
                "isolate": station_id in isolates,
                "buddy_ids": [item["station_id"] for item in buddies],
            }
        )
    return rows


def edge_list(graph: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for station_id, buddies in sorted(graph.items()):
        for buddy in buddies:
            edges.append(
                {
                    "primary_station_id": station_id,
                    "buddy_station_id": buddy["station_id"],
                    "distance_km": buddy["distance_km"],
                }
            )
    return edges


def write_buddy_edges(edges: list[dict[str, Any]], path: Path | None = None) -> Path:
    target = path or BUDDY_EDGES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_edges": len(edges),
        "edges": edges,
    }
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return target


def hours_csv_to_frame(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "timestamp" not in df.columns:
        raise CatalogImportError(f"{path} has no timestamp column")
    frame = df.rename(columns=HOUR_MAP).copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    for column in PUBLIC_HOURS:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame = frame.drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    return frame[["timestamp", *PUBLIC_HOURS]]


def persist_hours(station_id: str, df: pd.DataFrame, processed_dir: Path) -> Path:
    processed_dir.mkdir(parents=True, exist_ok=True)
    path = processed_dir / f"{station_id}.parquet"
    df.to_parquet(path, index=False)
    return path


def convert_hours(
    raw_dir: Path,
    station_ids: list[str],
    processed_dir: Path,
) -> tuple[list[str], list[str]]:
    written: list[str] = []
    skipped: list[str] = []
    for station_id in station_ids:
        csv_path = raw_dir / f"{station_id}.csv"
        if not csv_path.exists():
            skipped.append(station_id)
            continue
        frame = hours_csv_to_frame(csv_path)
        persist_hours(station_id, frame, processed_dir)
        written.append(station_id)
    return written, skipped


def import_ml_catalog(
    raw_dir: Path | None = None,
    stations_path: Path | None = None,
    edges_out: Path | None = None,
    processed_dir: Path | None = None,
    scalers_path: Path | None = None,
    convert_station_hours: bool = True,
) -> dict[str, Any]:
    root = raw_dir or ML_RAW_DIR
    stations_csv = root / "stations.csv"
    if not stations_csv.exists():
        raise CatalogImportError(_missing_raw_message(root))

    table = load_stations_table(stations_csv)
    edges_csv = root / "buddy_edges.csv"
    graph, isolates = build_buddy_graph(table, edges_csv if edges_csv.exists() else None)
    stations = catalog_rows(table, graph, isolates)
    scaler_ids = load_scaler_ids(scalers_path or ML_SCALERS_PATH)
    imported_ids = {row["station_id"] for row in stations}
    missing_scalers = sorted(imported_ids - scaler_ids) if scaler_ids else []
    missing_catalog = sorted(scaler_ids - imported_ids) if scaler_ids else []

    document = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": str(stations_csv),
        "n_stations": len(stations),
        "n_isolates": len(isolates),
        "notes": (
            "Imported from ML catalog. cluster_id is a UI region tag only; "
            "QC uses buddy_ids. isolate = fewer than 2 exported buddies."
        ),
        "stations": stations,
    }
    catalog_path = write_catalog(document, path=stations_path or STATIONS_PATH)
    edges_path = write_buddy_edges(edge_list(graph), path=edges_out or BUDDY_EDGES_PATH)

    hours_written: list[str] = []
    hours_skipped: list[str] = []
    if convert_station_hours:
        hours_written, hours_skipped = convert_hours(
            root,
            [row["station_id"] for row in stations],
            processed_dir or PROCESSED_DIR,
        )

    return {
        "catalog_path": catalog_path,
        "edges_path": edges_path,
        "n_stations": len(stations),
        "n_isolates": len(isolates),
        "isolates": sorted(isolates),
        "missing_scalers": missing_scalers,
        "missing_catalog": missing_catalog,
        "hours_written": hours_written,
        "hours_skipped": hours_skipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import ML stations.csv + buddy graph.")
    parser.add_argument("--raw-dir", type=Path, default=None, help="Default ml/data/raw")
    parser.add_argument("--no-hours", action="store_true", help="Skip parquet conversion.")
    args = parser.parse_args()
    try:
        result = import_ml_catalog(raw_dir=args.raw_dir, convert_station_hours=not args.no_hours)
    except CatalogImportError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Wrote {result['n_stations']} stations to {result['catalog_path']}")
    print(f"Wrote {result['edges_path']} ({result['n_isolates']} isolates)")
    if result["missing_catalog"]:
        print(f"WARN scaler ids missing from catalog: {len(result['missing_catalog'])}")
    if result["missing_scalers"]:
        print(f"WARN catalog ids without scaler: {len(result['missing_scalers'])}")
    if result["hours_written"] or result["hours_skipped"]:
        print(
            f"Parquet written for {len(result['hours_written'])} stations; "
            f"skipped {len(result['hours_skipped'])} without CSV"
        )


if __name__ == "__main__":
    main()
