"""The Claude Code skill that teaches agents to use the triage CLI, and its installer."""

from __future__ import annotations

from pathlib import Path

SKILL_MD = '''\
---
name: triage
description: Use the repo's triage board (planned features, fixes and changes) through the `triage` CLI. Use when the user says "check the triage board", "what's planned", "what's next", "next task", "pick up work", "file this for later", "add this to the board", or mentions planned/queued features, fixes or changes for this repo, or when you find out-of-scope work worth recording.
---

# Triage board

Every repository has a triage board shared between the user (a TUI) and you (the `triage` CLI).
It holds planned features, fixes and changes. Flow: Inbox -> Todo -> Doing -> Review -> Done.

- The board belongs to the **current repo**; git worktrees of the repo share it.
- Its data lives outside the repo (`~/.triage`). Never look for it in the repo and never edit its files; use only the CLI.
- Add `--json` to any command to get one JSON document you can parse. `triage config get` lists the user's settings (what you may do).

## The loop

1. Find work: `triage list --json` or `triage next --json` (does not claim anything).
2. Read the item first: `triage show ID`. The log matters: a `bounced: ...` note is the user's feedback on a previous attempt, so address it.
3. Claim it: `triage claim ID` (or `triage claim` for the next item). The item moves to Doing.
4. Do the work. Record progress and decisions as you go: `triage note ID "chose X because Y"`.
5. Finish: `triage done ID --summary "what changed, which files, how you verified it"`.
   The item goes to the user's Review (unless they configured otherwise). Do not mark it Done yourself; the user accepts it.

## When you are stuck

- Unclear or blocked: add a note with your question (`triage note ID "Question: ..."`), then keep the claim or give it up with `triage release ID --note "why"`. Never guess at the user's intent.
- Work you notice that is out of scope: do not creep. File it: `triage add "short title" --type fix --priority 3 --body "details, file paths, how to reproduce"`.
  Types: feature, fix, change, chore, idea. Priority: 1 urgent .. 4 low. Long bodies: `--body-file path` or `--body -` (stdin).

## Permissions

The CLI enforces the user's settings. If it returns a permission error (cannot edit, archive, mark done, create...), respect it: do not work around it by other commands or by editing files. Add a note, or tell the user what you would have changed.

## Quick reference

```
triage list [--status todo,doing] [--all]   triage show ID        triage next
triage claim [ID] [--force]                 triage release ID     triage note ID TEXT...
triage done ID --summary TEXT               triage add TITLE... [--type T --priority N --body TEXT]
triage config get [KEY]                     triage path           (prints the board file path)
```

Use item numbers without `#` in shell commands (`#` starts a comment in many shells).
'''


def default_dir() -> Path:
    return Path.home() / ".claude" / "skills" / "triage"


def install_skill(dir: str | Path | None = None, force: bool = False) -> Path:
    """Write ``SKILL.md`` into ``dir`` (default ``~/.claude/skills/triage``) and return its path.

    Refuses to replace a *different* existing file unless ``force``. Raises ``ValueError``.
    """
    target_dir = Path(dir) if dir else default_dir()
    path = target_dir / "SKILL.md"
    try:
        if path.exists():
            if path.read_text(encoding="utf-8") == SKILL_MD:
                return path
            if not force:
                raise ValueError(f"{path} already exists and differs from the bundled skill; rerun with --force to overwrite it")
        target_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(SKILL_MD, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise ValueError(f"cannot write {path}: {exc}") from None
    return path
