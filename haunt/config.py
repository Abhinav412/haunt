"""Configuration and persona loading for haunt.

Defaults are baked in; a `.haunt.toml` at the repo root overrides them.
Personas are TOML files shipped inside the package, optionally overridden
per-repo by `.haunt-personas/<name>.toml`.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

CONFIG_NAME = ".haunt.toml"
PERSONA_DIR_NAME = ".haunt-personas"

DEFAULT_MODEL = "gemma2:2b"
DEFAULT_HOST = "http://localhost:11434"

DEFAULT_IGNORE = [
    "vendor/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    ".venv/**",
    "venv/**",
    "target/**",
    "__pycache__/**",
    "*.lock",
    "package-lock.json",
    "*.min.js",
    "*.min.css",
    "HAUNTINGS.md",
]

DEFAULT_WEIGHTS = {"dormant": 0.35, "restless": 0.25, "orphaned": 0.25, "debt": 0.15}

FALLBACK_IGNORE = ["*"]


@dataclass
class Config:
    model: str = DEFAULT_MODEL
    host: str = DEFAULT_HOST
    persona: str = "victorian"
    # 25s: measured budget that real whisper fits inside on a CPU-only box
    # (gemma2:2b at ~5.4 tok/s needs ~18s for 100 tokens); falls back sooner
    # on dedicated servers, later than the siren-song 8s that always missed.
    whisper_timeout: float = 25.0
    report_timeout: float = 60.0
    top_n: int = 10
    send_snippets: bool = False
    ignore: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE))
    weights: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_WEIGHTS)
    )
    root: Path = field(default_factory=Path.cwd)

    def weight(self, key: str) -> float:
        return float(self.weights.get(key, DEFAULT_WEIGHTS.get(key, 0.0)))


def repo_root(start: Path | None = None) -> Path:
    """Walk up from `start` looking for a git meta dir; fall back to cwd's longest match."""
    probe = (start or Path.cwd()).resolve()
    for candidate in (probe, *probe.parents):
        if (candidate / ".git").exists():
            return candidate
    return probe


def load_config(root: Path | None = None) -> Config:
    """Load defaults, then apply overrides from `.haunt.toml` when present."""
    root = root or repo_root()
    cfg = Config()
    cfg.root = root
    config_path = root / CONFIG_NAME
    if config_path.is_file():
        try:
            data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            data = {}
        for key in (
            "model",
            "host",
            "persona",
            "whisper_timeout",
            "report_timeout",
            "top_n",
            "send_snippets",
        ):
            if key in data:
                setattr(cfg, key, data[key])
        if isinstance(data.get("ignore"), list) and data["ignore"]:
            cfg.ignore = [str(g) for g in data["ignore"]]
        weights = data.get("weights")
        if isinstance(weights, dict):
            for key in DEFAULT_WEIGHTS:
                if key in weights:
                    cfg.weights[key] = float(weights[key])
    # env overrides win for tests and CI pinning
    if os.environ.get("HAUNT_MODEL"):
        cfg.model = os.environ["HAUNT_MODEL"]
    if os.environ.get("HAUNT_HOST"):
        cfg.host = os.environ["HAUNT_HOST"]
    return cfg


# --------------------------------------------------------------------------
# Personas
# --------------------------------------------------------------------------


def _persona_from_package(name: str) -> dict | None:
    ref = resources.files("haunt").joinpath("personas").joinpath(f"{name}.toml")
    if ref.is_file():
        return tomllib.loads(ref.read_text(encoding="utf-8"))
    return None


def _persona_from_repo(name: str, root: Path) -> dict | None:
    path = root / PERSONA_DIR_NAME / f"{name}.toml"
    if path.is_file():
        return tomllib.loads(path.read_text(encoding="utf-8"))
    return None


def list_personas() -> list[str]:
    """Names of personas shipped with the package."""
    names = []
    try:
        for ref in resources.files("haunt").joinpath("personas").iterdir():
            if ref.name.endswith(".toml") and ref.is_file():
                names.append(ref.name[: -len(".toml")])
    except (AttributeError, FileNotFoundError, NotADirectoryError):
        pass
    return sorted(names)


def load_persona(name: str, root: Path | None = None) -> dict:
    """Load a persona dict; repo-local `.haunt-personas/` overrides the package.

    Raises KeyError for unknown names and ValueError for malformed ones.
    """
    root = root or repo_root()
    data = _persona_from_repo(name, root) or _persona_from_package(name)
    if data is None:
        raise KeyError(name)
    for required in ("name", "system", "fallbacks", "emoji"):
        if required not in data:
            raise ValueError(f"persona '{name}' is missing field '{required}'")
    if not isinstance(data["fallbacks"], list) or len(data["fallbacks"]) < 10:
        raise ValueError(f"persona '{name}' needs a fallbacks list of 10+ lines")
    return data
