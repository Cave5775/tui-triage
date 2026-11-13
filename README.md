# triage-board

**A to-do board for each of your repositories, shared by you and your coding agent.**

You jot down features, fixes and ideas in a fast, keyboard-driven terminal app.
Your coding agent (for example Claude Code), working in a normal session in that repo, reads the same board, picks up the work, leaves notes as it goes, and hands finished items back for you to review.

- **Fast to use.** Almost everything is a single key. Capture an idea in one line: `a` `Fix login loop !1 #fix` `Enter`.
- **Live.** When the agent claims, updates or finishes something, your open board updates within a second.
- **Out of your repos.** Boards live in your home folder (`~/.triage/`), never in the repository: no stray files, nothing to `.gitignore`, nothing committed by accident.
- **You stay in charge.** By default the agent can't mark work Done, edit or delete your items, or change its own permissions. Finished work waits in **Review** for you.

---

## Install

You need Python 3.11+ and git.

```sh
cd triage-board
pip install -e .          # adds the `triage` command
triage install-skill      # optional: teaches Claude Code how to use the board
```

`install-skill` writes `~/.claude/skills/triage/SKILL.md`, so every Claude Code session, in any repo, knows the board exists and how to use it. It changes nothing inside your repositories.

## Five-minute tour

1. **Open a board.** `cd` into any git repo and run `triage`. Each repo gets its own board automatically. Outside a repo, `triage` opens a picker of the boards you've used.
2. **Capture something.** Press `a`, type `Add dark mode !2 #feat`, and press `Enter`. It lands in **Inbox** with priority 2 and type *feature*. To capture several in a row, press `Alt+Enter` (or `Ctrl+J`) instead of `Enter` and the box stays open.
3. **Triage it.** Move through items with `j`/`k` (or the arrow keys). When an item is ready for work, press `Space` to promote it to **Todo**. Set its priority with `p` then `1`–`4`.
4. **Hand it to the agent.** In your agent session, say *"check the triage board"* or *"pick up the next task"*. The agent claims the item (it moves to **Doing**), works on it, and writes progress notes you can read in the right-hand pane.
5. **Review.** When the agent finishes, the item appears under **Review** (tab `4`). Read its summary. Press `y` to accept it (→ Done), or `n` to send it back with a reason the agent will see next time.

Press `?` at any time for the full list of keys.

## How work flows

```
 Inbox ──▶ Todo ──▶ Doing ──▶ Review ──▶ Done
 ideas     ready    agent     waiting    accepted
           for      working   for you
           work
```

- **Inbox:** quick captures that haven't been thought through yet. Agents don't take work from here (unless you allow it).
- **Todo:** approved and ready. This is the agent's queue, ordered by priority, then by your manual order.
- **Doing:** someone is working on it. The item shows who claimed it.
- **Review:** the agent says it's finished. You decide: accept (`y`) or send back (`n`).
- **Done:** accepted.
- **Archived** (tab `9`): soft-deleted items. You can restore them with `Space`.

Every item keeps an **activity log**: status changes, edits, your notes and the agent's notes and summaries, each marked with who wrote it. Notes are how you and the agent talk about an item. Press `c` to add one.

## Keyboard cheat sheet

The design rules: frequent actions are single keys; holding Shift does the bigger version of the same action; vim keys and arrow keys both work; anything destructive needs a second key or a `y`. The bottom bar always shows the keys that apply right now.

**Getting around**

| | |
|---|---|
| `j` `k` / `↓` `↑` | move down / up |
| `g` `G` | top / bottom (`Ctrl+D` / `Ctrl+U` for half a page) |
| `h` `l` / `←` `→` / `Tab` | previous / next tab |
| `1` … `5` | Inbox, Todo, Doing, Review, Done (`0` = all, `9` = archived) |
| `/` | filter by text (`Enter` keeps it, `Esc` clears it) |
| `Enter` | read the selected item in the detail pane (`Esc` to come back) |
| `R` | switch to another repo's board |

**Capturing**

| | |
|---|---|
| `a` | quick add, one line (see the tokens below) |
| `A` | full form with a description field (`Ctrl+S` saves) |
| `e` / `E` | edit the item in the form / edit its description in your own editor (`$EDITOR`) |
| `c` | add a note, e.g. to answer the agent's question |

**Triaging**

| | |
|---|---|
| `Space` / `Backspace` | move one step forward / back along the flow |
| `m` then `i` `t` `d` `r` `x` | move straight to Inbox / Todo / Doing / Review / Done |
| `y` / `n` | in Review: accept / send back with a reason |
| `p` then `1`–`4`, or `+` `-` | set the priority, or raise / lower it |
| `t` / `T` | cycle the type (feature, fix, change, chore, idea) |
| `J` / `K` | move the item down / up in the list |
| `d` `d` | archive (press `d` twice) |
| `u` | undo your last change |
| `Y` | copy `triage show <id>` to paste into an agent chat |

**App:** `,` settings · `?` help · `q` quit

### Quick-add tokens

Type them anywhere in the line; everything else becomes the title.

| token | meaning | example |
|---|---|---|
| `!1` … `!4` | priority: 1 urgent, 2 high, 3 normal (default), 4 low | `!1` |
| `#feat` `#fix` `#change` `#chore` `#idea` | type (also `#bug`, `#refactor`, …) | `#fix` |
| `>todo` `>inbox` … | the status to start in | `>todo` |

`Upload fails on big files !1 #bug >todo` creates an urgent fix, straight into Todo.

## Working with your agent

