"""Scanner correctness against a real fixture repo with planted ghosts."""

from __future__ import annotations

from pathlib import Path

from haunt.config import Config
from haunt.scanner import Scanner, skip_reason


def by_path(scores, path):
    return {s.path: s for s in scores}.get(path)


def test_known_skips_are_filtered(ghost_repo: Path) -> None:
    cfg = Config(root=ghost_repo)
    scanner = Scanner(cfg)
    scores = scanner.scan()
    paths = {s.path for s in scores}
    assert "chants.lock" not in paths
    assert "vendor/old/seance.js" not in paths
    assert "portrait.png" not in paths
    assert scanner.warnings == []


def test_skip_reason_labels(ghost_repo: Path) -> None:
    assert skip_reason("chants.lock", Config(root=ghost_repo)) is not None
    assert skip_reason("vendor/old/seance.js", Config(root=ghost_repo)) is not None
    assert skip_reason("portrait.png", Config(root=ghost_repo)) is not None
    assert skip_reason("manor/poltergeist.py", Config(root=ghost_repo)) is None


def test_orphan_spirit(ghost_repo: Path) -> None:
    scores = Scanner(Config(root=ghost_repo)).scan()
    orphan = by_path(scores, "ghosts/orphan_litany.py")
    assert orphan is not None
    assert orphan.htype == "Orphan spirit"
    assert orphan.orphaned is True
    assert orphan.authors_total == 1
    assert orphan.authors_active == 0
    assert orphan.age_days > 180


def test_sleeper_is_old_and_quiet_but_not_orphaned(ghost_repo: Path) -> None:
    scores = Scanner(Config(root=ghost_repo)).scan()
    sleeper = by_path(scores, "cellar/keeper.py")
    assert sleeper is not None
    assert sleeper.htype == "Sleeper"
    assert sleeper.orphaned is False
    assert sleeper.age_days >= 90
    assert sleeper.churn_90d == 0


def test_revenant(ghost_repo: Path) -> None:
    scores = Scanner(Config(root=ghost_repo)).scan()
    revenant = by_path(scores, "crypt/revenant.py")
    assert revenant is not None
    assert revenant.htype == "Revenant"
    assert revenant.age_days <= 90


def test_poltergeist_has_churn_and_many_authors(ghost_repo: Path) -> None:
    scores = Scanner(Config(root=ghost_repo)).scan()
    polter = by_path(scores, "manor/poltergeist.py")
    assert polter is not None
    assert polter.htype == "Poltergeist"
    assert polter.churn_90d >= 10
    assert polter.authors_total >= 2


def test_debt_markers_saturate(ghost_repo: Path) -> None:
    scores = Scanner(Config(root=ghost_repo)).scan()
    debt = by_path(scores, "debt/ledger.py")
    assert debt is not None
    assert debt.debt_markers >= 10


def test_scores_sorted_descending(ghost_repo: Path) -> None:
    scores = Scanner(Config(root=ghost_repo)).scan()
    values = [s.score for s in scores]
    assert values == sorted(values, reverse=True)
    assert all(0.0 <= v <= 1.0 for v in values)


def test_scan_is_deterministic(ghost_repo: Path) -> None:
    first = Scanner(Config(root=ghost_repo)).scan()
    second = Scanner(Config(root=ghost_repo)).scan()
    assert [(s.path, s.score, s.htype) for s in first] == [
        (s.path, s.score, s.htype) for s in second
    ]


def test_history_subjects_available_for_report(ghost_repo: Path) -> None:
    scanner = Scanner(Config(root=ghost_repo))
    scanner.scan()
    history = scanner.histories.get("crypt/revenant.py")
    assert history is not None
    assert "the revenant stirs once more" in history.last_subjects[0]
