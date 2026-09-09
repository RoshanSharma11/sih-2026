"""Station catalog: exported 151 stations + buddy distances among them."""

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


def _graph_from_edges(exported: set[str], path: Path) -> dict[str, list[dict]]:
    graph: dict[str, list[dict]] = {sid: [] for sid in exported}
    if not path.exists():
        return graph
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
    return graph


def _graph_from_catalog_columns(catalog: pd.DataFrame, exported: set[str]) -> dict[str, list[dict]]:
    graph: dict[str, list[dict]] = {}
    for _, row in catalog.iterrows():
        sid = str(row["station_id"])
        raw_ids = str(row.get("buddy_station_ids") or "")
        raw_d = str(row.get("buddy_distances_km") or "")
        ids = [x.strip() for x in raw_ids.split(";") if x.strip()]
        dists = [x.strip() for x in raw_d.split(";") if x.strip()]
        usable = []
        for bid, dist in zip(ids, dists):
            if bid not in exported:
                continue
            try:
                dkm = float(dist)
            except ValueError:
                continue
            usable.append({"station_id": bid, "distance_km": dkm})
        graph[sid] = usable
    return graph


def build_buddy_graph(catalog: pd.DataFrame) -> tuple[dict, set[str], set[str]]:
    """
    Buddies restricted to other exported stations.

    Isolates = exported stations with fewer than 2 exported buddies.
    That includes the original six with zero exported neighbors, plus
    stations that only have a single exported neighbor (IDW needs two).

    Returns:
        graph: station_id -> [{station_id, distance_km}, ...]
        exported: all catalog ids
        isolates: exported stations with fewer than 2 exported buddies
    """
    if catalog.empty:
        return {}, set(), set()

    exported = set(catalog["station_id"].astype(str))
    if EDGES_PATH.exists():
        graph = _graph_from_edges(exported, EDGES_PATH)
    else:
        graph = _graph_from_catalog_columns(catalog, exported)

    isolates = {sid for sid in exported if len(graph.get(sid, [])) < 2}
    return graph, exported, isolates
