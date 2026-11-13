"""All board mutations. The ONLY module that changes board data.

Every function runs one locked transaction (see ``store.BoardStore.transaction``)
and returns a :class:`Change` holding deep copies of the item before and after.
``actor`` is ``"user"`` (TUI / human) or ``"agent"`` (CLI default); agent
permissions are enforced from the effective config for the board.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import get_config
from .model import (
    ACTORS,
    FLOW,
    Board,
    Item,
    LogEntry,
    normalize_priority,
    normalize_status,
    normalize_type,
    now_iso,
    sort_key,
)
from .paths import resolve_repo
from .store import BoardStore


# ---- errors -----------------------------------------------------------------

class TriageError(Exception):
    """Base class for user-facing errors (CLI prints the message and exits 1)."""


class NotFound(TriageError):
    pass


class PermissionDenied(TriageError):
    """The actor is not allowed to do this under the current config."""


class InvalidOperation(TriageError):
    """The operation does not make sense for the item's current state."""


# ---- change record ----------------------------------------------------------

@dataclass(frozen=True)
class Change:
    op: str
    before: Item | None
    after: Item | None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def item(self) -> Item:
        return self.after if self.after is not None else self.before  # type: ignore[return-value]

    @property
    def changed(self) -> bool:
        return self.before is None or self.after is None or self.before.to_dict() != self.after.to_dict()


# ---- helpers ----------------------------------------------------------------

def open_store(repo: str | Path | None = None) -> BoardStore:
    """Resolve a repo path (default cwd / $TRIAGE_REPO) and return its store."""
    return BoardStore(resolve_repo(repo))


def config_for(store: BoardStore) -> dict[str, Any]:
    return get_config(store.ref.board_id)


def _check_actor(actor: str) -> None:
    if actor not in ACTORS:
        raise TriageError(f"actor must be one of {ACTORS}, got {actor!r}")


def _require(board: Board, item_id: int) -> Item:
    item = board.get(int(item_id))
    if item is None:
        raise NotFound(f"no item #{item_id} on this board")
    return item


def _log(item: Item, actor: str, kind: str, text: str) -> None:
    item.log.append(LogEntry(at=now_iso(), by=actor, kind=kind, text=text))


def _touch(item: Item, actor: str) -> None:
    item.updated_by = actor
    item.updated_at = now_iso()


def _apply_status(item: Item, target: str, actor: str) -> None:
    if item.status == target:
        return
    _log(item, actor, "status", f"{item.status} -> {target}")
    item.status = target
    if target in ("inbox", "todo"):
        item.claimed_by = None
    _touch(item, actor)


def _agent_status_rule(cfg: dict, item: Item, target: str) -> None:
    """Raise PermissionDenied if the agent may not move ``item`` to ``target``."""
    if target == "done" and cfg["agent.finish_status"] != "done":
        raise PermissionDenied(
            "agent may not mark items done (agent.finish_status = review); "
            "use `triage done ID --summary ...` to send it to review"
        )
    if "archived" in (target, item.status) and not cfg["agent.can_archive"]:
        raise PermissionDenied("agent may not archive or unarchive items (agent.can_archive = false)")
    if target in ("review", "done") and cfg["agent.require_claim"] and not item.claimed_by:
        raise PermissionDenied(f"claim #{item.id} first (agent.require_claim = true)")
    if target == "doing" and item.status != "doing":
        raise PermissionDenied(f"use `triage claim {item.id}` to start work; it checks the pickup rules")
    if target in ("inbox", "todo"):
        releasing = item.status == "doing" and item.claimed_by
        if item.status in ("review", "done") and item.created_by != "agent" and not cfg["agent.can_edit"]:
            raise PermissionDenied(f"#{item.id} is {item.status}; reopening reviewed work is the user's call")
        if not releasing:
            _agent_edit_rule(cfg, item)


def _agent_edit_rule(cfg: dict, item: Item) -> None:
    if item.created_by != "agent" and not cfg["agent.can_edit"]:
        raise PermissionDenied(
            f"agent may not edit #{item.id}, which the user created (agent.can_edit = false); "
            "add a note instead"
        )


def _snapshot(item: Item | None) -> Item | None:
    return item.copy() if item is not None else None


# ---- queries ----------------------------------------------------------------

def load(store: BoardStore) -> Board:
    return store.load()


