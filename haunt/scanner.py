"""Haunting score per tracked file — computed from git history alone.

No model involvement here: the deterministic score is what makes the flavor
responsible (see prompts.py) and keeps haunt honest when the model is absent.
"""

from __future__ import annotations

import fnmatch
import re
import time
from dataclasses import dataclass
from pathlib import Path

from . import gitutil
from .config import Config

DAY = 86_400
CHURN_NORM = 20.0        # commits in 90d that saturate `restless`
DEBT_NORM = 10.0         # debt markers that saturate `debt`
SIZE_NORM = 500.0        # lines of code that saturate the size factor
REVENANT_GAP = 270       # days of silence that count as a long dormancy
MAX_READ_BYTES = 256_000
MAX_FILES = gitutil.PASS_FILES_CAP

TYPES = ("Sleeper", "Poltergeist", "Revenant", "Orphan spirit")

DEBT_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".tiff",
    ".pdf", ".zip", ".gz", ".tar", ".rar", ".7z", ".exe", ".dll", ".so",
    ".dylib", ".bin", ".o", ".a", ".lib", ".class", ".jar", ".war", ".pyc",
    ".pyo", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4",
    ".mov", ".avi", ".wav", ".flac", ".ogg", ".sqlite", ".sqlite3", ".db",
    ".iso", ".h5", ".pkl", ".pickle", ".asset", ".unity", ".blend", ".psd",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
}

BUILTIN_DIRS = (
    "node_modules", "vendor", "dist", "build", "out", ".venv", "venv",
    "target", "__pycache__", ".git", ".tox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".next", ".cache", "coverage", ".idea", ".vscode",
)
BUILTIN_GLOBS = (
    "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "go.sum",
    "poetry.lock", "Pipfile.lock", "*.min.js", "*.min.css", "*.bundle.js",
    "*.svgz",
)


@dataclass
class FileScore:
    path: str
    score: float
    htype: str
    age_days: float
    churn_90d: int
    authors_total: int
    authors_active: int
    orphaned: bool
    debt_markers: int
    size_loc: int

    @property
    def metrics_line(self) -> str:
        return (
            f"age {self.age_days:.0f}d | churn90 {self.churn_90d} | "
            f"authors {self.authors_active}/{self.authors_total} | "
            f"TODO/FIXME {self.debt_markers} | {self.size_loc} loc"
        )


def _ignored(path: str, globs: tuple[str, ...]) -> bool:
    """Match a repo-relative posix path against dir names and glob patterns."""
    parts = path.split("/")
    for pattern in globs:
        if pattern.endswith("/**"):
            prefix = pattern[: -len("/**")]
            if path.startswith(prefix + "/"):
                return True
        elif "/" in pattern:
            if fnmatch.fnmatch(path, pattern):
                return True
        else:
            if any(fnmatch.fnmatch(segment, pattern) for segment in parts):
                return True
    return False


def skip_reason(path: str, cfg: Config) -> str | None:
    parts = path.split("/")
    base = parts[-1]
    for directory in BUILTIN_DIRS:
        if directory in parts:
            return "vendored/generated dir"
    for pattern in BUILTIN_GLOBS:
        if fnmatch.fnmatch(base, pattern) or fnmatch.fnmatch(path, pattern):
            return "generated/lockfile"
    ext = Path(base).suffix.lower()
    if ext in BINARY_EXTS:
        return "binary"
    if _ignored(path, tuple(cfg.ignore)):
        return "ignored by .haunt.toml"
    return None


