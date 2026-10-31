"""haunt CLI — typer entrypoint.

Commands: install, uninstall, whisper, scan, report, persona, personas.

Design rule for the hook path: `haunt whisper` must never block or fail a
commit; it exits 0 in every branch and prints at most one line.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import typer

from . import __version__, config, gitutil, prompts, render
from .config import Config
from .llm import Ghost
from .scanner import Scanner

app = typer.Typer(
    help="haunt — a ghost in the repo. Git hooks + a local open-weight model.",
    add_completion=False,
    no_args_is_help=True,
)

HOOK_BEGIN = "# >>> HAUNT BEGIN (managed by `haunt install`; edit only between these markers)"
HOOK_END = "# <<< HAUNT END"


def _enable_windows_vt() -> None:
    """Windows console bootstrap: VT ANSI + UTF-8 pipes.

    Child processes on Windows default to the legacy codepage (cp1252); without
    this, personality emoji crash whisper with UnicodeEncodeError inside the
    quiet-catch hook path and the line silently disappears.
    """
    if sys.platform == "win32" and "NO_COLOR" not in os.environ:
        os.system("")  # enables ANSI VT processing in classic Windows consoles
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _print_version_and_exit(value: bool) -> None:
    if value:
        typer.echo(f"haunt {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_print_version_and_exit,
        is_eager=True,
        help="Print haunt's version and exit.",
    ),
) -> None:
    _enable_windows_vt()


# --------------------------------------------------------------------- utils


def _load() -> Config:
    cfg = config.load_config()
    if not gitutil.is_repo(cfg.root):
        typer.echo(
            "haunt: not a git repository — find the closest haunt elsewhere.", err=True
        )
        raise typer.Exit(code=1)
    return cfg


def _persona_or_default(cfg: Config) -> dict:
    try:
        return config.load_persona(cfg.persona, cfg.root)
    except Exception:
        known = ", ".join(config.list_personas()) or "none shipped"
        return {
            "name": "default",
            "emoji": "👻",
            "system": "You are the resident ghost of this repository.",
            "fallbacks": [
                "The repository stirs. Another commit joins the crypt.",
                "Something was changed here. The dust notices.",
                "A new page in the ledger of the dead.",
                "The file trembles; I keep the candle for it.",
                "They push, they forget. I keep the ledger.",
                "Another revision rests upon the old one.",
                "The working tree exhales. I remain.",
                "A quiet commit in a noisy history.",
                "The ancestors of this line salute it.",
                "Someone was here. The trail is still warm.",
                "Buried without ceremony: another commit.",
                "The spirits accepted the change without comment.",
            ],
            "_note": f"persona '{cfg.persona}' unavailable; shipped: {known}",
        }


def _hook_path(cfg: Config) -> Path:
    git_dir = Path(gitutil.run(cfg.root, "rev-parse", "--absolute-git-dir").strip())
    return git_dir / "hooks" / "post-commit"


def _hook_block(cfg: Config) -> str:
    project_root = str(Path(__file__).resolve().parent.parent).replace(os.sep, "/")
    python_exe = str(Path(sys.executable).resolve()).replace(os.sep, "/")
    return "\n".join(
        [
            HOOK_BEGIN,
            "if command -v haunt >/dev/null 2>&1; then",
            "    haunt whisper",
            f'elif [ -x "{python_exe}" ]; then',
            f'    PYTHONPATH="{project_root}" "{python_exe}" -m haunt whisper',
            "fi",
            "exit 0",
            HOOK_END,
        ]
    )


def _write_hook_region(path: Path, block: str) -> None:
    """Insert or replace the HAUNT block in a hook script, touching nothing else."""
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    pattern = re.compile(
        rf"{re.escape(HOOK_BEGIN)}.*?{re.escape(HOOK_END)}\n", re.DOTALL
    )
    if pattern.search(text):
        text = pattern.sub(block + "\n", text, count=1)
    elif text.startswith("#!"):
        line_end = text.find("\n")
        if line_end == -1:
            text = text + "\n" + block + "\n"
        else:
            shebang = text[: line_end + 1]
            rest = text[line_end + 1 :]
            text = shebang + block + "\n" + rest
    else:
        body = text if text.strip() else ""
        text = "#!/bin/sh\n" + block + "\n" + body
        if not text.endswith("\n"):
            text += "\n"
    # LF endings only: CRLF hook scripts break sh parsing on Git for Windows
    path.write_text(text, encoding="utf-8", newline="\n")


def _strip_hook_region(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"{re.escape(HOOK_BEGIN)}.*?{re.escape(HOOK_END)}\n?", re.DOTALL
    )
    if not pattern.search(text):
        return False
    path.write_text(pattern.sub("", text, count=1), encoding="utf-8", newline="\n")
    return True


def _executable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | 0o111)
    except OSError:
        pass


# -------------------------------------------------------------------- install


@app.command()
def install() -> None:
    """Install the post-commit hook. Backs up an existing hook, never overwrites."""
    cfg = _load()
    hook_dir = _hook_path(cfg).parent
    hook_dir.mkdir(parents=True, exist_ok=True)
    hook = hook_dir / "post-commit"

    if hook.is_file() and HOOK_BEGIN not in hook.read_text(encoding="utf-8"):
        stamp = "nocommit"
        try:
            stamp = gitutil.run(cfg.root, "rev-parse", "--short", "HEAD").strip() or stamp
        except gitutil.GitError:
            pass
        backup = hook_dir / f"post-commit.pre-haunt.{stamp}"
        shutil.copy2(hook, backup)
        typer.echo(f"haunt: existing hook backed up to {backup.name}")

    _write_hook_region(hook, _hook_block(cfg))
    _executable(hook)
    typer.echo(f"haunt: whisper installed at {hook}")

    ghost = Ghost(cfg)
    typer.echo("haunt: warming the local model (falls back silently if absent)...")
    if ghost.warm():
        typer.echo(f"haunt: model {cfg.model} is resident — first whisper should be quick.")
    else:
        probe = ghost.probe()
        hint = ghost.hint(probe)
        if hint:
            typer.echo(hint)
        typer.echo("haunt: still installed — whispers fall back to templates.")


@app.command()
def uninstall() -> None:
    """Remove haunt's block from the post-commit hook, leaving everything else alone."""
    cfg = _load()
    if _strip_hook_region(_hook_path(cfg)):
        typer.echo("haunt: whisper removed. The repository is on its own.")
    else:
        typer.echo("haunt: no haunt hook block found here.")


