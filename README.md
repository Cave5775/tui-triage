# tui-triage

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
pipx install tui-triage   # or: pip install tui-triage — adds the `triage` command
triage install-skill        # optional: teaches Claude Code how to use the board
```

To run the latest unreleased version, use `pipx install git+https://github.com/Cave5775/tui-triage`.

`install-skill` writes `~/.claude/skills/triage/SKILL.md`, so every Claude Code session, in any repo, knows the board exists and how to use it. It changes nothing inside your repositories.

## Five-minute tour

1. **Open a board.** `cd` into any git repo and run `triage`. Each repo gets its own board automatically. Outside a repo, `triage` opens a picker of the boards you've used.
2. **Capture something.** Press `a`, type `Add dark mode !2 #feat`, and press `Enter`. It lands in **Inbox** with priority 2 and type *feature*. To capture several in a row, press `Ctrl+J` instead of `Enter` and the box stays open.
3. **Triage it.** Move through items with `j`/`k` (or the arrow keys). When an item is ready for work, press `Space` to promote it to **Todo**. Set its priority with `p` then `1`–`4`.
4. **Hand it to the agent.** In your agent session, say *"check the triage board"* or *"pick up the next task"*. The agent claims the item (it moves to **Doing**), works on it, and writes progress notes you can read in the right-hand pane.
5. **Review.** When the agent finishes, the item appears under **Review** (tab `4`). Read its summary. Press `y` to accept it (→ Done), or `n` to send it back with a reason the agent will see next time.

Press `?` at any time for the full list of keys. It starts with the keys that matter for what you're looking at, and the bar at the bottom of the screen shows the same thing.

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

The design rules: frequent actions are single keys; holding Shift does the bigger version of the same action; vim keys and arrow keys both work; anything destructive needs a second key or a `y`. The bar at the bottom always shows the keys that apply right now (an item selected, an item in Review, the Archived tab, the detail pane, a filter), using your own key names if you've changed them.

**Getting around**

| | |
|---|---|
| `j` `k` / `↓` `↑` | move down / up |
| `g` `G` | top / bottom (`Ctrl+D` / `Ctrl+U` or `PgDn` / `PgUp` for half a page) |
| `h` `l` / `←` `→` | previous / next tab |
| `Tab` / `Shift+Tab` | switch between the item list and the detail pane, so you can scroll a long note without reaching for `Enter` and `Esc` |
| `1` … `5` | Inbox, Todo, Doing, Review, Done (`0` = all, `9` = archived) |
| `/` | filter by text (`Enter` keeps it, `Esc` clears it) |
| `o` / `O` | sort by priority, last activity, newest, oldest or item number (forward / back); the list title shows the order |
| `Enter` | read the selected item in the detail pane (`Esc` or `Tab` to come back) |
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
| `J` / `K` | move the item down / up in the list (priority sort only) |
| `d` `d` | archive (press `d` twice) |
| `u` | undo your last change |
| `Y` | copy `triage show <id>` to paste into an agent chat |

**App:** `,` settings · `?` help · `q` quit

The item keys (`e`, `c`, `Space`, `m`, `p`, `y`, `n`, `u`, `d d`, ...) work the same while the detail pane has focus, and act on the selected item. In the detail pane `j`/`k` scroll instead of moving through the list.

### Customising keys

Every key above can be changed. The keys live in the `[keys]` table of `~/.triage/config.toml`, and the easiest way to start is to let triage write the whole file for you, defaults and comments included:

```sh
triage config init                 # writes ~/.triage/config.toml (refuses to overwrite an existing one)
triage config init ./my.toml --as user   # or write it somewhere else, then: TRIAGE_CONFIG=./my.toml triage
triage config keys                 # show the keys in effect (add --json for scripts)
```

Each line is `command = "key1, key2"`. Keys are Textual key names (`ctrl+d`, `down`, `shift+tab`, `f5`, `question_mark`) or just the character (`?`, `/`, `+`, `-`, `=`, `space`; the comma key is written `comma`). For example:

```toml
[keys]
quit = "q, ctrl+q"
help = "?, f1"
edit = "e, f2"
toggle_detail = "tab, w"
move = "m"                 # the first key of m-then-i/t/d/r/x; the second keys are fixed
archive = "d"              # press it twice to archive
```

