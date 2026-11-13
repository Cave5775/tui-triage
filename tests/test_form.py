"""The add/edit form: keyboard-first type and priority fields, field order and hints."""

from __future__ import annotations

import pytest
from textual.app import App
from textual.widgets import Input, Static, TextArea

from triage import ops
from triage.model import PRIORITIES, TYPES, Item
from triage.tui.fields import ChoiceField
from triage.tui.screens import ItemFormScreen

SIZE = (120, 40)


class Host(App):
    """Pushes an ItemFormScreen and records what ``save`` receives."""

    def __init__(self, item: Item | None = None, error: str | None = None) -> None:
        super().__init__()
        self.item = item
        self.error = error
        self.saved: list[dict] = []
        self.main_keys: list[str] = []

    def on_mount(self) -> None:
        self.push_screen(ItemFormScreen(self.item, self._save))

    def _save(self, values: dict) -> str | None:
        self.saved.append(values)
        return self.error

    # main-screen actions that must never fire from inside the form
    def action_leak(self) -> None:
        self.main_keys.append("leak")

    BINDINGS = [("a", "leak", "x"), ("q", "leak", "x"), ("1", "leak", "x"), ("j", "leak", "x"), ("?", "leak", "x")]


async def settle(pilot) -> None:
    await pilot.pause()
    await pilot.pause()


def focused_id(app) -> str | None:
    return app.focused.id if app.focused else None


async def to_type(pilot) -> None:
    await pilot.press("enter")
    await settle(pilot)


async def to_priority(pilot) -> None:
    await pilot.press("enter", "enter")
    await settle(pilot)


async def test_type_cycles_with_arrows_and_wraps():
    app = Host()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await to_type(pilot)
        field = app.screen.query_one("#f-type", ChoiceField)
        assert focused_id(app) == "f-type" and field.value == "feature"
        await pilot.press("right")
        assert field.value == "fix"
        await pilot.press("left", "left")
        assert field.value == "idea"  # wrapped backwards
        await pilot.press("right")
        assert field.value == "feature"  # wrapped forwards
        for expected in TYPES[1:]:
            await pilot.press("right")
            assert field.value == expected


async def test_type_cycles_with_h_l_and_space():
    app = Host()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await to_type(pilot)
        field = app.screen.query_one("#f-type", ChoiceField)
        await pilot.press("l")
        assert field.value == "fix"
        await pilot.press("space")
        assert field.value == "change"
        await pilot.press("h")
        assert field.value == "fix"
        await pilot.press("h", "h")
        assert field.value == "idea"
        await pilot.press("space")
        assert field.value == "feature"


async def test_type_jumps_by_first_letter():
    app = Host()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await to_type(pilot)
        field = app.screen.query_one("#f-type", ChoiceField)
        await pilot.press("i")
        assert field.value == "idea"
        await pilot.press("c")
        assert field.value == "change"
        await pilot.press("c")
        assert field.value == "chore"  # next value starting with c
        await pilot.press("c")
        assert field.value == "change"  # and it wraps
        await pilot.press("f")
        assert field.value == "feature"
        await pilot.press("f")
        assert field.value == "fix"
        await pilot.press("z")  # nothing starts with z
        assert field.value == "fix"


async def test_priority_digits_pick_directly():
    app = Host()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await to_priority(pilot)
        field = app.screen.query_one("#f-priority", ChoiceField)
        assert focused_id(app) == "f-priority" and field.value == 3
        for p in PRIORITIES:
            await pilot.press(str(p))
            assert field.value == p
        await pilot.press("5")  # not a priority
        assert field.value == 4


async def test_priority_cycles_and_wraps():
    app = Host()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await to_priority(pilot)
        field = app.screen.query_one("#f-priority", ChoiceField)
        await pilot.press("right", "right")
        assert field.value == 1  # 3 -> 4 -> 1
        await pilot.press("left")
        assert field.value == 4
        await pilot.press("space")
        assert field.value == 1


async def test_enter_advances_title_type_priority_body():
    app = Host()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert focused_id(app) == "f-title"
        order = []
        for _ in range(3):
            await pilot.press("enter")
            await settle(pilot)
            order.append(focused_id(app))
        assert order == ["f-type", "f-priority", "f-body"]
        # enter in the body is a newline, not "next"
        await pilot.press("enter")
        assert focused_id(app) == "f-body"
        assert app.screen.query_one("#f-body", TextArea).text == "\n"