def get(store: BoardStore, item_id: int) -> Item:
    return _require(store.load(), item_id)


def next_item(board: Board, cfg: dict[str, Any]) -> Item | None:
    """Best unclaimed item for the agent: from pickup statuses, todo before inbox, then priority/rank."""
    pickup = cfg["agent.pickup_statuses"]
    candidates = [i for i in board.items if i.status in pickup and not i.claimed_by]
    candidates.sort(key=lambda i: (i.status != "todo",) + sort_key(i))
    return candidates[0] if candidates else None


def item_json(item: Item) -> dict[str, Any]:
    """Stable JSON shape for CLI output."""
    d = item.to_dict()
    d["ref"] = item.ref
    return d


# ---- mutations --------------------------------------------------------------

def add(
    store: BoardStore,
    title: str,
    *,
    actor: str = "user",
    body: str = "",
    type: str = "feature",
    priority: int | str = 3,
    status: str | None = None,
) -> Change:
    _check_actor(actor)
    title = title.strip()
    if not title:
        raise InvalidOperation("title must not be empty")
    cfg = config_for(store)
    t, p = normalize_type(type), normalize_priority(priority)
    if actor == "agent":
        if not cfg["agent.can_create"]:
            raise PermissionDenied("agent may not create items (agent.can_create = false)")
        st = normalize_status(status) if status else cfg["agent.create_status"]
        if st not in ("inbox", "todo"):
            raise PermissionDenied("agent-created items must start in inbox or todo")
    else:
        st = normalize_status(status) if status else cfg["ui.new_item_status"]
    with store.transaction() as board:
        rank = max((i.rank for i in board.items), default=0.0) + 1.0
        item = Item(
            id=board.next_id, title=title, body=body, type=t, priority=p, status=st, rank=rank,
            created_by=actor, updated_by=actor,
        )
        _log(item, actor, "create", f"created in {st}")
        board.next_id += 1
        board.items.append(item)
        return Change("add", None, _snapshot(item))


def update(
    store: BoardStore,
    item_id: int,
    *,
    actor: str = "user",
    title: str | None = None,
    body: str | None = None,
    type: str | None = None,
    priority: int | str | None = None,
) -> Change:
    _check_actor(actor)
    cfg = config_for(store)
    with store.transaction() as board:
        item = _require(board, item_id)
        if actor == "agent":
            _agent_edit_rule(cfg, item)
        before = _snapshot(item)
        changes = []
        if title is not None:
            if not title.strip():
                raise InvalidOperation("title must not be empty")
            if title.strip() != item.title:
                item.title = title.strip()
                changes.append("title")
        if body is not None and body != item.body:
            item.body = body
            changes.append("body")
        if type is not None:
            t = normalize_type(type)
            if t != item.type:
                changes.append(f"type {item.type} -> {t}")
                item.type = t
        if priority is not None:
            p = normalize_priority(priority)
            if p != item.priority:
                changes.append(f"priority P{item.priority} -> P{p}")
                item.priority = p
        if changes:
            _log(item, actor, "edit", ", ".join(changes))
            _touch(item, actor)
        return Change("update", before, _snapshot(item))


def set_status(store: BoardStore, item_id: int, status: str, *, actor: str = "user", note: str | None = None) -> Change:
    _check_actor(actor)
    target = normalize_status(status)
    cfg = config_for(store)
    with store.transaction() as board:
        item = _require(board, item_id)
        if actor == "agent":
            _agent_status_rule(cfg, item, target)
        before = _snapshot(item)
        _apply_status(item, target, actor)
        if note:
            _log(item, actor, "note", note)
        return Change("set_status", before, _snapshot(item))


def advance(store: BoardStore, item_id: int, *, actor: str = "user", step: int = 1) -> Change:
    """Move one step along the flow (inbox -> todo -> doing -> review -> done); negative step goes back."""
    item = get(store, item_id)
    if item.status not in FLOW:
        raise InvalidOperation(f"#{item.id} is {item.status}; unarchive it first")
    idx = max(0, min(len(FLOW) - 1, FLOW.index(item.status) + step))
    if FLOW[idx] == item.status:
        raise InvalidOperation(f"#{item.id} is already {item.status}")
    return set_status(store, item_id, FLOW[idx], actor=actor)


