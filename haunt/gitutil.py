"""Thin git wrappers — subprocess only, no GitPython.

All parsing is tuned for the data haunt needs per file: commit dates,
authors, subjects, and the changed-file lists. One `git log --name-only`
pass feeds the whole scanner to keep large repos workable.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

RS = "\x1e"  # record separator
US = "\x1f"  # unit separator

PASS_FILES_CAP = 5000


class GitError(RuntimeError):
    """git returned a failure haunt cannot recover from."""


def run(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def run_bytes(root: Path, *args: str, check: bool = True) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise GitError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def is_repo(root: Path) -> bool:
    try:
        return run(root, "rev-parse", "--git-dir", check=False) != ""
    except OSError:
        return False


def ls_files(root: Path) -> list[str]:
    out = run(root, "-c", "core.quotePath=false", "ls-files")
    return [line.strip() for line in out.splitlines() if line.strip()]


@dataclass
class FileHistory:
    path: str
    dates: list[int] = field(default_factory=list)          # unix commit dates, newest-first once sorted
    authors: list[tuple[str, int]] = field(default_factory=list)
    last_subjects: list[str] = field(default_factory=list)  # recent first, capped at 5


def has_commits(root: Path) -> bool:
    """False for an empty repository (unborn HEAD)."""
    try:
        return run(root, "rev-parse", "--verify", "-q", "HEAD", check=False) != ""
    except OSError:
        return False


def file_history(root: Path) -> dict[str, FileHistory]:
    """One-pass per-file commit history for the current branch (first-parent).

    Merge commits carry no file list in default log output, exactly matching
    haunt's rule that merges are skipped. Returns a dict keyed by
    repo-relative posix path.
    """
    if not has_commits(root):
        return {}
    fmt = RS + "%H" + US + "%at" + US + "%an" + US + "%s"
    out = run(
        root, "-c", "core.quotePath=false", "log", f"--format={fmt}", "--name-only"
    )
    histories: dict[str, FileHistory] = {}
    header: tuple[int, str, str] | None = None
    pending: list[str] = []

    def commit(header: tuple[int, str, str], files: list[str]) -> None:
        ts, author, subject = header
        for path in files:
            rec = histories.get(path)
            if rec is None:
                rec = FileHistory(path=path)
                histories[path] = rec
            rec.dates.append(ts)
            rec.authors.append((author, ts))
            rec.last_subjects.append(subject)

    for line in out.split("\n"):
        line = line.rstrip("\r")
        if line.startswith(RS):
            if header is not None:
                commit(header, pending)
            fields = line[1:].split(US)
            ts = int(fields[1]) if len(fields) > 1 and fields[1].lstrip("-").isdigit() else 0
            author = fields[2] if len(fields) > 2 else ""
            subject = fields[3] if len(fields) > 3 else ""
            header = (ts, author, subject)
            pending = []
        elif line and header is not None:
            pending.append(line.strip())
    if header is not None:
        commit(header, pending)

    for rec in histories.values():
        rec.dates.sort(reverse=True)
        del rec.last_subjects[5:]
    return histories


@dataclass
class HeadCommit:
    hash: str
    subject: str
    body: str
    insertions: int
    deletions: int
    files: list[str]           # up to 10 paths
    total_files: int
    diff_excerpt: str = ""     # at most ~4KB, only used when a persona asks


def head_commit(root: Path) -> HeadCommit | None:
    """Facts about HEAD. Returns None for empty or merge commits, or mid-rebase."""
    if rebase_in_progress(root):
        return None
    parents = run(root, "rev-list", "--parents", "-n", "1", "HEAD").split()
    if len(parents) > 2:  # hash + 2+ parents = merge commit
        return None
    fmt = US.join(["%H", "%s", "%b"])
    fields = run(
        root, "-c", "core.quotePath=false", "log", "-1", f"--format={fmt}"
    ).split(US)
    if len(fields) < 2:
        return None
    commit_hash, subject = fields[0], fields[1]
    body = fields[2].strip() if len(fields) > 2 else ""
    if not subject:
        return None

    files: list[str] = []
    insertions = deletions = 0
    stat_out = run(
        root, "-c", "core.quotePath=false",
        "diff-tree", "--no-commit-id", "--root", "-r", "HEAD", "--numstat",
    )
    for line in stat_out.split("\n"):
        line = line.rstrip("\r")
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        ins, dele, path = parts[0], parts[1], "\t".join(parts[2:])
        if path:
            files.append(path)
        if ins.isdigit():
            insertions += int(ins)
        if dele.isdigit():
            deletions += int(dele)

    if not files:
        return None  # empty commit — nothing to whisper about

    excerpt = ""
    try:
        full = run_bytes(
            root, "show", "--no-color", "--no-ext-diff", "--unified=2", "HEAD", "--"
        )
        excerpt = full.decode("utf-8", "replace")[:4096]
    except GitError:
        excerpt = ""

    return HeadCommit(
        hash=commit_hash,
        subject=subject,
        body=body[:500],
        insertions=insertions,
        deletions=deletions,
        files=files[:10],
        total_files=len(files),
        diff_excerpt=excerpt,
    )


def rebase_in_progress(root: Path) -> bool:
    action = os.environ.get("GIT_REFLOG_ACTION", "")
    if "rebase" in action.lower():
        return True
    git_dir = Path(run(root, "rev-parse", "--absolute-git-dir").strip())
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()
