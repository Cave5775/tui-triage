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

Single keys for the frequent actions; Shift is the bigger version of the same action; vim keys and arrow keys both work; nothing destructive happens without a second key or a `y`. The footer and the `?` help screen are generated from the same binding table (`triage/tui/keys.py`), so they always agree with this list.

**Navigate**

| key | action |
|---|---|
| `j/↓` | move down (scrolls the detail pane when it has focus) |
| `k/↑` | move up |
| `g/Home` | jump to the top |
| `G/End` | jump to the bottom |
| `ctrl+d` | half page down |
| `ctrl+u` | half page up |
| `l/→` | next status tab (also tab) |
| `h/←` | previous status tab (also shift+tab) |
| `1-5` | jump to Inbox / Todo / Doing / Review / Done |
| `0` | show All (every non-archived status) |
| `9` | show Archived (also h/l past All) |
| `/` | filter by title/body (enter keeps it, esc clears it) |
| `enter` | focus the detail pane to scroll it (esc returns) |
| `esc` | leave the detail pane (shown while it has focus) |

**Capture**

| key | action |
|---|---|
| `a` | quick add: !1-!4 priority, #fix type, >todo status (enter saves, alt+enter / ctrl+j saves and keeps open) |
| `A` | full add form (ctrl+s saves, esc cancels) |
| `e` | edit the selected item in the form |
| `E` | edit the body in $VISUAL / $EDITOR |
| `c` | add a note (how you reply to the agent) |

**Triage**

| key | action |
|---|---|
| `space` | advance to the next status |
| `backspace` | move to the previous status |
| `y` | accept (Review only): move to Done |
| `n` | bounce with a reason: back to Todo, logged for the agent |
| `+/=` | raise priority (lower number) |
| `-` | lower priority |
| `t` | cycle the type forward |
| `T` | cycle the type backward |
| `J` | move the item down within its column |
| `K` | move the item up within its column |
| `D` | permanently delete (Archived tab; asks y/n) |
| `u` | undo the last change made in this session |
| `Y` | copy `triage show <id>` to the clipboard |
| `m …` | move the item to a status: i inbox t todo d doing r review x done |
| `p …` | set the priority: 1 urgent 2 high 3 normal 4 low |
| `d d` | press d twice to archive (in Archived: purge, asks y/n) |

**App**

| key | action |
|---|---|
| `,` | settings (global or per board) |
| `R` | repo picker |
| `?` | this help |
| `q` | quit |

Chords show their options in the message line and are cancelled by `esc` (or, for `m` and `p`, any other key): `m` then `i` `t` `d` `r` `x` moves to inbox / todo / doing / review / done; `p` then `1`-`4` sets the priority; `d d` (within a second) archives. In the Archived tab `space` restores an item to Inbox and `D` / `d d` deletes it permanently after a `y/n`.

Quick add (`a`) understands tokens anywhere in the text: `!1`-`!4` priority, `#feat #fix #change #chore #idea` (and the aliases `#bug`, `#refactor`, ...) type, `>todo` `>inbox` ... initial status. `enter` saves and closes; `alt+enter` or `ctrl+j` (Windows terminals often cannot send `ctrl+enter`) saves and keeps the input open for the next item.

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