Only the commands you list change; everything else keeps its default. One key can't be bound to two commands. If something in `[keys]` is wrong (an unknown command, an empty value, a clash), triage ignores that entry, uses the default instead, and shows one warning when it starts, for example `keys: 2 problems in config.toml — default used for quit, edit (see triage config keys)`. It never refuses to start. Key changes apply the next time you open the TUI. A few keys do two jobs depending on where you are, and each is one entry: `advance` (`Space` moves an item forward, or restores it in Archived), `back` (`Esc` leaves the detail pane, or clears the filter), `accept` (`y`) and `purge` (`D`).

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
triage config init                                             # write a complete, commented config.toml to start from
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
| `ui.sort` | `priority` | the list order the TUI starts with: `priority`, `activity`, `created` (newest first), `oldest`, `number` |

Settings are stored in `~/.triage/config.toml` (or the file named by `TRIAGE_CONFIG`). Only you can change them: the CLI refuses `config set` unless it is run with `--as user`, and the skill tells the agent never to try. Changing a setting edits just that one line, so the comments and the `[keys]` table you wrote stay as they are.

## Where your data lives

```
~/.triage/
  config.toml                 your settings
  registry.json               the boards you've used (for the repo picker)
  boards/<repo>-<id>.json     one board per repository
```

Board files are plain, readable JSON, which makes them easy to back up or inspect. To keep boards somewhere else, set `TRIAGE_HOME`. To use a config file from a different place (for example one made with `triage config init ./my.toml`), set `TRIAGE_CONFIG` to its path.
The app and any number of agents can write at the same time: every change is locked and saved in one step, so nothing gets lost or corrupted.

## Troubleshooting

- **Esc, Alt or Shift keys do nothing, and you can't cancel or quit** (Windows, in modern terminals such as Windows Terminal, Alacritty or Terax). Fixed: triage no longer asks the terminal for the "kitty keyboard protocol", which Windows 10's console layer can't translate. If a future setup handles it, `TRIAGE_KITTY_KEYS=1` turns it back on.
- **Save-and-keep-open in quick add is `Ctrl+J`.** Most terminals send `Alt+Enter` exactly like `Enter`, so it can't be relied on.
- **`E` opens the wrong editor.** It uses `$VISUAL`, then `$EDITOR`, then Notepad on Windows (`vi` elsewhere). For VS Code, use `set VISUAL=code --wait`.
- **"not inside a git repository".** Boards belong to git repos. Run `git init` first, or pick a board with `R`.
- **The agent says it isn't allowed to do something.** That's the permission system working. Change the setting if you want to allow it.

## Command reference

Every command works from inside the repo (or with `--repo PATH`), and accepts `--json` for machine-readable output.

| command | what it does |
|---|---|
| `triage` | open the board |
| `triage list [--status todo,doing] [--all] [--sort S]` | list items (`--all` includes archived; `--sort activity\|created\|oldest\|number` gives one list across statuses) |
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
| `triage config init [PATH] [--force]` | write a complete default `config.toml` (an existing file needs `--force --as user`) |
| `triage config keys [--json]` | the keybindings in effect, and any problems with `[keys]` |
| `triage install-skill [--force] [--dir PATH]` | install the Claude Code skill |

The CLI acts as the **agent** by default. Add `--as user` (or set `TRIAGE_ACTOR=user`) to act as yourself.
Exit codes: `0` ok, `1` error (the reason is on stderr, or in the JSON), `2` wrong usage.

## Development

```sh
git clone https://github.com/Cave5775/tui-triage && cd tui-triage
pip install -e .[dev]
python -m pytest -q        # about 270 tests, about 2 minutes (the TUI tests wait on live polling)
```

The code is split into a small core that every change goes through (`triage/ops.py`, `store.py`, `config.py`, `model.py`, `paths.py`), plus two front ends: `triage/cli.py` and `triage/tui/`. `docs/CONTRACT.md` describes the core API. The TUI's keymap is defined once in `triage/tui/keys.py` (named commands with default keys, and the hint lists for each context). It drives the key bindings, the bottom bar, the `?` help screen and `triage config init|keys`, and the `[keys]` table in `config.toml` is overlaid on it at startup.

Releases are published to PyPI from a git tag by GitHub Actions; see `docs/RELEASING.md`.

## License

GNU General Public License v3.0 or later, see `LICENSE`.
