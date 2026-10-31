"""Deterministic fallback behavior: same commit, same template, forever, offline."""

from __future__ import annotations

from pathlib import Path

import os

from typer.testing import CliRunner

from haunt.cli import app
from haunt.prompts import fallback_whisper
from haunt.config import load_persona

DEAD_HOST = "http://127.0.0.1:9"  # reserved port, refuses instantly


def test_fallback_is_deterministic(ghost_repo: Path, monkeypatch) -> None:
    persona = load_persona("victorian", ghost_repo)
    first = fallback_whisper(persona, "abc123")
    second = fallback_whisper(persona, "abc123")
    assert first == second
    assert first in persona["fallbacks"]
    # a different commit yields a possibly different but always-valid line
    assert fallback_whisper(persona, "def456") in persona["fallbacks"]


def test_whisper_cli_prints_fallback_when_ollama_absent(
    ghost_repo: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HAUNT_HOST", DEAD_HOST)
    monkeypatch.chdir(ghost_repo)
    runner = CliRunner()
    first = runner.invoke(app, ["whisper"])
    second = runner.invoke(app, ["whisper"])
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert first.output == second.output
    assert "🕯️" in first.output  # victorian persona emoji, dim-wrapped


def test_whisper_prints_nothing_at_null_commit(ghost_repo: Path, monkeypatch) -> None:
    # whisper with no changes to HEAD must exit 0 silently (merge/empty rule
    # is exercised by the same gate: head_commit returns None)
    monkeypatch.setenv("HAUNT_HOST", DEAD_HOST)
    monkeypatch.chdir(ghost_repo)
    runner = CliRunner()
    result = runner.invoke(app, ["whisper"])
    assert result.exit_code == 0
    assert "🕯️" in result.output  # a commit exists, so it whispers


def test_probe_reports_down_without_raising(ghost_repo: Path, monkeypatch) -> None:
    from haunt.config import Config
    from haunt.llm import Ghost

    cfg = Config(root=ghost_repo, host=DEAD_HOST)
    probe = Ghost(cfg).probe()
    assert probe.status == "down"
    assert Ghost(cfg).hint(probe) is not None


def test_env_overrides_config_file(tmp_path: Path, monkeypatch) -> None:
    import tomllib
    from haunt.config import load_config, repo_root, Config

    (tmp_path / "target" / ".git").mkdir(parents=True)
    (tmp_path / "target" / ".haunt.toml").write_text(
        'model = "llama3.2:3b"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path / "target")
    monkeypatch.delenv("HAUNT_MODEL", raising=False)
    cfg = load_config()
    assert cfg.model == "llama3.2:3b"
    monkeypatch.setenv("HAUNT_MODEL", "gemma2:2b")
    cfg = load_config()
    assert cfg.model == "gemma2:2b"  # env wins for CI pinning