# -------------------------------------------------------------------- whisper


@app.command()
def whisper() -> None:
    """Print one in-character line about HEAD. Called by the post-commit hook.

    Contract: never blocks more than the configured timeout, never exits nonzero,
    silently skips empty commits, merges, and rebases.
    """
    try:
        _whisper_inner()
    except Exception:
        pass  # a haunted hook must never fail the commit


def _whisper_inner() -> None:
    cfg = _load()
    commit = gitutil.head_commit(cfg.root)
    if commit is None:
        return
    persona = _persona_or_default(cfg)
    system = prompts.whisper_system(persona)
    emoji = persona["emoji"]

    haunting = None
    try:
        scanner = Scanner(cfg)
        touched = set(commit.files)
        scores = [s for s in scanner.scan() if s.path in touched]
        if scores and scores[0].score >= 0.05:
            haunting = scores[0]
    except (gitutil.GitError, OSError):
        haunting = None

    prompt = prompts.whisper_prompt(commit, haunting)
    ghost = Ghost(cfg)
    probe = ghost.probe()
    line = None
    if probe.ok:
        line = ghost.generate(
            system=system,
            prompt=prompt,
            max_tokens=120,
            temperature=0.9,
            timeout=cfg.whisper_timeout,
        )
    if line is None:
        line = prompts.fallback_whisper(persona, commit.hash)
    typer.echo(render.whisper_line(emoji, line))


# ----------------------------------------------------------------------- scan


@app.command()
def scan(
    top: int = typer.Option(0, "--top", min=0, help="Show only the N most haunted files."),
) -> None:
    """Score tracked files from git history alone and print the most haunted."""
    cfg = _load()
    if top > 0:
        cfg.top_n = top
    scanner = Scanner(cfg)
    scores = scanner.scan()
    for warning in scanner.warnings:
        typer.echo(render.DIM_ON + warning + render.RESET, err=True)
    typer.echo(render.terminal_scores(scores, cfg))


# --------------------------------------------------------------------- report


