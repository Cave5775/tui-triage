import pytest

from triage import ops
from triage.config import set_value
from triage.ops import InvalidOperation, NotFound, PermissionDenied


def test_add_defaults_by_actor(store):
    u = ops.add(store, "user thing").after
    a = ops.add(store, "agent thing", actor="agent", type="fix", priority=1).after
    assert (u.status, u.created_by, u.id) == ("inbox", "user", 1)
    assert (a.status, a.created_by, a.type, a.priority, a.id) == ("inbox", "agent", "fix", 1, 2)


def test_agent_full_cycle_default_goes_to_review(store):
    item = ops.add(store, "x", status="todo").after
    assert ops.next_item(store.load(), ops.config_for(store)).id == item.id
    c = ops.claim(store, actor="agent")
    assert (c.after.status, c.after.claimed_by) == ("doing", "agent")
    ops.note(store, item.id, "halfway", actor="agent")
    f = ops.finish(store, item.id, actor="agent", summary="did it")
    assert f.after.status == "review"
    assert [e.kind for e in f.after.log][-2:] == ["summary", "status"]
    assert ops.accept(store, item.id).after.status == "done"


def test_agent_finish_status_configurable(store):
    set_value("agent.finish_status", "done", board_id=store.ref.board_id)
    item = ops.add(store, "x", status="todo").after
    ops.claim(store, item.id, actor="agent")
    assert ops.finish(store, item.id, actor="agent").after.status == "done"


def test_agent_rules(store):
    item = ops.add(store, "user item", status="inbox").after
    with pytest.raises(PermissionDenied):
        ops.claim(store, item.id, actor="agent")  # inbox not in pickup by default
    with pytest.raises(PermissionDenied):
        ops.update(store, item.id, actor="agent", title="changed")
    with pytest.raises(PermissionDenied):
        ops.set_status(store, item.id, "done", actor="agent")
    with pytest.raises(PermissionDenied):
        ops.archive(store, item.id, actor="agent")
    with pytest.raises(PermissionDenied):
        ops.finish(store, item.id, actor="agent")  # not claimed
    ops.note(store, item.id, "notes are always fine", actor="agent")
    own = ops.add(store, "agent item", actor="agent").after
    assert ops.update(store, own.id, actor="agent", title="renamed").after.title == "renamed"
    set_value("agent.can_create", False)
    with pytest.raises(PermissionDenied):
        ops.add(store, "nope", actor="agent")


def test_claim_conflict_and_release(store):
    item = ops.add(store, "x", status="todo").after
    ops.claim(store, item.id, actor="agent", who="agent-a")
    with pytest.raises(InvalidOperation):
        ops.claim(store, item.id, actor="agent", who="agent-b")
    r = ops.release(store, item.id, actor="agent", note="blocked")
    assert (r.after.status, r.after.claimed_by) == ("todo", None)


def test_bounce_logs_reason(store):
    item = ops.add(store, "x", status="todo").after
    ops.claim(store, item.id, actor="agent")
    ops.finish(store, item.id, actor="agent")
    with pytest.raises(PermissionDenied):
        ops.bounce(store, item.id, "self-bounce", actor="agent")
    b = ops.bounce(store, item.id, "tests fail")
    assert b.after.status == "todo" and b.after.claimed_by is None
    assert b.after.log[-1].text == "bounced: tests fail"


def test_advance_and_bounds(store):
    item = ops.add(store, "x").after
    assert ops.advance(store, item.id).after.status == "todo"
    assert ops.advance(store, item.id, step=-1).after.status == "inbox"
    with pytest.raises(InvalidOperation):
        ops.advance(store, item.id, step=-1)


