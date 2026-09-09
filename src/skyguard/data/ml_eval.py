"""Shim — the shareable file is ``scripts/simulate_corruption_eval.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "simulate_corruption_eval.py"
_SPEC = importlib.util.spec_from_file_location("simulate_corruption_eval", _SCRIPT)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Cannot load {_SCRIPT}")
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

OUTPUT_COLS = _MOD.OUTPUT_COLS
simulate_corruption = _MOD.simulate_corruption
plot_eval_results = _MOD.plot_eval_results
run = _MOD.run
main = _MOD.main
