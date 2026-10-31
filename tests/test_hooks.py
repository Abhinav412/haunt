"""Hook lifecycle: install is idempotent, uninstall is surgical, and the
real user flow — an actual `git commit` — produces a whisper (community
lesson: never trust a re-read of the hook script; run the exact flow).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from haunt.cli import HOOK_BEGIN, HOOK_END, app

DEAD_HOST = "http://127.0.0.1:9"


def _copy(repo: Path, tmp_path: Path) -> Path:
    copy = tmp_path / "repo"
    shutil.copytree(repo, copy)
    return copy


def _run_hook_script(repo: Path, hook: Path, env: dict) -> subprocess.CompletedProcess:
    """Execute the hook file exactly as git would, via Git for Windows' sh.

    Windows has no sh on PATH, and system32/bash.exe is WSL — never use it.
    Git bundles its own sh next to its cmd dir.
    """
    exe = shutil.which("sh")
    if not exe:
        try:
            exec_path = subprocess.run(
                ["git", "--exec-path"], capture_output=True, encoding="utf-8", check=True
            ).stdout.strip()
            base = Path(exec_path)  # e.g. Git/mingw64/libexec/git-core
            for ancestor in (base, *base.parents):
                candidate = ancestor / "usr" / "bin" / "sh.exe"
                if candidate.is_file():
                    exe = str(candidate)
                    break
        except (subprocess.SubprocessError, OSError):
            exe = None
    if not exe:
        # last resort: git's experimental hook runner
        return subprocess.run(
            ["git", "hook", "run", "post-commit"],
            cwd=repo,
            env=env,
            capture_output=True,
            encoding="utf-8",
        )
    return subprocess.run(
        [exe, str(hook)], cwd=repo, env=env, capture_output=True, encoding="utf-8"
    )


def _count_markers(hook: Path) -> int:
    text = hook.read_text(encoding="utf-8")
    return text.count(HOOK_BEGIN) + text.count(HOOK_END)


def _hook(repo: Path) -> Path:
    return repo / ".git" / "hooks" / "post-commit"


def test_install_uninstall_lifecycle(ghost_repo: Path, tmp_path: Path, monkeypatch) -> None:
    repo = _copy(ghost_repo, tmp_path)
    monkeypatch.chdir(repo)
    runner = CliRunner()
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0, result.output
    hook = _hook(repo)
    assert hook.is_file()
    assert hook.read_text(encoding="utf-8").startswith("#!/bin/sh")
    assert _count_markers(hook) == 2  # one BEGIN, one END
    assert "-m haunt whisper" in hook.read_text(encoding="utf-8")

    # idempotent: a second install does not duplicate the block
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0, result.output
    assert _count_markers(hook) == 2

    # uninstall removes only the block
    result = runner.invoke(app, ["uninstall"])
    assert result.exit_code == 0, result.output
    assert _count_markers(hook) == 0


def test_install_backs_up_existing_hook(ghost_repo: Path, tmp_path: Path, monkeypatch) -> None:
    repo = _copy(ghost_repo, tmp_path)
    monkeypatch.chdir(repo)
    hook_dir = repo / ".git" / "hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)
    original = hook_dir / "post-commit"
    original.write_text("#!/bin/sh\necho pre-existing\nexit 0\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0, result.output
    assert "backed up" in result.output
    text = original.read_text(encoding="utf-8")
    assert "pre-existing" in text  # original logic survived
    assert HOOK_BEGIN in text      # haunt block prepended after shebang
    assert _count_markers(original) == 2

    backups = list(hook_dir.glob("post-commit.pre-haunt.*"))
    assert backups, "a backup of the original hook was made"
    assert backups[0].read_text(encoding="utf-8") == "#!/bin/sh\necho pre-existing\nexit 0\n"


def test_real_git_commit_runs_the_hook(ghost_repo: Path, tmp_path: Path, monkeypatch) -> None:
    repo = _copy(ghost_repo, tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HAUNT_HOST", DEAD_HOST)  # inherited by the hook subprocess
    runner = CliRunner()
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0, result.output

    # the exact user flow: change a file, commit for real
    (repo / "manor" / "poltergeist.py").write_text("NOISE = 99\n", encoding="utf-8")
    committed = subprocess.run(
        ["git", "commit", "-am", "slam the manor shut"],
        cwd=repo,
        capture_output=True,
        encoding="utf-8",
    )
    assert committed.returncode == 0, committed.stderr
    combined = committed.stdout + committed.stderr
    assert committed.returncode == 0
    # the whisper ran through the real hook chain and printed a fallback line
    whisper_ran = ("🕯️" in combined) or ("👻" in combined) or ("haunt:" in combined)
    assert whisper_ran, f"no whisper in commit output:\n{combined}"


def test_hook_script_executes_standalone(ghost_repo: Path, tmp_path: Path, monkeypatch) -> None:
    """Run .git/hooks/post-commit exactly as git would, with no changed files."""
    repo = _copy(ghost_repo, tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HAUNT_HOST", DEAD_HOST)
    runner = CliRunner()
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0, result.output

    hook = _hook(repo)
    env = {**os.environ, "GIT_REFLOG_ACTION": "rebase"}  # mid-rebase: must stay silent
    run = _run_hook_script(repo, hook, env)
    assert run.returncode == 0
    assert run.stdout.strip() == ""  # rebase rule: no whisper