class Scanner:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.warnings: list[str] = []

    # ---------------------------------------------------------------- scoring

    def scan(self) -> list[FileScore]:
        root = self.cfg.root
        files = gitutil.ls_files(root)
        try:
            histories = gitutil.file_history(root)
        except gitutil.GitError as error:
            histories = {}
            self.warnings.append(f"history unavailable: {error}")

        now = time.time()
        kept = 0
        scores: list[FileScore] = []
        for path in files:
            reason = skip_reason(path, self.cfg)
            if reason:
                continue
            kept += 1
            if kept > MAX_FILES:
                self.warnings.append(
                    f"scan capped at {MAX_FILES} files; scores may be incomplete"
                )
                break
            history = histories.get(path)
            entry = self._score(path, history, now, root)
            if entry is not None:
                scores.append(entry)
        scores.sort(key=lambda s: s.score, reverse=True)
        self.scanned = kept
        self.total_tracked = len(files)
        self.histories = histories
        return scores

    def _score(
        self, path: str, history: gitutil.FileHistory | None, now: float, root: Path
    ) -> FileScore | None:
        if history is None or not history.dates:
            # tracked on disk but not in current-branch history: skip quietly
            return None
        newest = float(history.dates[0])
        # quantize to whole hours so repeated scans print stable numbers
        age_hours = max(0, int((now - newest) / 3_600))
        age_days = age_hours / 24.0
        churn_90d = sum(1 for d in history.dates if (now - d) <= 90 * DAY)
        authors_total = len({a for a, _ in history.authors} - {""})
        cutoff_180 = now - 180 * DAY
        authors_active = len(
            {a for a, ts in history.authors if a and ts >= cutoff_180}
        )
        orphaned = authors_total > 0 and authors_active == 0

        debt, loc = self._read_markers(path, root)
        size_factor = min(loc / SIZE_NORM, 1.0)

        dormant = min(age_days / 365.0, 1.0) * size_factor
        restless = min(churn_90d / CHURN_NORM, 1.0)
        debt_norm = min(debt / DEBT_NORM, 1.0)
        orphan_component = 1.0 if orphaned else 0.0

        score = (
            self.cfg.weight("dormant") * dormant
            + self.cfg.weight("restless") * restless
            + self.cfg.weight("orphaned") * orphan_component
            + self.cfg.weight("debt") * debt_norm
        )

        return FileScore(
            path=path,
            score=score,
            htype=self._classify(
                history=history,
                age_days=age_days,
                churn_90d=churn_90d,
                authors_active=authors_active,
                orphaned=orphaned,
                debt=debt,
            ),
            age_days=age_days,
            churn_90d=churn_90d,
            authors_total=authors_total,
            authors_active=authors_active,
            orphaned=orphaned,
            debt_markers=debt,
            size_loc=loc,
        )

    @staticmethod
    def _classify(
        *,
        history: gitutil.FileHistory,
        age_days: float,
        churn_90d: int,
        authors_active: int,
        orphaned: bool,
        debt: int,
    ) -> str:
        """Which ghost holds this file, in precedence order.

        Orphan spirit is a fact (all authors gone), not an intensity, so it
        wins first. Revenant and Poltergeist are activity profiles. Sleeper
        fires on old-but-not-abandoned files — notably reachable when an
        author is still around but has stopped touching this file for ~90d.
        """
        if orphaned:
            return "Orphan spirit"
        dates = history.dates  # newest first, unix ints (exact, no drift)
        # first-commit age only feeds a >=365d threshold; ms-level drift is
        # irrelevant there, while age_days above is hour-quantized
        first_commit_age = (time.time() - dates[-1]) / DAY
        if (
            len(dates) >= 2
            and (dates[0] - dates[1]) / DAY >= REVENANT_GAP
            and first_commit_age >= 365
            and age_days <= 90
        ):
            return "Revenant"
        if churn_90d >= 10 and authors_active >= 2:
            return "Poltergeist"
        if age_days >= 90 and churn_90d <= 1:
            return "Sleeper"
        debt_norm = min(debt / DEBT_NORM, 1.0)
        if debt_norm >= 0.4:
            return "Poltergeist"  # mischievous knocking on the same TODOs
        # tail: mildly restless files read as small poltergeists
        return "Poltergeist" if churn_90d >= 3 else "Sleeper"

    @staticmethod
    def _read_markers(path: str, root: Path) -> tuple[int, int]:
        """Count debt markers and lines by reading the working-tree file.

        Text-only, size-capped reading keeps this a single scan with no
        per-file subprocess calls; binary and huge files contribute nothing.
        """
        try:
            blob = (root / path).read_bytes()
        except OSError:
            return 0, 0
        if blob[:8192].find(b"\x00") != -1:
            return 0, 0
        text = blob.decode("utf-8", "replace")
        if len(blob) > MAX_READ_BYTES:
            text = text[:MAX_READ_BYTES]
        debt = len(DEBT_RE.findall(text))
        return debt, text.count("\n") + (0 if text.endswith("\n") or not text else 1)