@app.command()
def report(
    html: bool = typer.Option(False, "--html", help="Also write HAUNTINGS.html."),
) -> None:
    """Write HAUNTINGS.md — a narrated spectral report for the most haunted files."""
    cfg = _load()
    scanner = Scanner(cfg)
    scores = scanner.scan()
    entries = scores[: cfg.top_n]
    skipped = max(0, scanner.total_tracked - scanner.scanned)

    narrations: dict[str, str] = {}
    if entries:
        persona = _persona_or_default(cfg)
        system = prompts.report_system(persona)
        ghost = Ghost(cfg)
        probe = ghost.probe()
        hint = ghost.hint(probe)
        if hint:
            typer.echo(hint, err=True)
        for index, entry in enumerate(entries, start=1):
            history = scanner.histories.get(entry.path)
            subjects = history.last_subjects if history else []
            prompt = prompts.report_prompt(entry, subjects, cfg)
            narration = (
                ghost.generate(
                    system=system,
                    prompt=prompt,
                    max_tokens=260,
                    temperature=0.9,
                    timeout=cfg.report_timeout,
                )
                if probe.ok
                else None
            )
            if narration is None:
                narration = prompts.fallback_report(entry, persona, f"report::{entry.path}")
            narrations[entry.path] = narration
            whisperized = "haunt: narrating" if False else "haunt: narrating"
            typer.echo(f"haunt: narrating {index}/{len(entries)} {entry.path}")

    md_path = render.write_markdown(
        cfg.root / "HAUNTINGS.md", scores, narrations, cfg, skipped=skipped
    )
    if html:
        (cfg.root / "HAUNTINGS.html").write_text(
            render.html_report(scores, narrations, cfg), encoding="utf-8"
        )
        typer.echo(f"haunt: report haunts {md_path.name} and HAUNTINGS.html")
    else:
        typer.echo(f"haunt: report haunts {md_path.name}")


# -------------------------------------------------------------------- persona


@app.command("personas")
def personas() -> None:
    """List available personas."""
    names = config.list_personas()
    if not names:
        typer.echo("haunt: no personas shipped — check your install.")
        raise typer.Exit(code=1)
    for name in names:
        extra = ""
        try:
            data = config.load_persona(name, Path.cwd())
            first = data["system"].strip().splitlines()[0]
            extra = f"  {data['emoji']} — {first[:70]}"
        except Exception:
            extra = ""
        typer.echo(f"  {name}{extra}")
    typer.echo("")
    typer.echo("Repo-local personas live in .haunt-personas/<name>.toml and override these.")


@app.command()
def persona(
    name: str = typer.Argument(..., help="Persona name to set in .haunt.toml"),
) -> None:
    """Set the active persona in .haunt.toml."""
    cfg = _load()
    try:
        config.load_persona(name, cfg.root)
    except KeyError:
        typer.echo(
            f"haunt: persona '{name}' is not shipped and no .haunt-personas/{name}.toml found.",
            err=True,
        )
        known = ", ".join([*config.list_personas(), "custom (.haunt-personas/)"])
        typer.echo(f"haunt: known personas: {known}", err=True)
        raise typer.Exit(code=1)
    except ValueError:
        typer.echo(f"haunt: persona '{name}' exists but is malformed.", err=True)
        raise typer.Exit(code=1)

    config_path = cfg.root / config.CONFIG_NAME
    if not config_path.is_file():
        config_path.write_text(_template(cfg, name), encoding="utf-8")
    else:
        text = config_path.read_text(encoding="utf-8")
        if re.search(r"(?m)^persona\s*=", text):
            text = re.sub(r"(?m)^persona\s*=.*$", f'persona = "{name}"', text, count=1)
        else:
            text = f'persona = "{name}"\n' + text
        config_path.write_text(text, encoding="utf-8")
    typer.echo(f"haunt: persona set — {name}")


def _template(cfg: Config, name: str) -> str:
    return (
        "# haunt config — one ghost, many voices\n"
        f'model = "{cfg.model}"\n'
        f'host = "{cfg.host}"\n'
        f'persona = "{name}"\n'
        f"whisper_timeout = {cfg.whisper_timeout}\n"
        f"report_timeout = {cfg.report_timeout}\n"
        f"top_n = {cfg.top_n}\n"
        f"send_snippets = {str(cfg.send_snippets).lower()}\n"
        f"ignore = {json_list(cfg.ignore)}\n"
        "[weights]\n"
        f"dormant = {cfg.weight('dormant')}\n"
        f"restless = {cfg.weight('restless')}\n"
        f"orphaned = {cfg.weight('orphaned')}\n"
        f"debt = {cfg.weight('debt')}\n"
    )


def json_list(values: list[str]) -> str:
    return "[" + ", ".join(f'"{v}"' for v in values) + "]"


if __name__ == "__main__":
    app()
