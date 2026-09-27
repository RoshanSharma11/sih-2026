"""151-station catalog + 100 km buddy graph."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd

from .config import CATALOG_PATH, EDGES_PATH


def load_catalog(path: Path | None = None) -> pd.DataFrame:
    path = path or CATALOG_PATH
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, dtype={"station_id": str})
    df["station_id"] = df["station_id"].astype(str)
    return df


def build_buddy_graph(catalog: pd.DataFrame) -> tuple[dict, set[str], set[str]]:
    if catalog.empty:
        return {}, set(), set()
    exported = set(catalog["station_id"].astype(str))
    graph: dict[str, list[dict]] = {sid: [] for sid in exported}
    path = EDGES_PATH
    if path.exists():
        edges = pd.read_csv(path, dtype=str)
        seen: dict[str, set[str]] = defaultdict(set)
        for _, row in edges.iterrows():
            a = str(row["primary_station_id"])
            b = str(row["buddy_station_id"])
            if a not in exported or b not in exported:
                continue
            try:
                dkm = float(row["distance_km"])
            except (TypeError, ValueError):
                continue
            if b not in seen[a]:
                graph[a].append({"station_id": b, "distance_km": dkm})
                seen[a].add(b)
    isolates = {sid for sid in exported if len(graph.get(sid, [])) < 2}
    return graph, exported, isolates
