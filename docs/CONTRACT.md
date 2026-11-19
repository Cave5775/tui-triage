# Core contract (frozen for the CLI and TUI phases)

The CLI (`triage/cli.py`) and TUI (`triage/tui/`) are thin front ends over the core.
**They must never write board files or config files directly.** All board mutations go
through `triage.ops`, and all config writes go through `triage.config.set_value`.

## Invariants
- Nothing is ever written inside a repository. All data lives under `triage.paths.triage_home()`
  (`~/.triage`, or `$TRIAGE_HOME`, which tests set).
- Repo identity comes from the git common dir, so worktrees share the board: `triage.paths.resolve_repo(path=None)`.
- Every mutation is one locked transaction, safe to run alongside other processes. Readers use `store.load()` (no lock).
- `actor` is `"user"` (TUI, or the CLI's `--as user`) or `"agent"` (the CLI default). Agent permissions are checked inside `ops`.

## Modules

### `triage.paths`
`triage_home()`, `boards_dir()`, `registry_path()`, `config_path()` (`$TRIAGE_CONFIG` when set, else `<home>/config.toml`), `board_path(board_id)`,
`resolve_repo(path=None) -> RepoRef(root: Path, name: str, board_id: str)` (it has a `.board_path` property),
`RepoNotFound` (exception).

### `triage.model`
- `FLOW = ("inbox","todo","doing","review","done")`, `STATUSES = FLOW + ("archived",)`
- `TYPES = ("feature","fix","change","chore","idea")`, `PRIORITIES = (1,2,3,4)` (1 = urgent), `PRIORITY_LABELS`
- `TYPE_ALIASES` / `STATUS_ALIASES`: `normalize_type(s)`, `normalize_status(s)`, `normalize_priority(v)` (each raises `ValueError`)
- `Item(id, title, body, type, priority, status, rank, created_by, updated_by, claimed_by, created_at, updated_at, log: list[LogEntry])`
  with `.ref` (`"#12"`), `.to_dict()` and `.copy()`
- `LogEntry(at, by, kind, text, data={})`, where kind is one of `note|status|edit|summary|create|question|answer`.
  `data` is only used by the last two: a `question` entry holds `{"options": [...], "multi": bool}` (its `text` is the
  question), an `answer` entry holds `{"choices": [...], "text": "..."}`. Empty `data` is not written, so old board files load unchanged.
- `Item.open_question() -> Question|None` (the latest `question` entry with no `answer` after it) and
  `Item.latest_answer() -> Answer|None` (the reply to the latest question); `Question(text, options, multi, at, by)`,
  `Answer(choices, text, question, at, by)`, each with `.to_dict()`
- `Board(board_id, repo_name, repo_path, rev, next_id, updated_at, items)` with
  `.get(id)`, `.sorted_items(statuses=None|str|list, by="priority")` (None means every FLOW status, i.e. everything except archived; `by` is a `SORTS` key: `priority` = priority, rank, id; also `activity`, `created`, `oldest`, `number`) and `.counts()`
- `SORTS` (sort name -> label) and `sort_items(items, by="priority")`

### `triage.store`
- `BoardStore(ref)`: `.ref`, `.path`, `.load() -> Board`, `.exists()`, `.stat_token()` (a cheap `(mtime_ns, size)`, used for polling), `.transaction()` (private to `ops`)
- `list_boards() -> list[dict]` (board_id, name, path, updated_at, opened_at?), most recent first
- `touch_registry(ref, opened=True)`: call it when the TUI opens a board
- `LockTimeout`

### `triage.config`
- `SETTINGS` (a tuple of `Setting(key, kind, default, help, choices)`), `SETTINGS_BY_KEY`, `DEFAULTS`
- `get_config(board_id=None) -> dict` (effective flat dict: defaults, then global, then the board's overrides)
- `overrides(board_id=None) -> dict` (only the values explicitly set at that level)
- `parse_value(key, text)`, `set_value(key, value, board_id=None)` (`value=None` removes the override), `ConfigError`.
  `set_value` is atomic and locked, and edits only the one line in its table (replace it, or append under the table
  header, creating the header if missing; `[boards."id".agent]` tables work the same). Comments, other tables and
  the `[keys]` table survive. It falls back to a full rewrite (comments lost) only if the edited text would not
  parse to the expected data. Invalid TOML on disk still raises `ConfigError`.
- `keys_table()`: the raw global `[keys]` table, or `None` (global only; there are no per-board keys).
- `default_config_text(keys_section="")`, `init_target(path=None)`, `init_config(path=None, keys_section="", force=False)`:
  the generated default `config.toml` (every setting at its default with its help text as a `#` comment, plus the
  `[keys]` text). `init_config` is locked and atomic and raises `ConfigError` when the file exists and `force` is false;
  a directory path means `<dir>/config.toml`. The CLI (`triage config init`) adds the actor rule: creating a new file is
  allowed for any actor, `--force` overwriting needs `--as user`.

| key | default |
|---|---|
| agent.finish_status | `review` (review/done) |
| agent.pickup_statuses | `["todo"]` (subset of inbox/todo) |
| agent.create_status | `inbox` |
| agent.can_create | true |
| agent.can_edit | false (applies to items the user created; agents may always edit their own) |
| agent.can_archive | false |
| agent.require_claim | true |
| ui.new_item_status | `inbox` |
| ui.confirm_delete | true |
| ui.poll_seconds | 1.0 |
| ui.sort | `priority` (a `SORTS` key) |

### `triage.ops` (all mutations; each returns `Change`)
`Item.claimed_by` is the one "taken by" tag: `None` = none, the agent's name (default `agent`) = the agent took it, `"user"` = reserved by the user. For `actor="agent"`, every mutation of an item tagged `user` raises `PermissionDenied` (force does not help), `next_item` skips it, and the agent may not claim under the name `user`. The user's tag survives status moves.
Errors: `TriageError` (base; print the message), `NotFound`, `PermissionDenied`, `InvalidOperation`.
Model `ValueError`s from bad type/status/priority strings and `ConfigError` can also come through.
Front ends should catch `(TriageError, ValueError)`.

`Change(op, before: Item|None, after: Item|None, meta)` has `.item` and `.changed`. Undo is `ops.revert(store, change, actor=...)`.

| function | notes |
|---|---|
| `open_store(repo=None) -> BoardStore` | resolves the cwd or `$TRIAGE_REPO` |
| `config_for(store) -> dict` | effective config for the board |
| `load(store) -> Board`, `get(store, id) -> Item` | reads |
| `next_item(board, cfg) -> Item\|None` | unclaimed, from the pickup statuses, todo first |
| `item_json(item) -> dict` | stable JSON shape (adds `ref`, `question` = the open question or null, `answer` = the reply to the latest question or null) |
| `add(store, title, *, actor, body="", type="feature", priority=3, status=None, taken_by=None)` | the default status comes from config, per actor; `taken_by` is user only |
| `update(store, id, *, actor, title=None, body=None, type=None, priority=None, taken_by=None)` | `taken_by` (`none`/`agent`/a name/`user`, user only) sets `claimed_by`, logged as `taken by: a -> b`, undoable |
| `set_status(store, id, status, *, actor, note=None)` | |
| `advance(store, id, *, actor, step=1)` | moves along FLOW; raises `InvalidOperation` at either end |
| `claim(store, id=None, *, actor="agent", who=None, force=False)` | → doing; `id=None` claims the next item |
| `release(store, id, *, actor="agent", note=None)` | → todo, claim cleared |
| `finish(store, id, *, actor="agent", summary="")` | agent → `agent.finish_status`; user → done |
| `accept(store, id, *, actor="user", note=None)` | review → done |
| `bounce(store, id, reason="", *, actor="user")` | review/done → todo, logs "bounced: reason"; user only (agents get PermissionDenied) |
| `note(store, id, text, *, actor)` | allowed unless an agent targets a `user`-tagged item |
| `ask(store, id, question, options, multi=False, *, actor="agent")` | logs a `question`; 2-6 distinct non-empty options; asking again replaces an open question; allowed unless an agent targets a `user`-tagged item |
| `answer(store, id, choices, text="", *, actor="user", question=None)` | logs an `answer` to the open question (`InvalidOperation` when there is none, or when `question`, the one the user saw, was replaced); choices must be options (one unless `multi`), free text may replace or add to them; agents get PermissionDenied; undoable (`revert` removes the reply and reopens the question) |
| `reorder(store, id, delta, *, actor)` | moves within the status column; adopts the neighbour's priority when crossing a band; meta has the delta |
| `archive(store, id, *, actor)` | → archived (soft delete) |
| `purge(store, id, *, actor)` | permanent delete |
| `revert(store, change, *, actor)` | undo as a new transaction; removes the undone change's log entries and logs nothing itself (entries written meanwhile stay) |

### Keybindings (`triage.tui.keys`)
A `[keys]` table in the global `config.toml` maps a command name to `"key1, key2"` (or a TOML list of strings).
Keys are Textual names (`ctrl+d`, `down`, `question_mark`) or literal characters (`?`, `/`, `,`, `+`, `-`, `=`, `space`),
normalised with `normalize_key`; `display_key` goes back (`question_mark` -> `?`).

- `COMMANDS`: the stable command names with default keys, group, description, app actions and contexts. Context twins share one
  entry: `back` (detail_back + clear_filter), `advance` (advance + restore), `accept` (accept + accept_hint),
  `purge` (purge + purge_hint). `move`, `priority` and `archive` are chords; only their first key is configurable.
- `build_keymap(user_table) -> Keymap` overlays the table on the defaults and never raises. It validates unknown
  commands, empty or unknown key names and one key bound to two commands whose contexts overlap; each invalid entry falls
  back to its default and is recorded in `Keymap.problems`. `Keymap.warning()` is the one-line startup message.
  `load_keymap()` reads the config (a broken file gives the defaults plus a warning).
- `bindings(keymap)` builds the Textual bindings. The app adds them per instance in `TriageApp.__init__` (Textual collects
  class-level `BINDINGS` once per class, so the configurable ones cannot live there). Printable keys are never priority bindings.
- `HINT_CONTEXTS` (empty, item, review, archived, detail, filter) and `hint_entries` / `fit_hints` drive the bottom key-hint
  bar; `help_sections(keymap)` drives the `?` screen. Both show the effective keys.
- Key changes apply when the TUI starts, not while it runs.

CLI: `triage config init [PATH] [--force]`, `triage config keys [--json]`.

Tests: `tests/conftest.py` provides an autouse `triage_home` (an isolated `$TRIAGE_HOME`), a `repo` (a scratch git repo with one commit) and a `store`.