def test_reorder_crosses_priority_band(store):
    a = ops.add(store, "a", priority=2).after
    b = ops.add(store, "b", priority=3).after
    c = ops.add(store, "c", priority=3).after
    ch = ops.reorder(store, a.id, +1)
    order = [i.title for i in store.load().sorted_items("inbox")]
    assert order == ["b", "a", "c"]
    assert store.load().get(a.id).priority == 3
    ops.revert(store, ch)
    assert [i.title for i in store.load().sorted_items("inbox")] == ["a", "b", "c"]
    assert ops.reorder(store, a.id, -1).meta["delta"] == 0


def test_revert_keeps_log_and_undoes_add_and_purge(store):
    item = ops.add(store, "x").after
    ch = ops.update(store, item.id, title="y", priority=1)
    ops.note(store, item.id, "agent note", actor="agent")
    r = ops.revert(store, ch).after
    assert (r.title, r.priority) == ("x", 3)
    assert any(e.text == "agent note" for e in r.log)
    p = ops.purge(store, item.id)
    assert store.load().get(item.id) is None
    ops.revert(store, p)
    assert store.load().get(item.id).title == "x"
    added = ops.add(store, "temp")
    ops.revert(store, added)
    assert store.load().get(added.after.id) is None
    with pytest.raises(NotFound):
        ops.get(store, 999)


def test_agent_set_status_cannot_skip_claim_or_reopen(store):
    inbox = ops.add(store, "inbox item").after
    with pytest.raises(PermissionDenied):
        ops.set_status(store, inbox.id, "doing", actor="agent")  # must claim
    with pytest.raises(PermissionDenied):
        ops.set_status(store, inbox.id, "todo", actor="agent")  # user's item, can_edit=false
    done = ops.add(store, "done item", status="done").after
    with pytest.raises(PermissionDenied):
        ops.set_status(store, done.id, "todo", actor="agent")
    with pytest.raises(InvalidOperation):
        ops.release(store, done.id, actor="agent")
    todo = ops.add(store, "todo item", status="todo").after
    ops.claim(store, todo.id, actor="agent")
    assert ops.set_status(store, todo.id, "todo", actor="agent").after.status == "todo"  # releasing own claim
    own = ops.add(store, "agent idea", actor="agent").after
    assert ops.set_status(store, own.id, "todo", actor="agent").after.status == "todo"


def test_revert_does_not_clobber_concurrent_agent_changes(store):
    item = ops.add(store, "x", status="todo").after
    bump = ops.update(store, item.id, priority=1)  # user change
    ops.claim(store, item.id, actor="agent")  # agent works on it meanwhile
    r = ops.revert(store, bump).after
    assert r.priority == 3  # user's own change undone
    assert (r.status, r.claimed_by) == ("doing", "agent")  # agent's claim survives

    moved = ops.set_status(store, item.id, "review", actor="user")
    ops.set_status(store, item.id, "done", actor="user")  # changed again since
    with pytest.raises(InvalidOperation):
        ops.revert(store, moved)


def test_undo_add_refused_after_agent_touched_it(store):
    added = ops.add(store, "x", status="todo")
    ops.note(store, added.after.id, "on it", actor="agent")
    with pytest.raises(InvalidOperation):
        ops.revert(store, added)
    assert store.load().get(added.after.id) is not None


def test_every_undo_writes_a_descriptive_log_entry(store):
    """triage #8: undo must show up in the item's activity log, saying what was reverted."""
    a = ops.add(store, "a", status="todo").after
    b = ops.add(store, "b", status="todo").after
    cases = [
        (lambda: ops.advance(store, a.id), "undo: status doing -> todo"),
        (lambda: ops.update(store, a.id, priority=1, type="fix"), "undo: type fix -> feature, priority P1 -> P3"),
        (lambda: ops.reorder(store, b.id, -1), "undo: moved back"),
        (lambda: ops.archive(store, a.id), "undo: status archived -> todo"),
    ]
    for make, expected in cases:
        change = make()
        ops.revert(store, change)
        last = store.load().get(change.item.id).log[-1]
        assert (last.kind, last.by, last.text) == ("edit", "user", expected)
