"""Open the Streamlit demo console against the running API."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend" / "app.py"


def main() -> None:
    os.chdir(ROOT)
    # Pin light theme on the CLI so deploy (wrong cwd / OS dark mode) cannot
    # leave Streamlit bodyText white on our forced white sidebar.
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(APP),
                "--server.headless=false",
                "--theme.base=light",
                "--theme.primaryColor=#0D9488",
                "--theme.backgroundColor=#F8FAFC",
                "--theme.secondaryBackgroundColor=#FFFFFF",
                "--theme.textColor=#0F172A",
            ],
            cwd=ROOT,
        )
    )


if __name__ == "__main__":
    main()
