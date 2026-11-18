"""TUI tests, driven through Textual's Pilot with a 120x40 terminal."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import time

import pytest
from textual.screen import ModalScreen
from textual.widgets import Footer

from triage import config, ops
from triage.paths import resolve_repo
from triage.store import BoardStore
from triage.tui import keys
from triage.tui.app import TriageApp, edit_text_externally, resolve_editor
from triage.tui.quickadd import parse_quick_add
from triage.tui.screens import HelpScreen, RepoPickerScreen, SettingsScreen, fuzzy_score
from triage.tui.widgets import KeyHints

SIZE = (120, 40)


def typed(text: str) -> list[str]:
    """Key names for typing ``text`` literally."""
    names = {" ": "space", "!": "exclamation_mark", "#": "number_sign", ">": "greater_than_sign", "-": "minus",
             ",": "comma", ".": "full_stop", "/": "slash", "?": "question_mark", "'": "apostrophe", ":": "colon"}
    return [names.get(c, c) for c in text]


def seed(store, *specs):
    """Add items as the user: (title, status, priority) tuples. Returns the ids."""
    out = []
    for title, status, prio in specs:
        out.append(ops.add(store, title, actor="user", status=status, priority=prio).item.id)
    return out


def ids(app) -> list[int]:
    return app.items_view.ids()


def selected(app):
    return app.items_view.selected_id


async def settle(pilot, n: int = 2) -> None:
    for _ in range(n):
        await pilot.pause()


# ---- parse_quick_add -----------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("fix the login", dict(title="fix the login", priority=None, type=None, status=None)),
        ("fix the login !1 #fix >todo", dict(title="fix the login", priority=1, type="fix", status="todo")),
        ("!2 #feat add dark mode", dict(title="add dark mode", priority=2, type="feature", status=None)),
        ("tokens #bug in the middle >wip of the title", dict(title="tokens in the middle of the title", priority=None, type="fix", status="doing")),
        ("  extra   spaces   !4 ", dict(title="extra spaces", priority=4, type=None, status=None)),
        ("later one wins !1 !3 #idea #chore", dict(title="later one wins", priority=3, type="chore", status=None)),
        ("unknown tokens stay #12 !9 >nowhere #nope", dict(title="unknown tokens stay #12 !9 >nowhere #nope", priority=None, type=None, status=None)),
        ("CASE !2 #FIX >TODO", dict(title="CASE", priority=2, type="fix", status="todo")),
        ("#refactor this >in", dict(title="this", priority=None, type="change", status="inbox")),
        ("", dict(title="", priority=None, type=None, status=None)),
        ("#fix", dict(title="", priority=None, type="fix", status=None)),
        ("a > b", dict(title="a > b", priority=None, type=None, status=None)),
    ],
)
def test_parse_quick_add(text, expected):
    assert parse_quick_add(text) == expected


def test_fuzzy_score():
    assert fuzzy_score("", "anything") == 0
    assert fuzzy_score("trg", "triage-board") is not None
    assert fuzzy_score("zzz", "triage-board") is None
    assert fuzzy_score("tri", "triage") < fuzzy_score("tri", "a very long name with t r i spread out")


# ---- quick add -----------------------------------------------------------------

async def test_quick_add_creates_item_with_parsed_fields(store):
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("a")
        await settle(pilot)
        assert isinstance(app.screen, ModalScreen)
        await pilot.press(*typed("fix the login loop !1 #fix >todo"))
        await pilot.press("enter")
        await settle(pilot)
        assert not isinstance(app.screen, ModalScreen)
    [item] = store.load().items
    assert (item.title, item.priority, item.type, item.status, item.created_by) == ("fix the login loop", 1, "fix", "todo", "user")


async def test_quick_add_defaults_to_current_tab_status(store):
    seed(store, ("existing", "todo", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("2", "a", *typed("in todo tab"), "enter")
        await settle(pilot)
        await pilot.press("3", "a", *typed("from doing tab"), "enter")  # not inbox/todo: ui.new_item_status
        await settle(pilot)
    by_title = {i.title: i for i in store.load().items}
    assert by_title["in todo tab"].status == "todo"
    assert by_title["from doing tab"].status == "inbox"


@pytest.mark.parametrize("save_key", ["alt+enter", "ctrl+j"])
async def test_quick_add_multi_keeps_input_open(store, save_key):
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("a", *typed("first !2"), save_key)
        await settle(pilot)
        assert isinstance(app.screen, ModalScreen)  # still open
        assert app.screen.query_one("Input").value == ""  # and cleared
        await pilot.press(*typed("second #idea"), save_key)
        await settle(pilot)
        await pilot.press("escape")
        await settle(pilot)
        assert not isinstance(app.screen, ModalScreen)
    items = store.load().items
    assert [(i.title, i.priority, i.type) for i in items] == [("first", 2, "feature"), ("second", 3, "idea")]


async def test_quick_add_keys_do_not_leak_to_the_list(store):
    seed(store, ("one", "inbox", 3), ("two", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("a", "j", "j", "d", "d", "space", "backspace", "q")
        await settle(pilot)
        assert isinstance(app.screen, ModalScreen)  # q did not quit
        assert app.screen.query_one("Input").value == "jjddq"  # typed literally; backspace deleted the space
        await pilot.press("escape")
        await settle(pilot)
        assert selected(app) == 1
    assert [i.status for i in store.load().items] == ["inbox", "inbox"]


async def test_quick_add_escape_cancels_and_empty_title_is_rejected(store):
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("a", "enter")  # empty: stays open
        await settle(pilot)
        assert isinstance(app.screen, ModalScreen)
        await pilot.press(*typed("never saved"), "escape")
        await settle(pilot)
    assert store.load().items == []


# ---- triage keys ---------------------------------------------------------------

async def test_space_advances_and_backspace_goes_back(store):
    [a] = seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("space")
        await settle(pilot)
        assert store.load().get(a).status == "todo"
        await pilot.press("2", "backspace")
        await settle(pilot)
        assert store.load().get(a).status == "inbox"


async def test_m_chord_moves_item(store):
    [a] = seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("m")
        await settle(pilot)
        assert app.message.startswith("move to:") and "r review" in app.message
        await pilot.press("r")
        await settle(pilot)
        assert store.load().get(a).status == "review"
        assert app.message.startswith("moved #1 to review")
        # all the chord targets
        await pilot.press("4")
        for key, status in (("i", "inbox"), ("t", "todo"), ("d", "doing"), ("x", "done")):
            await pilot.press("0")  # All tab keeps the item visible
            await pilot.press("m", key)
            await settle(pilot)
            assert store.load().get(a).status == status


async def test_chord_cancelled_by_escape_or_other_key(store):
    [a] = seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("m", "escape")
        await settle(pilot)
        assert store.load().get(a).status == "inbox" and app.message == "cancelled"
        await pilot.press("m", "z")
        await settle(pilot)
        assert store.load().get(a).status == "inbox"
        await pilot.press("space")  # chord state is gone: a normal key again
        await settle(pilot)
        assert store.load().get(a).status == "todo"


async def test_y_accepts_in_review_only(store):
    [a, b] = seed(store, ("in review", "review", 3), ("in todo", "todo", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("2", "y")
        await settle(pilot)
        assert "Review" in app.message and store.load().get(b).status == "todo"
        await pilot.press("4", "y")
        await settle(pilot)
        assert store.load().get(a).status == "done"


async def test_n_bounces_with_reason(store):
    [a] = seed(store, ("needs work", "review", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("4", "n")
        await settle(pilot)
        assert isinstance(app.screen, ModalScreen)
        await pilot.press(*typed("missing tests"), "enter")
        await settle(pilot)
    item = store.load().get(a)
    assert item.status == "todo"
    assert item.log[-1].text == "bounced: missing tests" and item.log[-1].by == "user"


async def test_n_outside_review_explains(store):
    seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        assert not isinstance(app.screen, ModalScreen)
        assert "Review" in app.message


async def test_p_chord_sets_priority_and_plus_minus(store):
    [a] = seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("p", "1")
        await settle(pilot)
        assert store.load().get(a).priority == 1
        await pilot.press("plus")
        await settle(pilot)
        assert store.load().get(a).priority == 1 and "urgent" in app.message
        await pilot.press("minus", "minus")
        await settle(pilot)
        assert store.load().get(a).priority == 3
        await pilot.press("equals_sign")
        await settle(pilot)
        assert store.load().get(a).priority == 2


async def test_type_cycles_both_ways(store):
    [a] = seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("t")
        await settle(pilot)
        assert store.load().get(a).type == "fix"  # after "feature"
        await pilot.press("T", "T")
        await settle(pilot)
        assert store.load().get(a).type == "idea"  # wraps backwards


async def test_J_reorders_and_selection_follows(store):
    a, b, c = seed(store, ("a", "todo", 3), ("b", "todo", 3), ("c", "todo", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("2")
        await settle(pilot)
        assert ids(app) == [a, b, c] and selected(app) == a
        await pilot.press("J")
        await settle(pilot)
        assert ids(app) == [b, a, c]
        assert selected(app) == a  # the selection stays on the moved item
        await pilot.press("K")
        await settle(pilot)
        assert ids(app) == [a, b, c] and selected(app) == a
        await pilot.press("K")
        await settle(pilot)
        assert "top" in app.message


async def test_dd_archives_and_u_undoes(store):
    [a] = seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("d", "d")
        await settle(pilot)
        assert store.load().get(a).status == "archived"
        assert "archived #1" in app.message and "u to undo" in app.message
        assert ids(app) == []
        await pilot.press("u")
        await settle(pilot)
        assert store.load().get(a).status == "inbox"
        assert app.message == "undid: set_status #1"
        assert ids(app) == [a]


async def test_single_d_does_nothing_and_times_out(store, monkeypatch):
    [a] = seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("d")
        await settle(pilot)
        assert store.load().get(a).status == "inbox"
        await pilot.pause(1.2)  # the chord expires
        await pilot.press("d")
        await settle(pilot)
        assert store.load().get(a).status == "inbox"  # that was a first d again, not a second
        await pilot.press("j", "d", "d")  # d + other key passes the other key through
        await settle(pilot)


async def test_archived_tab_restore_and_purge(store):
    a, b = seed(store, ("one", "inbox", 3), ("two", "inbox", 3))
    ops.archive(store, a, actor="user")
    ops.archive(store, b, actor="user")
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("9")
        await settle(pilot)
        assert ids(app) == [a, b]
        await pilot.press("space")  # restore to inbox
        await settle(pilot)
        assert store.load().get(a).status == "inbox"
        # purge asks first; n declines
        await pilot.press("D")
        await settle(pilot)
        assert isinstance(app.screen, ModalScreen)
        await pilot.press("n")
        await settle(pilot)
        assert store.load().get(b) is not None
        await pilot.press("d", "d", "y")
        await settle(pilot)
        assert store.load().get(b) is None
        await pilot.press("u")  # undo the purge
        await settle(pilot)
        assert store.load().get(b).status == "archived"


async def test_purge_without_confirmation_when_disabled(store):
    config.set_value("ui.confirm_delete", False)
    [a] = seed(store, ("one", "inbox", 3))
    ops.archive(store, a, actor="user")
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("9", "D")
        await settle(pilot)
        assert not isinstance(app.screen, ModalScreen)
        assert store.load().items == []


async def test_D_outside_archive_explains(store):
    [a] = seed(store, ("one", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("D")
        await settle(pilot)
        assert "Archived" in app.message and store.load().get(a) is not None


async def test_note_prompt_adds_note(store):
    [a] = seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("c", *typed("please use sqlite"), "enter")
        await settle(pilot)
    log = store.load().get(a).log[-1]
    assert (log.kind, log.by, log.text) == ("note", "user", "please use sqlite")


async def test_errors_show_in_message_area_and_never_crash(store):
    [a] = seed(store, ("task", "done", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("5", "space")  # done -> nothing further
        await settle(pilot)
        assert "already done" in app.message
        assert app.query_one("#message").has_class("-error")
        await pilot.press("j", "j", "k")  # still alive
        # an item removed behind our back
        ops.purge(store, a, actor="user")
        await pilot.press("space")
        await settle(pilot)


async def test_undo_with_nothing_to_undo(store):
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("u")
        assert app.message == "nothing to undo"


async def test_copy_handoff(store, monkeypatch):
    [a] = seed(store, ("task", "inbox", 3))
    calls = []
    monkeypatch.setattr("triage.tui.app.copy_to_system_clipboard", lambda text: calls.append(text))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("Y")
        await settle(pilot)
        assert calls == [f"triage show {a}"]
        assert f"triage show {a}" in app.message


# ---- navigation, tabs, filter -----------------------------------------------------

async def test_tab_switching_with_l_h_arrows_and_numbers(store):
    seed(store, ("i", "inbox", 3), ("t", "todo", 3), ("d", "doing", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert app.tab == "inbox"
        await pilot.press("l")
        assert app.tab == "todo"
        await pilot.press("3")
        assert app.tab == "doing"
        await settle(pilot)
        assert [app.board.get(i).title for i in ids(app)] == ["d"]
        await pilot.press("h", "h")
        assert app.tab == "inbox"
        await pilot.press("l")
        assert app.tab == "todo"
        await pilot.press("h", "h")
        assert app.tab == "archived"  # wraps; archived is the 7th tab
        await pilot.press("right", "right")  # archived -> inbox -> todo
        assert app.tab == "todo"
        await pilot.press("l", "l", "l", "l")  # doing, review, done, all
        assert app.tab == "all"
        await pilot.press("l")
        assert app.tab == "archived"
        await pilot.press("0")
        await settle(pilot)
        assert app.tab == "all" and len(ids(app)) == 3
        await pilot.press("9")
        assert app.tab == "archived"


async def test_tab_bar_shows_counts_and_review_attention(store):
    seed(store, ("i", "inbox", 3), ("r", "review", 3), ("r2", "review", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        text = app.query_one("#tabs").render().plain if hasattr(app.query_one("#tabs").render(), "plain") else str(app.query_one("#tabs").render())
        assert "1 Inbox 1" in text and "4 Review 2" in text and "0 All 3" in text
        from triage.tui.widgets import palette, render_tabs

        pal = palette(app)
        review = render_tabs(app.board.counts(), "inbox", 120, pal)
        styles = {review.plain[s.start:s.end]: str(s.style) for s in review.spans}
        assert pal["warning"] in styles["Review"]  # attention colour while the review column is non-empty
        empty = render_tabs({}, "inbox", 120, pal)
        assert pal["warning"] not in " ".join(str(s.style) for s in empty.spans)


async def test_list_navigation_keys(store):
    got = seed(store, *[(f"item {n}", "inbox", 3) for n in range(1, 31)])
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert selected(app) == got[0]
        await pilot.press("j", "j", "down")
        assert selected(app) == got[3]
        await pilot.press("k", "up")
        assert selected(app) == got[1]
        await pilot.press("G")
        assert selected(app) == got[-1]
        await pilot.press("g")
        assert selected(app) == got[0]
        await pilot.press("end")
        assert selected(app) == got[-1]
        await pilot.press("home")
        assert selected(app) == got[0]
        await pilot.press("ctrl+d")
        half = selected(app) - got[0]
        assert half > 5
        await pilot.press("ctrl+u")
        assert selected(app) == got[0]


async def test_filter_narrows_list_live(store):
    a, b, c = seed(store, ("Fix the parser", "inbox", 3), ("Add dark mode", "inbox", 3), ("Docs", "inbox", 3))
    ops.update(store, c, actor="user", body="mentions the PARSER too")
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert ids(app) == [a, b, c]
        await pilot.press("slash")
        await settle(pilot)
        await pilot.press(*typed("parser"))
        await settle(pilot)
        assert ids(app) == [a, c]  # title and body, case-insensitive
        assert app.focused is app.filter_input
        await pilot.press("enter")  # keep the filter, back to the list
        await settle(pilot)
        assert app.focused is app.items_view and ids(app) == [a, c]
        await pilot.press("j")
        assert selected(app) == c
        await pilot.press("escape")  # clears
        await settle(pilot)
        assert ids(app) == [a, b, c] and app.filter_text == ""


async def test_filter_escape_while_typing_clears(store):
    a, b = seed(store, ("alpha", "inbox", 3), ("beta", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("slash", *typed("alp"))
        await settle(pilot)
        assert ids(app) == [a]
        await pilot.press("escape")
        await settle(pilot)
        assert ids(app) == [a, b] and app.focused is app.items_view


async def test_enter_focuses_detail_and_escape_returns(store):
    [a] = seed(store, ("task", "inbox", 3))
    ops.update(store, a, actor="user", body="\n\n".join(f"line {n}" for n in range(80)))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot)
        assert app.focused is app.detail
        y0 = app.detail.scroll_y
        await pilot.press("j", "j", "j")
        await settle(pilot)
        assert app.detail.scroll_y > y0
        await pilot.press("G")
        await settle(pilot)
        assert app.detail.scroll_y == app.detail.max_scroll_y
        await pilot.press("escape")
        await settle(pilot)
        assert app.focused is app.items_view


async def test_detail_pane_shows_markdown_and_distinguishes_agent_log(store):
    [a] = seed(store, ("task", "todo", 2))
    ops.update(store, a, actor="user", body="## Heading\n\nsome **bold** text")
    ops.claim(store, a, actor="agent")
    ops.note(store, a, "agent note here", actor="agent")
    ops.note(store, a, "user reply", actor="user")
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("3")
        await settle(pilot)
        from triage.tui.widgets import render_detail, palette
        from rich.console import Console
        con = Console(file=io.StringIO(), width=80, record=True, force_terminal=True, color_system="truecolor")
        con.print(render_detail(app.current_item(), palette(app)))
        out = con.export_text()
        assert "Heading" in out and "agent note here" in out and "user reply" in out
        assert "taken by agent" in out and "⚑" not in out
        styled = con.export_text(styles=True)
        assert styled != out  # agent entries carry colour


# ---- live updates -------------------------------------------------------------------

async def test_outside_change_appears_after_poll_and_flashes(store):
    config.set_value("ui.poll_seconds", 0.1)
    seed(store, ("mine", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert len(ids(app)) == 1
        new = ops.add(store, "from the agent", actor="agent").item.id  # an outside write
        await pilot.pause(0.6)
        assert new in ids(app)
        assert app.message.startswith(f"agent updated #{new}")
        assert new in app._flash  # flashing


async def test_user_reorder_does_not_flag_agent_items(store):
    a, b, c = seed(store, ("a", "todo", 3), ("b", "todo", 3), ("c", "todo", 3))
    ops.note(store, b, "hello", actor="agent")  # b was last touched by the agent
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("2", "J")  # rewrites every rank in the column, including b's
        await settle(pilot)
        assert ids(app) == [b, a, c]
        assert not app._flash and not app.message.startswith("agent updated")


async def test_outside_change_keeps_selection_by_id(store):
    config.set_value("ui.poll_seconds", 0.1)
    a, b, c = seed(store, ("a", "inbox", 1), ("b", "inbox", 2), ("c", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("j", "j")
        assert selected(app) == c
        # new urgent item sorts above everything: the selection must stay on c
        d = ops.add(store, "urgent", actor="agent", priority=1).item.id
        await pilot.pause(0.6)
        assert ids(app)[0] in (a, d) and d in ids(app)
        assert selected(app) == c


async def test_outside_change_keeps_scroll_position(store):
    config.set_value("ui.poll_seconds", 0.1)
    got = seed(store, *[(f"item {n}", "inbox", 3) for n in range(1, 61)])
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("G")
        await settle(pilot, 4)
        before = app.items_view.scroll_y
        assert before > 0 and selected(app) == got[-1]
        ops.note(store, got[0], "poke", actor="agent")  # changes the file, not the visible order
        ops.add(store, "another", actor="agent", priority=4)  # lands at the very bottom
        await pilot.pause(0.6)
        await settle(pilot, 4)
        assert selected(app) == got[-1]
        assert app.items_view.scroll_y >= before - 1  # the viewport did not jump back to the top


async def test_outside_change_to_selected_item_updates_detail(store):
    config.set_value("ui.poll_seconds", 0.1)
    [a] = seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        ops.note(store, a, "outside note", actor="agent")
        await pilot.pause(0.6)
        assert "outside note" in app.detail._shown[0]  # the pane re-rendered the selected item


async def test_poll_does_not_reload_when_nothing_changed(store, monkeypatch):
    config.set_value("ui.poll_seconds", 0.1)
    seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        loads = []
        orig = store.load
        monkeypatch.setattr(store, "load", lambda: (loads.append(1), orig())[1])
        await pilot.pause(0.5)
        assert loads == []


# ---- forms ---------------------------------------------------------------------------

async def test_add_form_creates_item(store):
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("A")
        await settle(pilot)
        await pilot.press(*typed("Big feature"))
        await pilot.press("tab")  # type select
        await pilot.press("tab")  # priority select
        await pilot.press("tab")  # taken by select
        await pilot.press("tab")  # body
        await settle(pilot)
        await pilot.press(*typed("body text"))
        await pilot.press("ctrl+s")
        await settle(pilot)
        assert not isinstance(app.screen, ModalScreen)
    [it] = store.load().items
    assert (it.title, it.body, it.type, it.priority) == ("Big feature", "body text", "feature", 3)


async def test_add_form_rejects_empty_title_and_escape_cancels(store):
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("A", "ctrl+s")
        await settle(pilot)
        assert isinstance(app.screen, ModalScreen)  # still open
        await pilot.press("escape")
        await settle(pilot)
        assert not isinstance(app.screen, ModalScreen)
    assert store.load().items == []


async def test_edit_form_prefilled_and_saves(store):
    [a] = seed(store, ("old title", "todo", 2))
    ops.update(store, a, actor="user", body="old body", type="chore")
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("2", "e")
        await settle(pilot)
        form = app.screen
        assert form.query_one("#f-title").value == "old title"
        assert form.query_one("#f-type").value == "chore"
        assert form.query_one("#f-priority").value == 2
        assert form.query_one("#f-body").text == "old body"
        await pilot.press("end", *typed(" v2"), "ctrl+s")
        await settle(pilot)
    it = store.load().get(a)
    assert it.title == "old title v2" and it.body == "old body" and it.status == "todo"


def test_external_editor_round_trip(tmp_path, monkeypatch):
    script = tmp_path / "ed.py"
    script.write_text("import sys\nopen(sys.argv[1], 'a', encoding='utf-8').write('appended\\n')\n")
    monkeypatch.setenv("EDITOR", f'"{sys.executable}" "{script}"')
    monkeypatch.delenv("VISUAL", raising=False)
    assert edit_text_externally("start\n", name="triage-test") == "start\nappended\n"
    # the temp file never lives in the repo and is cleaned up
    assert not [p for p in os.listdir(os.path.dirname(os.path.abspath(str(script)))) if p.startswith("triage-test")]


def test_resolve_editor_prefers_visual(monkeypatch):
    monkeypatch.setenv("VISUAL", "code --wait")
    monkeypatch.setenv("EDITOR", "nano")
    assert resolve_editor() == ["code", "--wait"]
    monkeypatch.delenv("VISUAL")
    assert resolve_editor() == ["nano"]
    monkeypatch.delenv("EDITOR")
    assert resolve_editor() == (["notepad"] if sys.platform == "win32" else ["vi"])


async def test_E_updates_body_via_editor(store, monkeypatch):
    [a] = seed(store, ("task", "inbox", 3))
    monkeypatch.setattr("triage.tui.app.edit_text_externally", lambda text, name="x": text + "edited externally")
    app = TriageApp(store)
    from contextlib import contextmanager

    @contextmanager
    def fake_suspend():
        yield

    monkeypatch.setattr(app, "suspend", fake_suspend)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("E")
        await settle(pilot)
    assert store.load().get(a).body == "edited externally"


# ---- settings, help, repo picker --------------------------------------------------------

async def test_settings_toggle_writes_config(store):
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("comma")
        await settle(pilot)
        assert isinstance(app.screen, SettingsScreen)
        # row 0 is agent.finish_status (review/done): enter cycles the choice
        await pilot.press("enter")
        await settle(pilot)
        assert config.overrides(None)["agent.finish_status"] == "done"
        assert ops.config_for(store)["agent.finish_status"] == "done"
        # a bool row (agent.can_create is row 3): space toggles
        await pilot.press("j", "j", "j", "space")
        await settle(pilot)
        assert config.overrides(None)["agent.can_create"] is False
        await pilot.press("escape")
        await settle(pilot)
        assert not isinstance(app.screen, ModalScreen)
        assert app.cfg["agent.can_create"] is False  # the app re-read the config


async def test_settings_board_scope_inline_input_and_remove(store):
    app = TriageApp(store)
    bid = store.ref.board_id
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("comma", "b")
        await settle(pilot)
        assert app.screen.scope == "board"
        await pilot.press("enter")
        await settle(pilot)
        assert config.overrides(bid) == {"agent.finish_status": "done"}
        assert config.overrides(None) == {}
        # poll_seconds is row 9: free entry through the inline input
        await pilot.press(*["j"] * 9, "enter")
        await settle(pilot)
        await pilot.press(*typed("2.5"), "enter")
        await settle(pilot)
        assert config.overrides(bid)["ui.poll_seconds"] == 2.5
        assert app.cfg["ui.poll_seconds"] == 2.5
        # a bad value is rejected inline
        await pilot.press("enter")
        await pilot.press(*typed("abc"), "enter")
        await settle(pilot)
        assert config.overrides(bid)["ui.poll_seconds"] == 2.5
        await pilot.press("escape")  # closes the input only
        await settle(pilot)
        assert isinstance(app.screen, SettingsScreen)
        await pilot.press("x")  # remove the board override of poll_seconds
        await settle(pilot)
        assert "ui.poll_seconds" not in config.overrides(bid)
        await pilot.press("escape")


async def test_help_screen_lists_every_binding_group(store):
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("question_mark")
        await settle(pilot)
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await settle(pilot)
        assert not isinstance(app.screen, ModalScreen)
    sections = dict(keys.help_sections())
    assert list(sections) == ["Navigate", "Capture", "Triage", "App"]
    flat = " ".join(f"{k} {t}" for rows in sections.values() for k, t in rows).lower()
    for needle in ("quick add", "full add form", "undo", "settings", "repo picker", "accept", "bounce",
                   "m …", "p …", "d d", "inbox", "doing", "ctrl+d"):
        assert needle in flat, needle


async def test_repo_picker_opens_another_board_and_resets_undo(store, tmp_path):
    other_path = tmp_path / "other-repo"
    other_path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=other_path, check=True)
    other = BoardStore(resolve_repo(other_path))
    ops.add(other, "other board item", actor="user")
    seed(store, ("here", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("p", "1")  # leaves something on the undo stack
        await settle(pilot)
        assert app.undo_stack
        await pilot.press("R")
        await settle(pilot)
        assert isinstance(app.screen, RepoPickerScreen)
        # type a path that exists: registers + opens it
        await pilot.press(*typed(str(other_path)))
        await pilot.press("enter")
        await settle(pilot)
        assert app.store.ref.name == "other-repo"
        assert app.undo_stack == []
        assert [app.board.get(i).title for i in ids(app)] == ["other board item"]
        # now it is in the registry, and the fuzzy list finds the first board again
        await pilot.press("R")
        await settle(pilot)
        await pilot.press(*typed("scr"))
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot)
        assert app.store.ref.name == "scratch-repo"


async def test_repo_picker_rejects_non_repo_path(store, tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("R", *typed(str(plain)), "enter")
        await settle(pilot)
        assert isinstance(app.screen, RepoPickerScreen)  # stays open with an error
        await pilot.press("escape")
        await settle(pilot)
        assert app.store.ref.name == "scratch-repo"


async def test_no_repo_opens_the_picker(tmp_path):
    app = TriageApp(None)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert isinstance(app.screen, RepoPickerScreen)
        await pilot.press("escape")
        await settle(pilot)
        await pilot.press("space", "a")  # no board: friendly message, no crash
        await settle(pilot)
        assert "no board" in app.message


async def test_opening_a_board_records_it_in_the_registry(store):
    from triage.store import list_boards

    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
    [row] = [b for b in list_boards() if b["board_id"] == store.ref.board_id]
    assert row.get("opened_at")


async def test_small_terminal_does_not_crash(store):
    seed(store, ("a fairly long title that will certainly be truncated in a narrow list", "todo", 1))
    app = TriageApp(store)
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(pilot)
        await pilot.press("2", "a")
        await settle(pilot)
        await pilot.press("escape", "question_mark")
        await settle(pilot)
        await pilot.press("escape", "comma")
        await settle(pilot)
        await pilot.press("escape")


def test_run_falls_back_to_picker_outside_a_repo(tmp_path, monkeypatch):
    """``run`` resolves the repo and survives RepoNotFound."""
    from triage.tui import app as app_mod

    seen = {}

    class Fake:
        def __init__(self, store):
            seen["store"] = store

        def run(self):
            seen["ran"] = True

    monkeypatch.setattr(app_mod, "TriageApp", Fake)
    app_mod.run(str(tmp_path))  # tmp_path is not inside a git repo
    assert seen == {"store": None, "ran": True}


def test_run_resolves_given_repo(repo, monkeypatch):
    from triage.tui import app as app_mod

    seen = {}

    class Fake:
        def __init__(self, store):
            seen["store"] = store

        def run(self):
            pass

    monkeypatch.setattr(app_mod, "TriageApp", Fake)
    app_mod.run(str(repo))
    assert seen["store"].ref.name == "scratch-repo"


def test_editor_not_found_raises_cleanly(monkeypatch):
    from triage.tui import app as tui_app

    monkeypatch.setenv("VISUAL", "definitely-not-an-editor-xyz")
    with pytest.raises(FileNotFoundError):
        tui_app.edit_text_externally("hello", name="triage-test")


def test_driver_never_requests_kitty_keyboard_when_disabled():
    """Issue #3: under ConPTY the kitty request made Esc/Alt keys unusable."""
    from triage.tui import app as tui_app

    class FakeDriver:
        def __init__(self):
            self.out = []

        def write(self, data):
            self.out.append(data)

    driver = tui_app.without_kitty_keyboard(FakeDriver)()
    driver.write(tui_app.KITTY_KEYS_ON)
    driver.write("\x1b[?1049h" + tui_app.KITTY_KEYS_ON + "\x1b[?2004h")
    driver.write(tui_app.KITTY_KEYS_OFF)
    assert driver.out == ["\x1b[?1049h\x1b[?2004h"]


