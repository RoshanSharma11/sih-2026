#!/usr/bin/env python3
"""Thin wrapper so Roshan's command works from repo root:

    python scripts/simulate_corruption_eval.py --clean eval_out/test_2024.csv --out ./eval_out
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml"))

from simulate_corruption_eval import main

if __name__ == "__main__":
    main()
