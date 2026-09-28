"""Outbound webhook for pages. One POST per event, off the ingest thread.

Configured by `SKYGUARD_WEBHOOK_URL`. Two events leave the building:

- `station_status_changed` — 7-day status moved into or out of DEGRADED / CRITICAL.
- `alert_opened` — a hardware alert with severity HIGH or CRITICAL.

Weather never pages. Unconfirmed never pages. Ingest never waits on the network.
"""

from __future__ import annotations

import json
import os
import queue
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

PAGE_STATUSES = {"DEGRADED", "CRITICAL"}
PAGE_SEVERITIES = {"HIGH", "CRITICAL"}
HARDWARE_LABELS = {"PHYSICAL_FAULT", "HARDWARE_ANOMALY"}
_TIMEOUT_SECONDS = 4.0
_QUEUE_MAX = 500


@dataclass
class WebhookStatus:
    configured: bool = False
    sent: int = 0
    failed: int = 0
    last_sent: datetime | None = None
    last_error: str | None = None
    last_event: str | None = None


@dataclass
class WebhookEvent:
    event: str
    station_id: str
    timestamp: datetime
    station_name: str | None = None
    status: str | None = None
    previous_status: str | None = None
    health_score: float | None = None
    label: str | None = None
    fault_type: str | None = None
    severity: str | None = None
    reason: str | None = None
    alert_id: int | None = None
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def body(self) -> dict[str, Any]:
        raw = asdict(self)
        return {
            key: (value.isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else value)
            for key, value in raw.items()
        }


def should_page_status(previous: str | None, current: str) -> bool:
    """Page on entering DEGRADED/CRITICAL, on CRITICAL from DEGRADED, and on recovery to HEALTHY."""
    if previous == current:
        return False
    if current in PAGE_STATUSES:
        return True
    return previous in PAGE_STATUSES and current == "HEALTHY"


def should_page_alert(label: str | None, severity: str | None) -> bool:
    return label in HARDWARE_LABELS and severity in PAGE_SEVERITIES


class Notifier:
    """Fire-and-forget POSTs on a daemon thread. `None` url means disabled."""

    def __init__(self, url: str | None, transport: httpx.BaseTransport | None = None) -> None:
        self.url = (url or "").strip() or None
        self.status = WebhookStatus(configured=self.url is not None)
        self._queue: queue.Queue[WebhookEvent | None] = queue.Queue(maxsize=_QUEUE_MAX)
        self._client = httpx.Client(timeout=_TIMEOUT_SECONDS, transport=transport)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        if self.url is not None:
            self._thread = threading.Thread(target=self._loop, name="skyguard-webhook", daemon=True)
            self._thread.start()

    @property
    def enabled(self) -> bool:
        return self.url is not None

    def notify(self, event: WebhookEvent) -> bool:
        if not self.enabled:
            return False
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            with self._lock:
                self.status.failed += 1
                self.status.last_error = "webhook queue full"
            return False
        return True

    def flush(self, timeout: float = 5.0) -> None:
        """Block until queued events were attempted. Tests only."""
        deadline = datetime.now(timezone.utc).timestamp() + timeout
        while not self._queue.empty() and datetime.now(timezone.utc).timestamp() < deadline:
            threading.Event().wait(0.02)
        self._queue.join()

    def close(self) -> None:
        if self._thread is not None:
            self._queue.put(None)
            self._thread.join(timeout=2.0)
        self._client.close()

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                return
            try:
                self._send(item)
            finally:
                self._queue.task_done()

    def _send(self, event: WebhookEvent) -> None:
        assert self.url is not None
        try:
            response = self._client.post(
                self.url,
                content=json.dumps(event.body()),
                headers={"Content-Type": "application/json", "User-Agent": "SkyGuard/0.1"},
            )
            ok = 200 <= response.status_code < 300
            with self._lock:
                self.status.last_event = event.event
                if ok:
                    self.status.sent += 1
                    self.status.last_sent = datetime.now(timezone.utc)
                    self.status.last_error = None
                else:
                    self.status.failed += 1
                    self.status.last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            with self._lock:
                self.status.failed += 1
                self.status.last_error = str(exc)[:200]
                self.status.last_event = event.event


def notifier_from_env() -> Notifier:
    return Notifier(os.environ.get("SKYGUARD_WEBHOOK_URL"))
