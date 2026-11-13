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
_(written in the CLI phase)_

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
