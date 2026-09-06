"""HTTP client for frozen SkyGuard REST contracts. No extra fields."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_API = "http://127.0.0.1:8000"


class SkyGuardApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Snapshot:
    ok: bool
    error: str | None = None
    stations: list[dict[str, Any]] = field(default_factory=list)
    telemetry: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    overlays: list[dict[str, Any]] = field(default_factory=list)
    selected_id: str | None = None


def merge_station(summary: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    latest = detail.get("latest")
    merged = dict(summary)
    merged["latest"] = latest
    merged["pipeline_status"] = None if not latest else latest.get("pipeline_status")
    return merged


class SkyGuardClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("SKYGUARD_API", DEFAULT_API)).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def healthz(self) -> bool:
        try:
            response = self._client.get("/healthz")
            response.raise_for_status()
        except httpx.HTTPError:
            return False
        body = response.json()
        return body.get("ok") is True

    def stations(self) -> list[dict[str, Any]]:
        return self._get_json("/stations")

    def station(self, station_id: str) -> dict[str, Any]:
        return self._get_json(f"/stations/{station_id}")

    def telemetry(self, station_id: str, limit: int = 240) -> list[dict[str, Any]]:
        return self._get_json(f"/stations/{station_id}/telemetry", params={"limit": limit})

    def alerts(self, station_id: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if station_id:
            params["station_id"] = station_id
        return self._get_json("/alerts", params=params)

    def demo_status(self) -> dict[str, Any]:
        return self._get_json("/demo/status")

    def inject(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("/demo/inject", body)

    def reset(self) -> dict[str, Any]:
        return self._post_json("/demo/reset", {})

    def snapshot(self, selected_id: str | None) -> Snapshot:
        if not self.healthz():
            return Snapshot(
                ok=False,
                error=f"API is not reachable at {self.base_url}. Start it with python scripts/run_api.py.",
            )
        try:
            summaries = self.stations()
            stations = [merge_station(row, self.station(row["station_id"])) for row in summaries]
        except SkyGuardApiError as exc:
            return Snapshot(ok=False, error=str(exc))

        if not stations:
            return Snapshot(ok=True, error="Catalog is empty. Load stations.json and restart the API.")

        ids = {row["station_id"] for row in stations}
        chosen = selected_id if selected_id in ids else stations[0]["station_id"]
        try:
            telemetry = self.telemetry(chosen)
            alerts = self.alerts(chosen)
            overlays = self.demo_status().get("overlays", [])
        except SkyGuardApiError as exc:
            return Snapshot(ok=False, error=str(exc), stations=stations, selected_id=chosen)
        return Snapshot(
            ok=True,
            stations=stations,
            telemetry=telemetry,
            alerts=alerts,
            overlays=overlays,
            selected_id=chosen,
        )

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise SkyGuardApiError(f"Request failed: {exc}") from exc
        return self._parse(response)

    def _post_json(self, path: str, body: dict[str, Any]) -> Any:
        try:
            response = self._client.post(path, json=body)
        except httpx.HTTPError as exc:
            raise SkyGuardApiError(f"Request failed: {exc}") from exc
        return self._parse(response)

    def _parse(self, response: httpx.Response) -> Any:
        if response.status_code >= 400:
            detail = _error_detail(response)
            raise SkyGuardApiError(detail, status_code=response.status_code)
        if not response.content:
            return {}
        return response.json()


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    detail = payload.get("detail", payload)
    if isinstance(detail, list):
        return "; ".join(str(item) for item in detail)
    return str(detail)