Once the skill is installed, plain requests are enough:

> "What's on the triage board?" · "Pick up the next task." · "Work on #12." · "Add that to the board for later."

Behind the scenes the agent runs the `triage` command:

```sh
triage next --json                 # what should I work on?
triage claim 12                    # take it (→ Doing)
triage note 12 "Found the cause in auth/session.py"
triage done 12 --summary "Fixed the redirect loop, added a regression test"   # → Review
```

The agent also files things it notices but shouldn't fix right now (`triage add ... --type fix`), so side quests don't creep into the current change.
If you send an item back with `n`, your reason is logged as `bounced: …`, and the agent reads it before trying again.

It works the same from git worktrees: an agent in `.claude/worktrees/feature-x` sees the same board as the main checkout.

### What the agent may do

Out of the box the agent **can** read everything, claim Todo items, write notes, finish work into Review, and add new items (they land in your Inbox).
It **can't** mark anything Done, accept or reject reviews, edit or reorder items you wrote, archive or delete, or change settings. If it tries, it gets a clear refusal telling it what to do instead.

You can loosen or tighten each of these rules globally or for a single repo. See Settings.

## Settings

Press `,` in the app to change settings. `Space`/`Enter` toggles or cycles a value, and `b` switches between **global** settings and settings **for this repo only**. You can also use the command line:

```sh
triage config                                        # show everything and where each value comes from
triage config set agent.finish_status done --as user          # global
triage config set agent.can_edit true --board --as user       # this repo only
```

| setting | default | what it controls |
|---|---|---|
| `agent.finish_status` | `review` | where finished agent work goes: `review` (you check it) or `done` (trust the agent) |
| `agent.pickup_statuses` | `todo` | where the agent may take work from (add `inbox` to let it pick up raw ideas) |
| `agent.create_status` | `inbox` | where items the agent files appear |
| `agent.can_create` | on | the agent may file new items |
| `agent.can_edit` | off | the agent may edit or reorder items *you* wrote (notes are always allowed) |
| `agent.can_archive` | off | the agent may archive or delete items |
| `agent.require_claim` | on | the agent must claim an item before finishing it |
| `ui.new_item_status` | `inbox` | where your quick-adds go when you're not on the Inbox or Todo tab |
| `ui.confirm_delete` | on | ask before permanently deleting |
| `ui.poll_seconds` | `1.0` | how quickly the board shows the agent's changes |

Settings are stored in `~/.triage/config.toml`. Only you can change them: the CLI refuses `config set` unless it is run with `--as user`, and the skill tells the agent never to try.

## Where your data lives

```
~/.triage/
  config.toml                 your settings
  registry.json               the boards you've used (for the repo picker)
  boards/<repo>-<id>.json     one board per repository
```

Board files are plain, readable JSON, which makes them easy to back up or inspect. To keep boards somewhere else, set `TRIAGE_HOME`.
The app and any number of agents can write at the same time: every change is locked and saved in one step, so nothing gets lost or corrupted.

## Troubleshooting

- **`Alt+Enter` doesn't keep the quick-add box open.** Some terminals don't send it; use `Ctrl+J` instead.
- **`E` opens the wrong editor.** It uses `$VISUAL`, then `$EDITOR`, then Notepad on Windows (`vi` elsewhere). For VS Code, use `set VISUAL=code --wait`.
- **"not inside a git repository".** Boards belong to git repos. Run `git init` first, or pick a board with `R`.
- **The agent says it isn't allowed to do something.** That's the permission system working. Change the setting if you want to allow it.

## Command reference

Every command works from inside the repo (or with `--repo PATH`), and accepts `--json` for machine-readable output.

| command | what it does |
|---|---|
| `triage` | open the board |
| `triage list [--status todo,doing] [--all]` | list items (`--all` includes archived) |
| `triage show ID` | one item with its description and full log |
| `triage next` | the item an agent should pick up next (doesn't claim it) |
| `triage claim [ID]` | start work (→ Doing); without an ID, claims the next item |
| `triage release ID [--note T]` | give up a claim (→ Todo) |
| `triage note ID TEXT` | add a note |
| `triage done ID [--summary T]` | finish (→ Review, or Done if configured) |
| `triage accept ID` / `triage bounce ID REASON` | review decisions (you only: add `--as user`) |
| `triage add TITLE [--type T] [--priority N] [--status S] [--body T \| --body-file F \| --body -]` | add an item |
| `triage set ID [--title] [--type] [--priority] [--status] [--body]` | edit an item |
| `triage archive ID` / `triage delete ID --yes` | archive / delete permanently |
| `triage repos` / `triage path` | known boards / this repo's board file |
| `triage config [get KEY \| set KEY VALUE \| unset KEY] [--board]` | settings |
| `triage install-skill [--force] [--dir PATH]` | install the Claude Code skill |

The CLI acts as the **agent** by default. Add `--as user` (or set `TRIAGE_ACTOR=user`) to act as yourself.
Exit codes: `0` ok, `1` error (the reason is on stderr, or in the JSON), `2` wrong usage.

## Development

```sh
pip install -e .[dev]
python -m pytest -q        # about 120 tests, about 2 minutes (the TUI tests wait on live polling)
```

The code is split into a small core that every change goes through (`triage/ops.py`, `store.py`, `config.py`, `model.py`, `paths.py`), plus two front ends: `triage/cli.py` and `triage/tui/`. `docs/CONTRACT.md` describes the core API. The TUI's keymap is defined once in `triage/tui/keys.py`, which drives both the bottom bar and the `?` help screen.
