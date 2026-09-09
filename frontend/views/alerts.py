"""Alerts page — filled in F10."""

from __future__ import annotations

from chrome import get_client, page_header, show_flash


def render_alerts() -> None:
    show_flash()
    page_header(
        "Alerts",
        "Newest first. Genuine weather stays amber; hardware is rose.",
        get_client().health(),
    )