def claim(store: BoardStore, item_id: int | None = None, *, actor: str = "agent",
          who: str | None = None, force: bool = False) -> Change:
    """Mark an item as being worked on (-> doing). ``item_id=None`` claims :func:`next_item`."""
    _check_actor(actor)
    cfg = config_for(store)
    with store.transaction() as board:
        if item_id is None:
            item = next_item(board, cfg)
            if item is None:
                raise NotFound("nothing to pick up (no unclaimed items in " + ", ".join(cfg["agent.pickup_statuses"]) + ")")
        else:
            item = _require(board, item_id)
        if item.claimed_by and item.claimed_by != (who or actor) and not force:
            raise InvalidOperation(f"#{item.id} is already claimed by {item.claimed_by} (use force to take over)")
        if actor == "agent":
            allowed = set(cfg["agent.pickup_statuses"]) | {"doing"}
            if item.status not in allowed:
                raise PermissionDenied(
                    f"#{item.id} is {item.status}; agent may only claim from {', '.join(cfg['agent.pickup_statuses'])}"
                )
        elif item.status not in FLOW or item.status == "done":
            raise InvalidOperation(f"#{item.id} is {item.status} and cannot be claimed")
        before = _snapshot(item)
        _apply_status(item, "doing", actor)
        item.claimed_by = who or actor
        _touch(item, actor)
        return Change("claim", before, _snapshot(item))


def release(store: BoardStore, item_id: int, *, actor: str = "agent", note: str | None = None) -> Change:
    """Give up a claim; the item returns to todo."""
    _check_actor(actor)
    with store.transaction() as board:
        item = _require(board, item_id)
        if actor == "agent" and item.status != "doing":
            raise InvalidOperation(f"#{item.id} is {item.status}, not claimed; nothing to release")
        before = _snapshot(item)
        item.claimed_by = None
        _apply_status(item, "todo", actor)
        if note:
            _log(item, actor, "note", note)
        _touch(item, actor)
        return Change("release", before, _snapshot(item))


def finish(store: BoardStore, item_id: int, *, actor: str = "agent", summary: str = "") -> Change:
    """Work is complete. Agents go to ``agent.finish_status`` (default review); users go to done."""
    _check_actor(actor)
    cfg = config_for(store)
    with store.transaction() as board:
        item = _require(board, item_id)
        target = cfg["agent.finish_status"] if actor == "agent" else "done"
        if item.status in ("done", "archived"):
            raise InvalidOperation(f"#{item.id} is already {item.status}")
        if actor == "agent":
            if cfg["agent.require_claim"] and not item.claimed_by:
                raise PermissionDenied(f"claim #{item.id} before finishing it (agent.require_claim = true)")
            _agent_status_rule(cfg, item, target)
        before = _snapshot(item)
        if summary:
            _log(item, actor, "summary", summary)
        _apply_status(item, target, actor)
        return Change("finish", before, _snapshot(item))


def accept(store: BoardStore, item_id: int, *, actor: str = "user", note: str | None = None) -> Change:
    """Approve reviewed work: review -> done."""
    item = get(store, item_id)
    if item.status != "review":
        raise InvalidOperation(f"#{item.id} is {item.status}, not in review")
    return set_status(store, item_id, "done", actor=actor, note=note)


def bounce(store: BoardStore, item_id: int, reason: str = "", *, actor: str = "user") -> Change:
    """Send reviewed work back: review/done -> todo, with the reason logged for the agent."""
    _check_actor(actor)
    cfg = config_for(store)
    with store.transaction() as board:
        item = _require(board, item_id)
        if item.status not in ("review", "done"):
            raise InvalidOperation(f"#{item.id} is {item.status}; only review/done items can be bounced")
        if actor == "agent":
            raise PermissionDenied(
                "review decisions belong to the user; agents may not bounce items "
                "(add a note instead, or claim it again once it is back in todo)"
            )
        before = _snapshot(item)
        _apply_status(item, "todo", actor)
        if reason:
            _log(item, actor, "note", f"bounced: {reason}")
        return Change("bounce", before, _snapshot(item))


def note(store: BoardStore, item_id: int, text: str, *, actor: str = "user") -> Change:
    _check_actor(actor)
    if not text.strip():
        raise InvalidOperation("note must not be empty")
    with store.transaction() as board:
        item = _require(board, item_id)
        before = _snapshot(item)
        _log(item, actor, "note", text.strip())
        _touch(item, actor)
        return Change("note", before, _snapshot(item))


