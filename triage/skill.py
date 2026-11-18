"""The Claude Code skill that teaches agents to use the triage CLI, and its installer."""

from __future__ import annotations

from pathlib import Path

SKILL_MD = '''\
---
name: triage
description: Use the repo's triage board of planned features, fixes and changes through the `triage` CLI. Use when the user says "check the triage board", "what's planned", "what's next", "next task", "pick up work", "file this for later", "add this to the board", mentions queued work for this repo, or when you find out-of-scope work worth recording.
---

# Triage board

The current repo's board (shared by its worktrees) is used by the user in a TUI and by you through the `triage` CLI. Flow: Inbox -> Todo -> Doing -> Review -> Done. Its data lives in `~/.triage`: use only the CLI, never read or edit those files. `--json` on any command prints one parseable document.

## Loop

1. Pick the item the user named, else `triage next --json` (claims nothing; `null` = no work) or `triage list --status todo --json`.
2. Read it: `triage show ID`. A `bounced: ...` log entry is the user's feedback on a previous attempt; address it.
3. `triage claim ID`. If refused, pick another item or ask; never force it. Items tagged `user` are the user's: hands off.
4. Work. Record decisions: `triage note ID "chose X because Y"`.
5. `triage done ID --summary "what changed, which files, how verified"`. It goes to the user's Review; never accept it yourself.

## Keep the board out of the repo

Item numbers, titles and the board itself (`#9`, "triage item 9", "per the board") never appear in commit messages, branch names, PR titles or bodies, code, comments, docs or tests. Describe the change on its own terms. Progress and summaries belong in `triage note` / `triage done`.

## Stuck or out of scope

- Unclear or blocked: `triage note ID "Question: ..."`, then keep the claim or `triage release ID --note "why"`. Never guess the user's intent.
- Unrelated work you notice: file it, don't do it: `triage add "title" --type fix --priority 3 --body "what, where, how to reproduce"`. Types: feature fix change chore idea. Priority: 1 urgent .. 4 low. Long body: `--body-file PATH` or `--body -` (stdin).

## Permissions

The CLI enforces the user's settings (`triage config get`). On a permission error, stop: no workarounds (other commands, `--as user`, editing files) and never change settings. Note or tell the user what you would have done.

Write IDs without `#` in shell commands (`#` starts a comment).
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
