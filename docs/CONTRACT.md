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
`triage_home()`, `boards_dir()`, `registry_path()`, `config_path()`, `board_path(board_id)`,
`resolve_repo(path=None) -> RepoRef(root: Path, name: str, board_id: str)` (it has a `.board_path` property),
`RepoNotFound` (exception).

### `triage.model`
- `FLOW = ("inbox","todo","doing","review","done")`, `STATUSES = FLOW + ("archived",)`
- `TYPES = ("feature","fix","change","chore","idea")`, `PRIORITIES = (1,2,3,4)` (1 = urgent), `PRIORITY_LABELS`
- `TYPE_ALIASES` / `STATUS_ALIASES`: `normalize_type(s)`, `normalize_status(s)`, `normalize_priority(v)` (each raises `ValueError`)
- `Item(id, title, body, type, priority, status, rank, created_by, updated_by, claimed_by, created_at, updated_at, log: list[LogEntry])`
  with `.ref` (`"#12"`), `.to_dict()` and `.copy()`
- `LogEntry(at, by, kind, text)`, where kind is one of `note|status|edit|summary|create`
- `Board(board_id, repo_name, repo_path, rev, next_id, updated_at, items)` with
  `.get(id)`, `.sorted_items(statuses=None|str|list)` (None means every FLOW status, i.e. everything except archived; order is priority, rank, id) and `.counts()`

### `triage.store`
- `BoardStore(ref)`: `.ref`, `.path`, `.load() -> Board`, `.exists()`, `.stat_token()` (a cheap `(mtime_ns, size)`, used for polling), `.transaction()` (private to `ops`)
- `list_boards() -> list[dict]` (board_id, name, path, updated_at, opened_at?), most recent first
- `touch_registry(ref, opened=True)`: call it when the TUI opens a board
- `LockTimeout`

### `triage.config`
- `SETTINGS` (a tuple of `Setting(key, kind, default, help, choices)`), `SETTINGS_BY_KEY`, `DEFAULTS`
- `get_config(board_id=None) -> dict` (effective flat dict: defaults, then global, then the board's overrides)
- `overrides(board_id=None) -> dict` (only the values explicitly set at that level)
- `parse_value(key, text)`, `set_value(key, value, board_id=None)` (`value=None` removes the override), `ConfigError`

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

### `triage.ops` (all mutations; each returns `Change`)
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
| `item_json(item) -> dict` | stable JSON shape (adds `ref`) |
| `add(store, title, *, actor, body="", type="feature", priority=3, status=None)` | the default status comes from config, per actor |
| `update(store, id, *, actor, title=None, body=None, type=None, priority=None)` | |
| `set_status(store, id, status, *, actor, note=None)` | |
| `advance(store, id, *, actor, step=1)` | moves along FLOW; raises `InvalidOperation` at either end |
| `claim(store, id=None, *, actor="agent", who=None, force=False)` | → doing; `id=None` claims the next item |
| `release(store, id, *, actor="agent", note=None)` | → todo, claim cleared |
| `finish(store, id, *, actor="agent", summary="")` | agent → `agent.finish_status`; user → done |
| `accept(store, id, *, actor="user", note=None)` | review → done |
| `bounce(store, id, reason="", *, actor="user")` | review/done → todo, logs "bounced: reason"; user only (agents get PermissionDenied) |
| `note(store, id, text, *, actor)` | always allowed |
| `reorder(store, id, delta, *, actor)` | moves within the status column; adopts the neighbour's priority when crossing a band; meta has the delta |
| `archive(store, id, *, actor)` | → archived (soft delete) |
| `purge(store, id, *, actor)` | permanent delete |
| `revert(store, change, *, actor)` | undo as a new transaction; keeps the log |

Tests: `tests/conftest.py` provides an autouse `triage_home` (an isolated `$TRIAGE_HOME`), a `repo` (a scratch git repo with one commit) and a `store`.
