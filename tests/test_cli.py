"""CLI surface: report files, persona switching, and listed personas."""

from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

from haunt.cli import app


def _copy(repo: Path, tmp_path: Path) -> Path:
    copy = tmp_path / "repo"
    shutil.copytree(repo, copy)
    return copy


def test_report_writes_markdown(ghost_repo: Path, tmp_path: Path, monkeypatch) -> None:
    repo = _copy(ghost_repo, tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HAUNT_HOST", "http://127.0.0.1:9")  # offline: template narrations
    runner = CliRunner()
    result = runner.invoke(app, ["report"])
    assert result.exit_code == 0, result.output
    md = repo / "HAUNTINGS.md"
    assert md.is_file()
    text = md.read_text(encoding="utf-8")
    assert "# 🪦 Hauntings Report" in text
    assert "Orphan spirit" in text          # the fixture's 2021 file must be ranked
    assert "## 📜 Ranked hauntings" in text
    assert "`ghosts/orphan_litany.py`" in text


def test_report_html_is_self_contained(ghost_repo: Path, tmp_path: Path, monkeypatch) -> None:
    repo = _copy(ghost_repo, tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HAUNT_HOST", "http://127.0.0.1:9")
    runner = CliRunner()
    result = runner.invoke(app, ["report", "--html"])
    assert result.exit_code == 0, result.output
    html = (repo / "HAUNTINGS.html").read_text(encoding="utf-8")
    assert "flicker" in html
    assert "http://" not in html and "https://" not in html  # no external assets


def test_report_uses_model_narration_when_alive(
    ghost_repo: Path, tmp_path: Path, monkeypatch
) -> None:
    """When the probe passes, the model narrates; stub generate to prove routing."""
    repo = _copy(ghost_repo, tmp_path)
    monkeypatch.chdir(repo)
    from haunt import cli, llm

    calls: list[str] = []

    def fake_generate(self, **kwargs):
        calls.append(kwargs["prompt"])  # noqa: B023
        assert kwargs["system"], "report narration needs the persona system prompt"
        return "The spirit says: write a test for this file."

    from types import SimpleNamespace

    monkeypatch.setattr(llm.Ghost, "generate", fake_generate)
    monkeypatch.setattr(
        llm.Ghost,
        "probe",
        lambda self: SimpleNamespace(status="ok", ok=True, model="stub", hint=None),
    )
    runner = CliRunner()
    result = runner.invoke(app, ["report"])
    assert result.exit_code == 0, result.output
    assert calls, "generations were attempted for narrations"
    text = (repo / "HAUNTINGS.md").read_text(encoding="utf-8")
    assert "write a test for this file." in text


def test_persona_switch_and_unknown(ghost_repo: Path, tmp_path: Path, monkeypatch) -> None:
    repo = _copy(ghost_repo, tmp_path)
    monkeypatch.chdir(repo)
    runner = CliRunner()
    listed = runner.invoke(app, ["personas"])
    assert listed.exit_code == 0
    for name in ("victorian", "poltergeist", "ancestor"):
        assert name in listed.output

    result = runner.invoke(app, ["persona", "ancestor"])
    assert result.exit_code == 0, result.output
    saved = (repo / ".haunt.toml").read_text(encoding="utf-8")
    assert 'persona = "ancestor"' in saved
    assert 'model = "gemma2:2b"' in saved  # defaults written into new config

    bad = runner.invoke(app, ["persona", "not_a_ghost"])
    assert bad.exit_code == 1
    assert "not_a_ghost" in bad.output


def test_scan_reports_empty_repo_content(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    empty = tmp_path / "empty"
    empty.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=empty, check=True, capture_output=True)
    monkeypatch.chdir(empty)
    runner = CliRunner()
    result = runner.invoke(app, ["scan"])
    assert result.exit_code == 0
    assert "at rest" in result.output
