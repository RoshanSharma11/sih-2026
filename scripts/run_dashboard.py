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
    raise SystemExit(
        subprocess.call(
            [sys.executable, "-m", "streamlit", "run", str(APP), "--server.headless=false"],
            cwd=ROOT,
        )
    )


if __name__ == "__main__":
    main()
