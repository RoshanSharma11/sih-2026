"""Repo root must resolve under Docker even when the package is in site-packages."""

from __future__ import annotations

from pathlib import Path

from skyguard.config import REPO_ROOT, STATIONS_PATH, _looks_like_repo, _resolve_repo_root


def test_local_repo_root_finds_catalog_and_v2() -> None:
    assert _looks_like_repo(REPO_ROOT)
    assert STATIONS_PATH.is_file()
    assert (REPO_ROOT / "v2-deliverable" / "v2" / "artifacts" / "scalers.json").is_file()


def test_skyguard_root_env_overrides(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "v2-deliverable").mkdir()
    monkeypatch.setenv("SKYGUARD_ROOT", str(tmp_path))
    assert _resolve_repo_root() == tmp_path.resolve()
