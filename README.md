# 🪦 haunt — Ghost in the Repo

Git hooks + a local open-weight model. haunt whispers eerie commentary on
commits, flags haunted code, and writes a spectral report. **Fully offline.**

```sh
pip install .          # then, inside any git repository:
haunt install          # the whisper joins your post-commit hook
git commit -m "tomb, again"
#   🕯️ The working tree trembles as a new revision is laid upon the tomb.

haunt scan             # which files are the most haunted, and why
haunt report [--html]  # narrated HAUNTINGS.md for the top `top_n` files
haunt persona ancestor # swap the voice: victorian, poltergeist, ancestor
```

## How it haunts

Every tracked file gets a **haunting score** from git history alone — no
model, fully deterministic:

```
dormant = min(age_days/365, 1) * min(size/500, 1)
restless = min(churn_90d/20, 1)
orphaned = 1 if every author is inactive 180d+ else 0
debt     = min((TODO FIXME HACK XXX)/10, 1)
score    = 0.35*dormant + 0.25*restless + 0.25*orphaned + 0.15*debt
```

Scores map to four ghosts, so you can speak their names:

| Ghost | Meaning |
| --- | --- |
| 🫥 **Orphan spirit** | everyone who wrote this file is gone from the project |
| 🕸️ **Sleeper** | old, untouched for ~90+ days |
| ⚡ **Poltergeist** | high churn, many authors, no owner |
| 🕯️ **Revenant** | dormant for months, then suddenly touched again |

The model only ever **narrates**. It receives metrics and commit subjects —
never your source files (send_snippets is off by default). Suggestions come
"grounded in the metrics": delete it, test it, document it, assign an owner.

## The model

Open-weight models run through Ollama at `http://localhost:11434`. Default:
`gemma2:2b` (alt: `llama3.2:3b`, `qwen2.5:3b` — any Ollama model works).

```sh
ollama pull gemma2:2b
```

**It works with no model running.** The Ollama layer is one client, zero
retries: probe once, generate once within the 8 s budget, else a
deterministic template whisper picked by commit hash — same commit, same
line, forever. The hook always exits 0 and never blocks a commit.

## Why open (and why offline)

- Runs on a laptop with no internet; works on a plane.
- Source code and history never leave the machine — a closed API would
  read your private repo's diffs to comment on them.
- No per-call cost, so a whisper on *every* commit is viable.
- Swap models and personas freely; hooks and config (`.haunt.toml`) live in
  the repo, not in someone else's service.

## Personas

- 🕯️ `victorian` — melodramatic, candlelit grief.
- ⚡ `poltergeist` — mischievous, terse, rattles your reflog.
- 🪔 `ancestor` — Día de los Muertos: warm, remembers *who* wrote the code
  and says it out loud ("Maria wrote this in 2021; her spirit still guards
  the retry loop").

Add your own as `.haunt-personas/<name>.toml` (needs name, system,
fallbacks with 10+ lines, emoji); it overrides the shipped ones.

## Edge cases handled

- Empty/merge commits and rebases: no whisper.
- Unborn HEAD (empty repo): scan reports "at rest".
- Hook install is idempotent and never overwrites — backups land in
  `.git/hooks/post-commit.pre-haunt.*`; `haunt uninstall` removes only the
  marked block.
- Shallow clones: age/author data may be thin; haunt still scores.
- Large repos: scan capped at 5 000 files from a single `git log` pass.
- Windows: hooks are POSIX `sh` with LF endings; `haunt` resolves absolute
  interpreter paths at install time so the hook works from any repo.

## Development

```sh
pip install -e .
python -m pytest tests/
```

Tests build a real git repo with planted ghosts (an orphan, a sleeper, a
revenant, a poltergeist) and assert real `git commit` runs the hook.

---

*The repository is never truly empty. It is merely quiet.* 🪦
