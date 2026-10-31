"""Terminal, Markdown, and HTML renderers.

Terminal: ANSI (respects NO_COLOR). HAUNTINGS.md: narrated entries. HTML:
single-file, dark, flickering CSS title, zero external assets.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .scanner import TYPES, FileScore

DIM_ITALIC_ON = "\x1b[2;3m"
RESET = "\x1b[0m"
BOLD_ON = "\x1b[1m"
DIM_ON = "\x1b[2m"

TYPE_EMOJI = {
    "Sleeper": "🕸️",
    "Poltergeist": "⚡",
    "Revenant": "🕯️",
    "Orphan spirit": "🫥",
}


def _ansi_enabled() -> bool:
    import os

    return "NO_COLOR" not in os.environ


def whisper_line(emoji: str, text: str) -> str:
    line = f"{emoji} {text}"
    if not _ansi_enabled():
        return line
    return f"{DIM_ITALIC_ON}{line}{RESET}"


def _short(value: float, unit: str) -> str:
    return f"{value:.0f}{unit}"


def terminal_scores(scores: list[FileScore], cfg: Config) -> str:
    top = scores[: cfg.top_n]
    if not top:
        return "The repository is at rest: nothing with a haunting score above zero."
    ansi = _ansi_enabled()
    headers = ("score", "type", "age", "churn90", "authors", "debt", "loc", "file")
    rows = []
    for score in top:
        rows.append(
            (
                f"{score.score:.2f}",
                TYPE_EMOJI.get(score.htype, "") + " " + score.htype,
                _short(score.age_days, "d"),
                str(score.churn_90d),
                f"{score.authors_active}/{score.authors_total}",
                str(score.debt_markers),
                str(score.size_loc),
                score.path,
            )
        )
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(8)]
    lines = []
    title = f" haunted files "
    bar = title.center(94, "~")
    if ansi:
        lines.append(f"{BOLD_ON}🕯️ {bar}{RESET}")
    else:
        lines.append(f"🕯️ {bar}")
    lines.append("  ".join(headers[i].ljust(widths[i]) for i in range(8)))
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        cells = "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        if ansi:
            cells = f"{DIM_ON}{cells}{RESET}"
        lines.append(cells)
    lines.append(f"\n(top {len(top)} of {len(scores)} haunted; show fewer with `haunt scan --top N`)")
    return "\n".join(lines)


# ------------------------------------------------------------------ markdown


def _fmt_age(entry: FileScore) -> str:
    if entry.age_days < 1:
        return "today"
    if entry.age_days < 120:
        return f"{entry.age_days:.0f} days"
    return f"{entry.age_days / 365.0:.1f} years"


def markdown_report(
    scores: list[FileScore],
    narrations: dict[str, str],
    cfg: Config,
    *,
    skipped: int | None = None,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    counts = {t: 0 for t in TYPES}
    for entry in scores:
        if entry.htype in counts:
            counts[entry.htype] += 1
    lines: list[str] = []
    lines.append("# 🪦 Hauntings Report")
    lines.append("")
    lines.append(
        f"Spectral audit by [`haunt`](https://github.com/Abhinav412/haunt) v0.1 — "
        f"persona `{cfg.persona}` · model `{cfg.model}` · generated {now}"
    )
    lines.append("")
    lines.append(f"**{len(scores)} files scored** with a haunting above zero"
                 + (f"; {skipped} skipped (lockfiles, vendored, generated, binary)." if skipped else "."))
    lines.append("")
    lines.append("## 👻 Summary")
    lines.append("")
    lines.append("| Haunting | Count |")
    lines.append("| --- | --- |")
    for kind in TYPES:
        emoji = TYPE_EMOJI.get(kind, "")
        lines.append(f"| {emoji} {kind} | {counts[kind]} |")
    lines.append("")
    lines.append("## 📜 Ranked hauntings")
    lines.append("")
    for rank, entry in enumerate(scores[: cfg.top_n], start=1):
        emoji = TYPE_EMOJI.get(entry.htype, "")
        lines.append(
            f"### {rank}. `{entry.path}` — {emoji} {entry.htype} (score {entry.score:.2f})"
        )
        lines.append("")
        lines.append(f"`{entry.metrics_line}`")
        lines.append("")
        narration = narrations.get(entry.path)
        if narration:
            lines.append(f"> {narration}")
        lines.append("")
    lines.append("---")
    lines.append(
        "*Run `haunt report` again after cleaning up; the ghosts keep score.*"
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------- html


def html_report(
    scores: list[FileScore], narrations: dict[str, str], cfg: Config
) -> str:
    counts = {t: 0 for t in TYPES}
    for entry in scores:
        if entry.htype in counts:
            counts[entry.htype] += 1
    cards = []
    for rank, entry in enumerate(scores[: cfg.top_n], start=1):
        emoji = TYPE_EMOJI.get(entry.htype, "")
        narration = narrations.get(entry.path, "")
        cards.append(
            f"<article>"
            f"<h3>{rank}. {entry.path}</h3>"
            f"<p class='meta'>{emoji} {entry.htype} · score {entry.score:.2f}</p>"
            f"<p class='metrics'>{entry.metrics_line}</p>"
            f"<p class='ghost-text'>{narration}</p>"
            f"</article>"
        )
    summary = " · ".join(f"{kind}: {counts[kind]}" for kind in TYPES)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Haunted Files — haunt report</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{
    background: #0a0a0f; color: #cfc4e8; font: 16px/1.6 Georgia, 'Times New Roman', serif;
    max-width: 820px; margin: 0 auto; padding: 3rem 1rem 5rem;
  }}
  h1 {{
      font-size: 2.6rem; letter-spacing: .04em; color: #e8ddff;
      animation: flicker 4s infinite steps(1);
  }}
  @keyframes flicker {{
    0%, 100% {{ opacity: 1; text-shadow: 0 0 14px #8a5cf5; }}
    7% {{ opacity: .4; }}
    8% {{ opacity: .92; }}
    42% {{ opacity: .95; }}
    43% {{ opacity: .35; }}
    44% {{ opacity: .9; }}
    71% {{ opacity: 1; }}
    74% {{ opacity: .55; }}
    75% {{ opacity: .92; }}
  }}
  h2 {{ color: #b89fff; text-transform: uppercase; letter-spacing: .2em; font-size: .95rem; }}
  .summary {{ color: #9d92ad; font-style: italic; }}
  article {{
    border: 1px solid #2a2440; border-radius: .6rem; padding: 1rem 1.2rem;
    margin: 1rem 0; background: #100d18;
  }}
  article h3 {{ margin: 0 0 .2rem; color: #d3c1ff; font-family: monospace; font-size: .95rem; }}
  .meta {{ margin: 0; color: #8a5cf5; }}
  .metrics {{ margin: .3rem 0 .6rem; color: #857b96; font-family: monospace; font-size: .8rem; }}
  .ghost-text {{ margin: 0; font-style: italic; color: #c4b8dc; }}
  article:hover {{ border-color: #4d3a80; }}
</style>
</head>
<body>
<h1>🕯️ Hauntings Report</h1>
<p class="summary">persona <code>{cfg.persona}</code> · model <code>{cfg.model}</code> — {summary}</p>
<h2>Ranked hauntings</h2>
{''.join(cards)}
</body>
</html>
"""


def write_markdown(
    path: Path, scores: list[FileScore], narrations: dict[str, str], cfg: Config, skipped: int | None = None
) -> Path:
    path.write_text(
        markdown_report(scores, narrations, cfg, skipped=skipped), encoding="utf-8"
    )
    return path
