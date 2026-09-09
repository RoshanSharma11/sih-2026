"""Guide page — filled in F11."""

from __future__ import annotations

from chrome import page_header


def render_guide() -> None:
    page_header(
        "How QC works",
        "Physical rules, then LSTM, then a two-buddy check. Delhi does not validate Mumbai.",
    )