async def test_tab_order_and_shift_tab():
    app = Host()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        seen = [focused_id(app)]
        for _ in range(4):
            await pilot.press("tab")
            await settle(pilot)
            seen.append(focused_id(app))
        assert seen[:4] == ["f-title", "f-type", "f-priority", "f-body"]
        assert seen[4] == "f-title"  # wraps
        await pilot.press("shift+tab")
        await settle(pilot)
        assert focused_id(app) == "f-body"
        await pilot.press("shift+tab")
        await settle(pilot)
        assert focused_id(app) == "f-priority"
        # tab in the body moves focus, it does not insert a tab character
        await pilot.press("tab")
        await settle(pilot)
        assert focused_id(app) == "f-body"
        await pilot.press("tab")
        await settle(pilot)
        assert app.screen.query_one("#f-body", TextArea).text == ""


async def test_ctrl_s_returns_chosen_values_from_any_field():
    app = Host()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("W", "i", "p", "enter")  # title, then on to type
        await pilot.press("i")  # idea
        await pilot.press("enter", "1")  # priority P1
        await pilot.press("enter", "h", "i")  # body
        await pilot.press("ctrl+s")
        await settle(pilot)
        assert not isinstance(app.screen, ItemFormScreen)
    assert app.saved == [{"title": "Wip", "type": "idea", "priority": 1, "body": "hi"}]
    assert isinstance(app.saved[0]["priority"], int) and app.saved[0]["type"] in TYPES


@pytest.mark.parametrize("presses,field", [(["tab"], "f-type"), (["tab", "tab"], "f-priority"), (["tab"] * 3, "f-body")])
async def test_ctrl_s_and_esc_work_from_every_field(presses, field):
    for key in ("ctrl+s", "escape"):
        app = Host()
        async with app.run_test(size=SIZE) as pilot:
            await settle(pilot)
            await pilot.press(*presses)
            await settle(pilot)
            assert focused_id(app) == field
            await pilot.press(key)
            await settle(pilot)
            assert not isinstance(app.screen, ItemFormScreen)
        assert len(app.saved) == (1 if key == "ctrl+s" else 0)


async def test_esc_cancels_without_saving():
    app = Host()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("x", "escape")
        await settle(pilot)
        assert not isinstance(app.screen, ItemFormScreen)
    assert app.saved == []


async def test_save_error_is_shown_and_form_stays_open():
    app = Host(error="title must not be empty")
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("ctrl+s")
        await settle(pilot)
        assert isinstance(app.screen, ItemFormScreen)
        assert "title must not be empty" in str(app.screen.query_one("#form-error", Static).render())
    assert len(app.saved) == 1


async def test_edit_form_is_prefilled_from_item(store):
    [a] = [ops.add(store, "old title", actor="user", status="todo", priority=2).item.id]
    ops.update(store, a, actor="user", body="old body", type="chore")
    item = store.load().get(a)
    app = Host(item)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        form = app.screen
        assert form.query_one("#f-title", Input).value == "old title"
        assert form.query_one("#f-type", ChoiceField).value == "chore"
        assert form.query_one("#f-priority", ChoiceField).value == 2
        assert form.query_one("#f-body", TextArea).text == "old body"
        assert form.query_one("#form").border_title == f"Edit {item.ref}"
        await pilot.press("ctrl+s")
        await settle(pilot)
    assert app.saved == [{"title": "old title", "type": "chore", "priority": 2, "body": "old body"}]


async def test_new_form_defaults():
    app = Host()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert app.screen.values() == {"title": "", "type": "feature", "priority": 3, "body": ""}
        assert app.screen.query_one("#form").border_title == "New item"


async def test_hint_line_and_field_hints_present():
    app = Host()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        hint = str(app.screen.query_one("#form-hint", Static).render())
        assert hint == "tab/enter next field · ←/→ change type & priority · ctrl+s save · esc cancel"
        assert "←/→ to change" in str(app.screen.query_one("#f-type-label").render())
        assert "←/→ or 1-4" in str(app.screen.query_one("#f-priority-label").render())
        assert app.screen.query("Footer")


async def test_choice_field_renders_arrows_around_value():
    app = Host()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        text = app.screen.query_one("#f-type", ChoiceField).render().plain
        assert "◀" in text and "feature" in text and "▶" in text


async def test_clicking_arrows_changes_value():
    app = Host()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        field = app.screen.query_one("#f-type", ChoiceField)
        await pilot.click("#f-type", offset=(field.size.width - 1, 0))
        await settle(pilot)
        assert field.value == "fix" and app.focused is field
        await pilot.click("#f-type", offset=(0, 0))
        await pilot.click("#f-type", offset=(0, 0))
        await settle(pilot)
        assert field.value == "idea"


async def test_keys_do_not_leak_to_the_host_app():
    app = Host()
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("a", "q", "j", "1", "tab", "a", "q", "j", "1", "tab", "a", "q", "j", "1", "?")
        await settle(pilot)
        assert app.main_keys == []
        assert isinstance(app.screen, ItemFormScreen)
