# triage-board

A keyboard-driven terminal board for planning features, fixes and changes **per repository**, shared between you (the TUI) and your coding agent (the CLI).
Nothing is stored in your repositories. Boards live in `~/.triage/` (override with `TRIAGE_HOME`), and every git worktree of a repo shares the same board.

```
pip install -e .          # installs the `triage` command
triage                    # open the board for the repo you're in
triage install-skill      # teach Claude Code sessions to use the board
```

## Workflow
`Inbox → Todo → Doing → Review → Done` (plus `Archived`).
You capture ideas into **Inbox** and promote the ones that are ready to **Todo**. The agent claims Todo items (→ Doing), works on them, and finishes them (→ **Review**, by default). You **accept** them (→ Done) or **bounce** them back to Todo with a reason.

## Keyboard
_(written in the TUI phase)_

## Agent interface
Coding agents use the `triage` CLI from inside a normal session in the repo (worktrees share the board). Run `triage install-skill` once to install the Claude Code skill (`~/.claude/skills/triage/SKILL.md`; use `--dir PATH` to choose another place, `--force` to overwrite an edited copy).

The agent loop: `triage list` or `triage next` -> `triage claim ID` -> work -> `triage note ID "..."` -> `triage done ID --summary "..."` (the item lands in Review unless `agent.finish_status` is `done`). A `bounced: ...` note in an item's log is your feedback on a previous attempt.

| command | what it does |
|---|---|
| `triage` / `triage tui` | open the board |
| `list [--status todo,doing] [--all]` | items grouped by status in flow order (`--all` adds archived) |
| `show ID` | one item with its body and full log |
| `next` | the item an agent should pick up (does not claim it) |
| `claim [ID] [--force] [--name NAME]` | start work (-> Doing); no ID claims the next item |
| `release ID [--note T]` | give up a claim (-> Todo) |
| `note ID TEXT...` | append a note |
| `done ID [--summary T]` | finish (-> Review or Done, per settings) |
| `accept ID [--note T]`, `bounce ID REASON...` | review decisions (user only: `--as user`; agents are refused) |
| `add TITLE... [--type T] [--priority N] [--status S] [--body T / --body-file PATH / --body -]` | add an item |
| `set ID [--title] [--type] [--priority] [--status] [--body ...]` | edit an item |
| `archive ID`, `delete ID --yes` | soft delete, permanent delete |
| `repos`, `path` | known boards, this repo's board file |
| `config [get [KEY]]`, `config set KEY VALUE`, `config unset KEY` | settings; `set`/`unset` are user only (`--as user`) (`--board` targets this repo's board, otherwise global; `get` shows the effective value and its source) |
| `install-skill [--force] [--dir PATH]` | install the Claude skill |

Global options work before or after the command: `--repo PATH` (else `$TRIAGE_REPO`, else the current directory), `--as agent|user` (default `agent`, or `$TRIAGE_ACTOR`) and `--json` (exactly one JSON document on stdout; errors are `{"error": ..., "type": ...}`).
Exit codes: 0 success, 1 error (message on stderr: `triage: error: ...`), 2 usage error. Agent actions are limited by the settings below, for example an agent cannot edit your items or mark work Done by default.

## Settings
`~/.triage/config.toml`. Each setting can be set globally or per board. Edit it from the TUI (`,`) or with `triage config`.

| key | default | meaning |
|---|---|---|
| `agent.finish_status` | `review` | where an item goes when the agent finishes it (`review` or `done`) |
| `agent.pickup_statuses` | `["todo"]` | statuses the agent may claim work from |
| `agent.create_status` | `inbox` | status for items the agent creates |
| `agent.can_create` | `true` | agent may add items |
| `agent.can_edit` | `false` | agent may edit items you created (notes are always allowed) |
| `agent.can_archive` | `false` | agent may archive or delete items |
| `agent.require_claim` | `true` | agent must claim an item before finishing it |
| `ui.new_item_status` | `inbox` | status for items you add in the TUI |
| `ui.confirm_delete` | `true` | ask before permanently deleting |
| `ui.poll_seconds` | `1.0` | how often the TUI picks up the agent's changes |

## Storage
```
~/.triage/
  config.toml
  registry.json              # known boards (for the repo picker)
  boards/<repo>-<hash>.json  # one board per repository
```
Writes are locked and atomic, so the TUI and any number of agent processes can work on a board at the same time.