def reorder(store: BoardStore, item_id: int, delta: int, *, actor: str = "user") -> Change:
    """Move an item ``delta`` places within its status column (+ = down).

    Crossing into a neighbouring priority band adopts that band's priority, so the
    visible order always matches what the user asked for.
    """
    _check_actor(actor)
    cfg = config_for(store)
    with store.transaction() as board:
        item = _require(board, item_id)
        if actor == "agent":
            _agent_edit_rule(cfg, item)
        before = _snapshot(item)
        column = board.sorted_items(item.status)
        i = column.index(item)
        j = max(0, min(len(column) - 1, i + int(delta)))
        if i == j:
            return Change("reorder", before, _snapshot(item), {"delta": 0})
        neighbour = column[j]
        column.pop(i)
        column.insert(j, item)
        if neighbour.priority != item.priority:
            _log(item, actor, "edit", f"priority P{item.priority} -> P{neighbour.priority}")
            item.priority = neighbour.priority
        for pos, it in enumerate(column):
            it.rank = float(pos + 1)
        _touch(item, actor)
        return Change("reorder", before, _snapshot(item), {"delta": j - i})


def archive(store: BoardStore, item_id: int, *, actor: str = "user") -> Change:
    return set_status(store, item_id, "archived", actor=actor)


def purge(store: BoardStore, item_id: int, *, actor: str = "user") -> Change:
    """Permanently delete an item."""
    _check_actor(actor)
    cfg = config_for(store)
    if actor == "agent" and not cfg["agent.can_archive"]:
        raise PermissionDenied("agent may not delete items (agent.can_archive = false)")
    with store.transaction() as board:
        item = _require(board, item_id)
        board.items.remove(item)
        return Change("purge", _snapshot(item), None)


_RESTORED_FIELDS = ("title", "body", "type", "priority", "status", "rank", "claimed_by")


def revert(store: BoardStore, change: Change, *, actor: str = "user") -> Change:
    """Undo a previous :class:`Change` as a new transaction (safe alongside other writers).

    The item's activity log is kept (so notes written meanwhile are not lost) and an
    ``undo`` entry is appended.
    """
    _check_actor(actor)
    if change.op == "reorder":
        delta = change.meta.get("delta", 0)
        if not delta:
            return change
        return reorder(store, change.item.id, -delta, actor=actor)
    with store.transaction() as board:
        if change.before is None:  # undo add
            item = board.get(change.after.id)  # type: ignore[union-attr]
            if item is None:
                raise NotFound(f"#{change.after.id} no longer exists")  # type: ignore[union-attr]
            if any(e.by != actor for e in item.log) or item.updated_by != actor:
                raise InvalidOperation(
                    f"{item.ref} has been worked on by someone else since it was added; archive it instead"
                )
            board.items.remove(item)
            return Change("revert", _snapshot(item), None)
        current = board.get(change.before.id)
        if current is None:  # undo purge
            restored = change.before.copy()
            _log(restored, actor, "edit", "restored (undo delete)")
            board.items.append(restored)
            board.next_id = max(board.next_id, restored.id + 1)
            return Change("revert", None, _snapshot(restored))
        # Three-way, per field: only restore what this change altered AND nobody has
        # changed since, so concurrent edits (e.g. an agent claiming the item) survive.
        before = _snapshot(current)
        restored, conflicts = [], []
        for f in _RESTORED_FIELDS:
            old, new = getattr(change.before, f), getattr(change.after, f)
            if old == new:
                continue
            if getattr(current, f) == new:
                setattr(current, f, old)
                restored.append(f)
            else:
                conflicts.append(f)
        if not restored:
            if conflicts:
                raise InvalidOperation(
                    f"{current.ref} was changed since ({', '.join(conflicts)}); nothing to undo safely"
                )
            return Change("revert", before, _snapshot(current))
        if "status" in restored and current.status in ("inbox", "todo"):
            current.claimed_by = None
        _log(current, actor, "edit", f"undo {change.op}" + (f" (kept newer {', '.join(conflicts)})" if conflicts else ""))
        _touch(current, actor)
        return Change("revert", before, _snapshot(current))
