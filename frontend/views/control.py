"""Control page — filled in F10."""

from __future__ import annotations

from chrome import get_client, page_header, show_flash


def render_control() -> None:
    show_flash()
    page_header(
        "Control",
        "Arm a neighborhood storm or a single-station fault. The streamer stays clean.",
        get_client().health(),
    )