@pytest.mark.parametrize(
    "platform, flag, wanted",
    [("win32", "", False), ("linux", "", True), ("win32", "1", True), ("linux", "off", False)],
)
def test_kitty_keyboard_platform_default(monkeypatch, platform, flag, wanted):
    from triage.tui import app as tui_app

    monkeypatch.setattr(tui_app.sys, "platform", platform)
    monkeypatch.setenv("TRIAGE_KITTY_KEYS", flag)
    assert tui_app.kitty_keyboard_wanted() is wanted
    driver_class = TriageApp().get_driver_class()
    assert driver_class.__name__.startswith("NoKitty") is (not wanted)


# ---- tab toggles list <-> detail --------------------------------------------------------

async def test_tab_toggles_between_list_and_detail(store):
    seed(store, ("a", "inbox", 3), ("b", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert app.focused is app.items_view
        await pilot.press("tab")
        assert app.focused is app.detail
        await pilot.press("tab")
        assert app.focused is app.items_view
        await pilot.press("shift+tab")  # not a toggle any more (triage #7 feedback)
        assert app.focused is app.items_view
        assert app.tab == "inbox"  # tab no longer switches status tabs
        await pilot.press("tab", "escape")  # enter/esc still work alongside
        assert app.focused is app.items_view
        await pilot.press("enter")
        assert app.focused is app.detail


async def test_tab_with_no_item_stays_on_the_list(store):
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("tab")
        assert app.focused is app.items_view and app.tab == "inbox"


async def test_tab_in_the_filter_box_returns_to_the_list_and_keeps_the_filter(store):
    seed(store, ("apple", "inbox", 3), ("pear", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("slash", *typed("app"), "tab")
        await settle(pilot)
        assert app.focused is app.items_view and app.filter_text == "app" and len(ids(app)) == 1


async def test_tab_inside_a_modal_is_not_hijacked(store):
    [a] = seed(store, ("a", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("c", "tab")
        await settle(pilot)
        assert isinstance(app.screen, ModalScreen)
        assert app._main_screen.focused is not app.detail and app.tab == "inbox"
        await pilot.press("escape")


async def test_item_actions_work_while_the_detail_pane_has_focus(store):
    [a] = seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("0", "tab")  # All tab: the item stays visible whatever happens to it
        await settle(pilot)
        assert app.focused is app.detail

        def item():
            return store.load().get(a)

        await pilot.press("space")
        await settle(pilot)
        assert item().status == "todo" and app.focused is app.detail
        await pilot.press("m", "d")
        await settle(pilot)
        assert item().status == "doing"
        await pilot.press("p", "1")
        await settle(pilot)
        assert item().priority == 1
        await pilot.press("plus", "minus")  # already urgent: + does nothing; - lowers it to P2
        await settle(pilot)
        assert item().priority == 2
        await pilot.press("t")
        await settle(pilot)
        assert item().type == "fix"
        await pilot.press("u")
        await settle(pilot)
        assert item().type == "feature"
        await pilot.press("backspace")
        await settle(pilot)
        assert item().status == "todo"
        await pilot.press("d", "d")
        await settle(pilot)
        assert item().status == "archived" and app.focused is app.detail
        await pilot.press("u")
        await settle(pilot)
        assert item().status == "todo" and app.focused is app.detail


async def test_review_keys_work_from_the_detail_pane(store):
    a, b = seed(store, ("accept me", "review", 3), ("bounce me", "review", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("4", "tab", "y")
        await settle(pilot)
        assert store.load().get(a).status == "done" and app.focused is app.detail
        await pilot.press("n", *typed("needs tests"), "enter")
        await settle(pilot)
        item = store.load().get(b)
        assert item.status == "todo" and any("needs tests" in e.text for e in item.log)
        assert app.focused is app.detail


async def test_edit_and_note_open_from_the_detail_pane(store):
    [a] = seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("tab", "e")
        await settle(pilot)
        assert app.screen.query_one("#f-title").value == "task"
        await pilot.press("escape")
        await settle(pilot)
        await pilot.press("c", *typed("from detail"), "enter")
        await settle(pilot)
        assert store.load().get(a).log[-1].text == "from detail"


# ---- the key-hint bar -----------------------------------------------------------------------

def hints(app) -> list[tuple[str, str]]:
    return app.query_one(KeyHints).shown


async def test_hint_bar_replaces_the_footer(store):
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert len(app.query(Footer)) == 0 and len(app.query(KeyHints)) == 1


async def test_hint_bar_for_an_empty_list(store):
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert hints(app) == [("a", "add"), ("A", "add form"), ("h/l", "tabs"), ("/", "find"), ("?", "help"), ("q", "quit")]


async def test_hint_bar_with_an_item_selected_shows_edit_and_the_space_destination(store):
    seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        shown = hints(app)
        assert shown == [("e", "edit"), ("c", "note"), ("space", "→ todo"), ("m", "move"), ("p", "priority"),
                         ("tab", "detail"), ("dd", "archive"), ("?", "help")]  # no undo yet
        await pilot.press("l")  # Todo tab is empty
        await settle(pilot)
        assert hints(app)[0][1] == "add"
        await pilot.press("h", "m", "t")
        await settle(pilot)
        await pilot.press("l")
        await settle(pilot)
        assert ("space", "→ doing") in hints(app) and ("u", "undo") in hints(app)
        await pilot.press("u")
        await settle(pilot)
        assert ("u", "undo") not in hints(app)


async def test_hint_bar_for_a_review_item_leads_with_accept_and_bounce(store):
    seed(store, ("waiting", "review", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("4")
        await settle(pilot)
        assert hints(app)[:3] == [("y", "accept"), ("n", "bounce"), ("e", "edit")]
        assert ("space", "→ done") in hints(app)


async def test_hint_bar_in_the_archived_tab(store):
    [a] = seed(store, ("old", "todo", 3))
    ops.archive(store, a, actor="user")
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("9")
        await settle(pilot)
        shown = hints(app)
        assert shown[:2] == [("space", "restore"), ("D", "delete")]
        assert ("j/k", "move") in shown and ("h/l", "tabs") in shown and ("?", "help") in shown
        assert ("e", "edit") not in shown and ("dd", "archive") not in shown


async def test_hint_bar_with_the_detail_pane_focused(store):
    seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("tab")
        await settle(pilot)
        assert hints(app) == [("j/k", "scroll"), ("tab/esc", "back to list"), ("e", "edit"), ("c", "note"), ("?", "help")]
        await pilot.press("escape")
        await settle(pilot)
        assert ("e", "edit") in hints(app) and ("j/k", "scroll") not in hints(app)


async def test_hint_bar_with_a_filter(store):
    seed(store, ("apple", "inbox", 3), ("pear", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("slash", "a")
        await settle(pilot)
        assert hints(app) == [("enter", "keep"), ("esc", "clear filter")]  # typing: ? and q are just letters here
        await pilot.press("enter")
        await settle(pilot)
        assert hints(app)[0] == ("esc", "clear filter") and ("e", "edit") in hints(app)
        await pilot.press("escape")
        await settle(pilot)
        assert ("esc", "clear filter") not in hints(app)


async def test_hint_bar_follows_the_selection(store):
    seed(store, ("in review", "review", 3), ("in inbox", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("0")
        await settle(pilot)
        first = hints(app)
        assert first[0] == ("y", "accept") or first[0] == ("e", "edit")
        await pilot.press("j")
        await settle(pilot)
        second = hints(app)
        assert first != second
        assert {first[0], second[0]} == {("y", "accept"), ("e", "edit")}


@pytest.mark.parametrize("size", [(80, 24), (60, 20), (40, 20)])
async def test_hint_bar_fits_the_terminal_and_keeps_help(store, size):
    [a] = seed(store, ("task", "review", 2))
    app = TriageApp(store)
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        await pilot.press("4", "plus")
        await settle(pilot)
        bar = app.query_one(KeyHints)
        assert ("?", "help") in bar.shown
        assert bar.text.cell_len <= size[0] - 2
        assert bar.shown[0] == ("y", "accept")


async def test_hint_bar_follows_remapped_keys(store, triage_home):
    seed(store, ("task", "inbox", 3))
    write_keys(triage_home, 'edit = "x"\nhelp = "F1"\narchive = "z"\n')
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        shown = dict(hints(app))
        assert shown["x"] == "edit" and shown["f1"] == "help" and shown["zz"] == "archive"
        assert "e" not in shown and "?" not in shown


# ---- configurable keys in the running app -------------------------------------------------------

def write_keys(triage_home, body: str) -> None:
    triage_home.mkdir(parents=True, exist_ok=True)
    (triage_home / "config.toml").write_text("[keys]\n" + body, encoding="utf-8")


async def test_remapped_quit_key_works_and_the_old_one_does_not(store, triage_home, monkeypatch):
    write_keys(triage_home, 'quit = "x"\n')
    calls = []
    monkeypatch.setattr(TriageApp, "action_quit", lambda self: calls.append("quit"))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("q")
        await settle(pilot)
        assert calls == []
        await pilot.press("x")
        await settle(pilot)
        assert calls == ["quit"]


async def test_remapped_chord_prefixes_and_item_keys(store, triage_home):
    [a, b] = seed(store, ("one", "inbox", 3), ("two", "inbox", 3))
    write_keys(triage_home, 'move = "M"\narchive = "z"\nnote = "N"\n')
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("m")  # the old prefix is gone
        assert app._chord is None
        await pilot.press("M")
        assert app._chord is not None and "move to" in app.message
        await pilot.press("t")
        await settle(pilot)
        assert store.load().get(a).status == "todo"
        await pilot.press("z", "z")  # archive is now z z
        await settle(pilot)
        assert store.load().get(b).status == "archived"
        await pilot.press("d", "d")  # the old archive prefix does nothing
        await settle(pilot)
        assert store.load().get(a).status == "todo"


async def test_remapped_note_key_opens_the_note_prompt(store, triage_home):
    seed(store, ("one", "inbox", 3))
    write_keys(triage_home, 'note = "N"\n')
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("c")
        await settle(pilot)
        assert not isinstance(app.screen, ModalScreen)
        await pilot.press("N")
        await settle(pilot)
        assert isinstance(app.screen, ModalScreen)
        await pilot.press("escape")


async def test_remapped_toggle_key_and_printable_keys_do_not_steal_filter_typing(store, triage_home):
    seed(store, ("zebra", "inbox", 3), ("apple", "inbox", 3))
    write_keys(triage_home, 'toggle_detail = "tab, z"\n')
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("z")
        assert app.focused is app.detail
        await pilot.press("z")
        assert app.focused is app.items_view
        await pilot.press("slash", "z")  # typing z in the filter box must type, not toggle
        await settle(pilot)
        assert app.filter_input.value == "z" and app.focused is app.filter_input


async def test_remapped_help_key_opens_and_closes_help(store, triage_home):
    write_keys(triage_home, 'help = "F1"\n')
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("question_mark")
        await settle(pilot)
        assert not isinstance(app.screen, HelpScreen)
        await pilot.press("f1")
        await settle(pilot)
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("f1")
        await settle(pilot)
        assert not isinstance(app.screen, ModalScreen)


async def test_bad_keys_config_shows_one_warning_and_falls_back(store, triage_home):
    seed(store, ("task", "inbox", 3))
    write_keys(triage_home, 'quit = ""\nedit = "blorp"\nghost = "x"\nnote = "e"\n')
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        shown = app._q("#message").content.plain
        assert shown == app.message
        assert shown == ("keys: 4 problems in config.toml — default used for quit, edit, note; "
                         "ignored unknown ghost (see triage config keys)")
        assert app._q("#message").has_class("-error")
        await pilot.press("e")  # the default still works
        await settle(pilot)
        assert app.screen.query_one("#f-title").value == "task"
        await pilot.press("escape")


async def test_unreadable_config_does_not_crash_the_tui(store, triage_home):
    triage_home.mkdir(parents=True, exist_ok=True)
    (triage_home / "config.toml").write_text("[keys\nnot toml", encoding="utf-8")
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert app.message.startswith("keys:") and "not valid TOML" in app.message
        await pilot.press("a")
        await settle(pilot)
        assert isinstance(app.screen, ModalScreen)


async def test_good_config_shows_no_warning(store):
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert app.keymap.problems == [] and not app.message.startswith("keys:")


def help_text(app) -> str:
    from rich.console import Console

    out = io.StringIO()
    Console(file=out, width=100, force_terminal=False).print(app.screen.query_one("#help-body").content)
    return out.getvalue()


async def test_help_leads_with_the_keys_for_what_you_are_looking_at(store):
    seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("question_mark")
        await settle(pilot)
        text = help_text(app)
        assert text.lstrip().startswith("Keys for what you're looking at")
        top = text[: text.index("NAVIGATE")]
        assert "e edit" in top and "space → todo" in top and "tab detail" in top
        for group in ("NAVIGATE", "CAPTURE", "TRIAGE", "APP"):
            assert group in text
        await pilot.press("escape")


async def test_help_shows_the_effective_configured_keys(store, triage_home):
    write_keys(triage_home, 'quit = "x"\nedit = "w"\nmove = "M"\n')
    seed(store, ("task", "inbox", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("question_mark")
        await settle(pilot)
        text = help_text(app)
        assert "w edit" in text.split("NAVIGATE")[0]  # the context line
        rows = {line.split("  ", 1)[0].strip(): line for line in text.splitlines() if line.strip()}
        assert "x" in rows and "M …" in rows and "m …" not in rows
        assert "Quit" in rows["x"] and "Edit the selected item" in rows["w"]
        await pilot.press("escape")


async def test_help_screen_does_not_lose_its_close_keys_when_quit_is_remapped(store, triage_home):
    write_keys(triage_home, 'quit = "x"\n')
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("question_mark", "x")  # the configured quit key closes help, like q used to
        await settle(pilot)
        assert not isinstance(app.screen, ModalScreen)


def test_bindings_and_help_come_from_the_command_table():
    app = TriageApp(None, keys.default_keymap())
    bound = {(k, b.action) for k, bs in app._bindings.key_to_bindings.items() for b in bs}
    for c in keys.COMMANDS:
        for action in c.actions:
            assert hasattr(TriageApp, "action_" + action.split("(")[0]), action
            for k in c.keys:
                assert (k, action) in bound, (c.name, k, action)
    assert ("ctrl+q", "quit") in bound  # Textual's own defaults are still there
    shown = {key for _, rows in keys.help_sections() for key, _ in rows}
    assert {"tab", "1-5", "d d", "m …", "p …", "space", "?", "q"} <= shown


def _stamp_created(store, ids_by_day):
    with store.transaction() as board:
        for item_id, day in ids_by_day.items():
            it = board.get(item_id)
            it.created_at = it.updated_at = f"2026-01-0{day}T00:00:00Z"


async def test_o_cycles_sort_and_J_needs_priority_sort(store):
    a, b, c = seed(store, ("b item", "todo", 3), ("c item", "todo", 3), ("a item", "todo", 3))
    _stamp_created(store, {a: 1, b: 3, c: 2})
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("2")
        await settle(pilot)
        assert ids(app) == [a, b, c]
        await pilot.press("o")  # last activity
        await settle(pilot)
        assert ids(app) == [b, c, a] and "by last activity" in app._q("#left").border_title
        ranks = [i.rank for i in store.load().items]
        await pilot.press("J")  # manual order is refused outside the priority sort
        await settle(pilot)
        assert [i.rank for i in store.load().items] == ranks and ids(app) == [b, c, a]
        await pilot.press("o", "o")  # newest, oldest
        await settle(pilot)
        assert ids(app) == [a, c, b]
        await pilot.press("o")  # item number
        await settle(pilot)
        assert ids(app) == [a, b, c] and "by item number" in app._q("#left").border_title
        await pilot.press("O", "O", "O", "O")  # back to priority
        await settle(pilot)
        assert ids(app) == [a, b, c] and "by" not in app._q("#left").border_title


async def test_ui_sort_setting_is_the_initial_order(store):
    a, b = seed(store, ("first", "todo", 3), ("second", "todo", 3))
    _stamp_created(store, {a: 1, b: 2})
    config.set_value("ui.sort", "created")
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("2")
        await settle(pilot)
        assert ids(app) == [b, a] and app.sort == "created"


# ---- taken-by tag -------------------------------------------------------------------

async def test_rows_show_the_tag_text_without_a_flag(store):
    from triage.tui.widgets import render_row, palette
    a, b, c = seed(store, ("plain", "todo", 3), ("taken", "todo", 3), ("reserved", "todo", 3))
    ops.claim(store, b, actor="agent")
    ops.note(store, a, "touched", actor="agent")  # last updated by the agent: no badge any more
    ops.update(store, c, taken_by="user")
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("2")
        await settle(pilot)
        board = store.load()
        rows = {i: render_row(board.get(i), 60, palette(app), False) for i in (a, b, c)}
        assert rows[a].plain.rstrip().endswith("plain")
        assert rows[b].plain.rstrip().endswith("agent")
        assert rows[c].plain.rstrip().endswith("user")
        assert all("⚑" not in r.plain for r in rows.values())
        styles = {i: {str(s.style) for s in r.spans} for i, r in rows.items()}
        assert styles[b] != styles[c]  # the user's tag has its own colour


async def test_edit_form_switches_taken_by_and_logs_it(store):
    [a] = seed(store, ("thing", "todo", 3))
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("2", "e")
        await settle(pilot)
        field = app.screen.query_one("#f-taken")
        assert field.value == "none"
        field.focus()
        await pilot.press("u", "ctrl+s")  # jump to user
        await settle(pilot)
        assert store.load().get(a).claimed_by == "user"
        assert store.load().get(a).log[-1].text == "taken by: none -> user"
        await pilot.press("e")
        await settle(pilot)
        field = app.screen.query_one("#f-taken")
        assert field.value == "user"
        field.focus()
        await pilot.press("a", "ctrl+s")
        await settle(pilot)
        it = store.load().get(a)
        assert (it.claimed_by, it.status) == ("agent", "todo")
        assert it.log[-1].text == "taken by: user -> agent"
        await pilot.press("e")
        await settle(pilot)
        field = app.screen.query_one("#f-taken")
        field.focus()
        await pilot.press("n", "ctrl+s")
        await settle(pilot)
        assert store.load().get(a).claimed_by is None
        await pilot.press("u")  # undo the last form save
        await settle(pilot)
        assert store.load().get(a).claimed_by == "agent"


async def test_edit_form_keeps_a_custom_agent_name_and_drops_tag_without_moving_status(store):
    [a] = seed(store, ("thing", "todo", 3))
    ops.claim(store, a, actor="agent", who="worker-7")
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("3", "e")
        await settle(pilot)
        field = app.screen.query_one("#f-taken")
        assert field.value == "worker-7" and field.label == "worker-7"
        await pilot.press("end", *typed("!"), "ctrl+s")  # save without touching the field
        await settle(pilot)
        it = store.load().get(a)
        assert it.claimed_by == "worker-7" and it.title == "thing!"
        await pilot.press("e")
        await settle(pilot)
        field = app.screen.query_one("#f-taken")
        field.focus()
        await pilot.press("n", "ctrl+s")
        await settle(pilot)
    it = store.load().get(a)
    assert (it.claimed_by, it.status) == (None, "doing")


async def test_add_form_can_reserve_the_item(store):
    app = TriageApp(store)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("A")
        await settle(pilot)
        await pilot.press(*typed("Mine"))
        app.screen.query_one("#f-taken").focus()
        await pilot.press("u", "ctrl+s")
        await settle(pilot)
    [it] = store.load().items
    assert (it.title, it.claimed_by) == ("Mine", "user")
