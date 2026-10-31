"""Shared fixtures: a real git repo with planted ghosts.

The fixture is built with actual commits (historical dates via env
overrides) so the scanner is tested against genuine git output, not mocks
of shapes we guessed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

GRETA = ("Greta Vane", "greta@haunt.local")
ARIA = ("Aria Mercer", "aria@haunt.local")
TODAY_AUTHORS = ("Pip Rook", "pip@haunt.local")


def commit(
    cwd: Path, message: str, name: str, email: str, date: str, paths: list[str] | None = None
) -> None:
    env = {
        **__import__("os").environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_DATE": date,
    }
    subprocess.run(["git", "add", "-A"], cwd=cwd, check=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
    )


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def write(path: Path, text: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")


@pytest.fixture(scope="session")
def ghost_repo(tmp_path_factory) -> Path:
    """A tiny repo with one of each haunting plus known skips."""
    repo = tmp_path_factory.mktemp("fx") / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Pip Rook")
    git(repo, "config", "user.email", "pip@haunt.local")
    git(repo, "config", "commit.gpgsign", "false")

    # guitar: Greta's 2021 orphan — no one active in 180d+ (older than age rule)
    write(repo / "ghosts" / "orphan_litany.py", "LITANY = [\n"
                                              "    'the door',\n"
                                              "    'the stairs',\n"
                                              "    'the attic',\n"
                                              "]\n")
    commit(repo, "add litany of the orphans", *GRETA, "2021-03-01T12:00:00")

    # aria's file last touched ~100d ago: not within 90d churn window,
    # still within 180d authorship window -> Sleeper, not orphan
    write(repo / "cellar" / "keeper.py", "def keep():\n    return 47\n")
    commit(repo, "keeper settles into the cellar", *ARIA, "2026-07-20T12:00:00")

    # revenant: born long ago, silent, then suddenly touched again
    write(repo / "crypt" / "revenant.py", "DORMANT = True\n")
    commit(repo, "crypt laid and sealed", *GRETA, "2025-01-10T12:00:00")
    write(repo / "crypt" / "revenant.py", "DORMANT = False\nRETIRED = 'no longer'\n")
    commit(repo, "the revenant stirs once more", *TODAY_AUTHORS, "2026-10-20T12:00:00")

    # poltergeist: lots of churn, two authors, all within 90d
    for i in range(12):
        who = (GRETA, ARIA)[i % 2]
        write(repo / "manor" / "poltergeist.py", f"NOISE = {i}\n")
        commit(repo, f"rattle the manor {i}", *who, f"2026-08-{(i % 27) + 1:02d}T12:00:00")

    # high debt: saturated TODO markers
    write(
        repo / "debt" / "ledger.py",
        ("# TODO bury this\n" * 6) + ("# FIXME wake this\n" * 5) + "LEDGER = 13\n",
    )
    commit(repo, "ledger of unsettled debts", *TODAY_AUTHORS, "2026-10-29T12:00:00")

    # skips: lockfile, vendored, binary
    write(repo / "chants.lock", "lock-version = 1\n")
    write(repo / "vendor" / "old" / "seance.js", "console.log('seance')\n")
    write(repo / "portrait.png", bytes(200))

    commit(repo, "final rites and skips", *TODAY_AUTHORS, "2026-10-30T12:00:00")
    return repo
