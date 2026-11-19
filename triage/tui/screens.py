"""Modal screens: prompts, confirm, help, the add/edit form, settings and the repo picker.

All of these are modal, so no key can leak through to the list underneath.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingsMap
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Label, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from .. import config
from ..model import AGENT_TAG, PRIORITY_LABELS, PRIORITIES, TYPES, USER_TAG, Item
from ..paths import RepoNotFound, RepoRef, board_path, resolve_repo
from ..store import list_boards, read_json
from .fields import ChoiceField
from .keys import Keymap, default_keymap, help_sections
from .widgets import palette

# ---- prompt ------------------------------------------------------------------


class PromptScreen(ModalScreen["str | None"]):
    """A one-line prompt docked at the bottom. Dismisses with the text, or ``None`` on Esc."""

    BINDINGS = [Binding("escape", "cancel", "cancel", key_display="esc", show=True)]

    def __init__(self, title: str, initial: str = "", placeholder: str = "", allow_empty: bool = False) -> None:
        super().__init__()
        self._title = title
        self._initial = initial
        self._placeholder = placeholder
        self._allow_empty = allow_empty

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt"):
            yield Static(self._title, id="prompt-title")
            yield Input(value=self._initial, placeholder=self._placeholder, id="prompt-input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        text = event.value.strip()
        if not text and not self._allow_empty:
            return
        self.dismiss(text)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "answer(True)", "yes", show=True),
        Binding("n,escape,enter", "answer(False)", "no", key_display="n/esc", show=True),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm"):
            yield Static(self._question, id="confirm-text")
            yield Static("[b]y[/b] yes   [b]n[/b] no", id="confirm-hint")
        yield Footer()

    def action_answer(self, yes: bool) -> None:
        self.dismiss(yes)


# ---- answer an agent's question ------------------------------------------------


class AnswerScreen(ModalScreen["tuple[list[str], str] | None"]):
    """The agent's question with its options as a keyboard-first list, plus an "Other" free-text row.

    ``j``/``k`` or the arrows move, a number picks that row (single choice: it answers at once; multiple choice:
    it toggles), ``space`` toggles in multiple-choice mode, ``enter`` submits. The last row is "Other": it focuses
    a text input (``enter`` there submits the text; the arrows go back to the list). ``esc`` cancels.
    Dismisses with ``(choices, text)``, or ``None`` when cancelled.
    """

    AUTO_FOCUS = ""  # the list is driven by the screen's own keys; the input only gets focus on the Other row
    BINDINGS = [
        Binding("escape", "cancel", "cancel", key_display="esc", show=True),
        Binding("enter", "confirm", "submit", show=True),
        Binding("space", "toggle", "toggle", show=False),
        Binding("j,down", "move(1)", "down", show=False),
        Binding("k,up", "move(-1)", "up", show=False),
    ]

    def __init__(self, ref: str, question) -> None:
        super().__init__()
        self._ref = ref
        self._q = question
        self._options = list(question.options)
        self._index = 0  # 0..len(options); the last row is "Other"
        self._checked: set[int] = set()

    @property
    def _other(self) -> int:
        return len(self._options)

    def compose(self) -> ComposeResult:
        n = len(self._options)
        keys = f"1-{n + 1}"
        hint = (f"j/k move · {keys} or space toggle · enter submit · esc cancel" if self._q.multi
                else f"j/k move · {keys} pick · enter confirm · esc cancel")
        with Vertical(id="answer"):
            yield Static(Text(self._q.text, style="bold"), id="answer-question")
            yield Static(Text("pick any" if self._q.multi else "pick one", style="dim"), id="answer-kind")
            yield Static("", id="answer-options")
            with Horizontal(id="answer-other"):
                yield Static("", id="answer-other-label")
                yield Input(placeholder="type your own answer", id="answer-input")
            yield Static("", id="answer-error")
            yield Static(hint, id="answer-hint")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#answer").border_title = f"Question on {self._ref}"
        self._redraw()

    def _redraw(self) -> None:
        accent = palette(self.app)["accent"]
        rows = Text()
        for i, option in enumerate(self._options):
            on = i == self._index
            rows.append("▸ " if on else "  ", style=f"bold {accent}")
            rows.append(f"{i + 1}  ", style=f"bold {accent}" if on else "dim")
            if self._q.multi:
                rows.append("[x] " if i in self._checked else "[ ] ", style="bold" if i in self._checked else "dim")
            rows.append(option, style="bold" if on else "")
            rows.append("\n" if i < len(self._options) - 1 else "")
        self.query_one("#answer-options", Static).update(rows)
        on = self._index == self._other
        label = Text()
        label.append("▸ " if on else "  ", style=f"bold {accent}")
        label.append(f"{self._other + 1}  ", style=f"bold {accent}" if on else "dim")
        label.append("Other: ", style="bold" if on else "")
        self.query_one("#answer-other-label", Static).update(label)

    def _input_focused(self) -> bool:
        return self.focused is self.query_one("#answer-input", Input)

    def _error(self, text: str = "") -> None:
        self.query_one("#answer-error", Static).update(Text(text, style="bold red"))

    def _go_other(self) -> None:
        self._index = self._other
        self._redraw()
        self._error()
        self.query_one("#answer-input", Input).focus()

    def _pick(self, i: int) -> None:
        """Number key or ``space`` on row ``i``."""
        if i == self._other:
            self._go_other()
        elif self._q.multi:
            self._index = i
            self._checked ^= {i}
            self._error()
            self._redraw()
        else:
            self.dismiss(([self._options[i]], ""))

    def action_move(self, delta: int) -> None:
        if self._input_focused():
            self.set_focus(None)
        self._index = max(0, min(self._other, self._index + delta))
        self._error()
        self._redraw()

    def action_toggle(self) -> None:
        if self._q.multi or self._index == self._other:
            self._pick(self._index)
        else:
            self.dismiss(([self._options[self._index]], ""))

    def action_confirm(self) -> None:
        if self._input_focused():
            self._submit_text()
        elif self._index == self._other:
            self._go_other()
        elif self._q.multi:
            self._checked = self._checked or {self._index}  # nothing ticked yet: the highlighted option is the pick
            self.dismiss(([o for i, o in enumerate(self._options) if i in self._checked], ""))
        else:
            self.dismiss(([self._options[self._index]], ""))

    def _submit_text(self) -> None:
        text = self.query_one("#answer-input", Input).value.strip()
        choices = [o for i, o in enumerate(self._options) if i in self._checked] if self._q.multi else []
        if not text and not choices:
            self._error("type an answer, or use ↑/↓ to pick an option")
            return
        self.dismiss((choices, text))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._submit_text()

    def on_key(self, event: events.Key) -> None:
        if event.character and event.character in "1234567" and not self._input_focused():
            event.stop()
            i = int(event.character) - 1
            if i <= self._other:
                self._pick(i)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---- help --------------------------------------------------------------------


def build_help(keymap: Keymap | None = None, hints: list[tuple[str, str]] | None = None) -> Group:
    """The help body: the current context's keys first, then every group (effective keys)."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold", no_wrap=True, min_width=12)
    table.add_column()
    for group, rows in help_sections(keymap or default_keymap()):
        table.add_row(Text(group.upper(), style="bold underline"), "")
        for key, text in rows:
            table.add_row(key, text)
        table.add_row("", "")
    parts: list = []
    if hints:
        line = Text(overflow="fold")
        for n, (key, label) in enumerate(hints):
            if n:
                line.append("   ")
            line.append(key, style="bold")
            line.append(" " + label)
        parts += [Text("Keys for what you're looking at", style="bold underline"), line, Text("")]
    parts.append(table)
    return Group(*parts)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "close", key_display="esc", show=True)]

    def __init__(self, keymap: Keymap | None = None, hints: list[tuple[str, str]] | None = None) -> None:
        super().__init__()
        self._keymap = keymap or default_keymap()
        self._hints = hints or []
        km = self._keymap
        # the keys that close or scroll follow the configured keymap (per instance, like the app's bindings)
        extra = [Binding(k, "close", "close", show=False) for name in ("help", "quit") for k in km.keys_for(name)]
        extra += [Binding(k, "scroll(1)", "scroll", show=False) for k in km.keys_for("cursor_down")]
        extra += [Binding(k, "scroll(-1)", "scroll", show=False) for k in km.keys_for("cursor_up")]
        self._bindings = BindingsMap.merge([self._bindings, BindingsMap(extra)])

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help"):
            yield Static(build_help(self._keymap, self._hints), id="help-body")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#help").border_title = "Keyboard"
        self.query_one("#help").focus()

    def action_close(self) -> None:
        self.dismiss(None)

    def action_scroll(self, delta: int) -> None:
        pane = self.query_one("#help")
        pane.scroll_to(y=max(0, pane.scroll_y + delta * 2), animate=False)


# ---- add / edit form ---------------------------------------------------------


class ItemFormScreen(ModalScreen[None]):
    """Title, type, priority, taken by and body. ``ctrl+s`` saves, ``esc`` cancels, ``tab``/``enter`` move between fields.

    Type, priority and taken by are :class:`ChoiceField` widgets: focus one and use ``←``/``→`` (or ``h``/``l``,
    ``space``) to cycle, or type the first letter (type, taken by) or ``1``-``4`` (priority) to jump.
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "save", show=True),
        Binding("escape", "cancel", "cancel", key_display="esc", show=True),
    ]

    HINT = "tab/enter next field · ←/→ change type, priority & taken by · ctrl+s save · esc cancel"

    def __init__(self, item: Item | None, save: Callable[[dict], str | None]) -> None:
        super().__init__()
        self._item = item
        self._save = save  # returns an error message, or None when saved

    def compose(self) -> ComposeResult:
        it = self._item
        with Vertical(id="form"):
            yield Label("title")
            yield Input(value=it.title if it else "", placeholder="what needs doing?", id="f-title")
            with Horizontal(id="form-row"):
                with Vertical():
                    yield Label(_field_label("type", "←/→ to change"), id="f-type-label")
                    yield ChoiceField([(t, t) for t in TYPES], it.type if it else "feature", id="f-type")
                with Vertical():
                    yield Label(_field_label("priority", "←/→ or 1-4"), id="f-priority-label")
                    yield ChoiceField(
                        [(f"P{p} {PRIORITY_LABELS[p]}", p) for p in PRIORITIES],
                        it.priority if it else 3,
                        jump={p: str(p) for p in PRIORITIES},
                        id="f-priority",
                    )
                with Vertical():
                    yield Label(_field_label("taken by", "←/→"), id="f-taken-label")
                    yield ChoiceField(*self._taken_choices(), id="f-taken")
            yield Label("body (markdown)", id="f-body-label")
            yield TextArea(it.body if it else "", id="f-body", tab_behavior="focus")
            yield Static("", id="form-error")
            yield Static(self.HINT, id="form-hint")
        yield Footer()

    def _taken_choices(self) -> tuple[list[tuple[str, str]], str]:
        """Options and current value for the "taken by" field: none / agent / user.

        An item an agent took under its own name keeps that name as the agent choice, so saving the form
        without touching the field leaves the tag as it is.
        """
        current = self._item.claimed_by if self._item else None
        agent = current if current and current != USER_TAG else AGENT_TAG
        return [("none", "none"), (agent, agent), ("user", USER_TAG)], current or "none"

    def on_mount(self) -> None:
        self.query_one("#form").border_title = f"Edit {it.ref}" if (it := self._item) else "New item"
        self.query_one("#f-title").focus()
        self._fit(self.size.height)

    def on_resize(self, event: events.Resize) -> None:
        self._fit(event.size.height)

    def _fit(self, height: int) -> None:
        self.set_class(height < 30, "-compact")

    def values(self) -> dict:
        return {
            "title": self.query_one("#f-title", Input).value,
            "type": self.query_one("#f-type", ChoiceField).value,
            "priority": self.query_one("#f-priority", ChoiceField).value,
            "taken_by": self.query_one("#f-taken", ChoiceField).value,
            "body": self.query_one("#f-body", TextArea).text,
        }

    def action_save(self) -> None:
        err = self._save(self.values())
        if err:
            self.query_one("#form-error", Static).update(Text(err, style="bold red"))
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.focus_next()

    def on_choice_field_submitted(self, event: ChoiceField.Submitted) -> None:
        event.stop()
        self.focus_next()

    def action_cancel(self) -> None:
        self.dismiss(None)


def _field_label(name: str, hint: str) -> Text:
    return Text.assemble(name, "  ", (hint, "dim"))


# ---- settings ----------------------------------------------------------------


def _fmt(value) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, list):
        return ", ".join(value)
    return str(value)


class SettingsScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "close", key_display="esc", show=True),
        Binding("j,down", "cursor(1)", "down", show=False),
        Binding("k,up", "cursor(-1)", "up", show=False),
        Binding("enter,space", "edit", "toggle/edit", key_display="enter", show=True),
        Binding("b", "scope", "global/board", show=True),
        Binding("x", "remove", "remove override", show=True),
    ]

    def __init__(self, board_id: str | None, on_change: Callable[[], None]) -> None:
        super().__init__()
        self._board_id = board_id
        self._on_change = on_change
        self.scope = "global"
        self._editing: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="settings"):
            yield DataTable(id="settings-table", cursor_type="row", zebra_stripes=False)
            yield Static("", id="settings-help")
            yield Static("", id="settings-msg")
            yield Input(id="settings-input")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_column("setting", key="key")
        t.add_column("value", key="value")
        t.add_column("from", key="source")
        t.add_column("help", key="help")
        self.query_one("#settings-input").display = False
        self._fill()
        t.focus()

    def _title(self) -> None:
        where = "global" if self.scope == "global" else "this board"
        self.query_one("#settings").border_title = f"Settings — editing {where}"

    def _fill(self, keep: int | None = None) -> None:
        t = self.query_one(DataTable)
        row = t.cursor_row if keep is None else keep
        cfg = config.get_config(self._board_id)
        glob = config.overrides(None)
        board = config.overrides(self._board_id) if self._board_id else {}
        t.clear()
        for s in config.SETTINGS:
            source = "board" if s.key in board else "global" if s.key in glob else "default"
            style = {"board": "bold", "global": "", "default": "dim"}[source]
            t.add_row(Text(s.key, style=style), Text(_fmt(cfg[s.key]), style="bold" if source != "default" else ""),
                      Text(source, style="dim"), Text(s.help, style="dim"), key=s.key)
        if t.row_count:
            t.move_cursor(row=max(0, min(row, t.row_count - 1)))
        self._title()

    def _say(self, text: str, error: bool = False) -> None:
        self.query_one("#settings-msg", Static).update(Text(text, style="bold red" if error else "green"))

    def _current(self) -> config.Setting:
        t = self.query_one(DataTable)
        return config.SETTINGS[t.cursor_row]

    def _target_board(self) -> str | None:
        return self._board_id if self.scope == "board" else None

    def _write(self, key: str, value) -> bool:
        if self.scope == "board" and not self._board_id:
            self._say("no board is open", error=True)
            return False
        try:
            config.set_value(key, value, self._target_board())
        except (ValueError, OSError) as exc:
            self._say(str(exc), error=True)
            return False
        self._fill()
        self._on_change()
        return True

    def action_cursor(self, delta: int) -> None:
        t = self.query_one(DataTable)
        t.move_cursor(row=max(0, min(t.row_count - 1, t.cursor_row + delta)))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if 0 <= event.cursor_row < len(config.SETTINGS):
            s = config.SETTINGS[event.cursor_row]
            self.query_one("#settings-help", Static).update(Text(s.help, style="dim"))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.action_edit()

    def action_edit(self) -> None:
        if self._editing:
            return
        s = self._current()
        cur = config.get_config(self._board_id)[s.key]
        if s.kind is bool:
            if self._write(s.key, not cur):
                self._say(f"{s.key} = {_fmt(not cur)} ({self.scope})")
        elif s.kind is str and s.choices:
            nxt = s.choices[(s.choices.index(cur) + 1) % len(s.choices)] if cur in s.choices else s.choices[0]
            if self._write(s.key, nxt):
                self._say(f"{s.key} = {nxt} ({self.scope})")
        else:
            self._editing = s.key
            inp = self.query_one("#settings-input", Input)
            inp.value = _fmt(cur)
            inp.placeholder = s.key
            inp.display = True
            inp.focus()
            inp.cursor_position = len(inp.value)
            self._say(f"{s.key}: enter saves, esc cancels" + (" (comma separated)" if s.kind is list else ""))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        key = self._editing
        if key is None:
            return
        try:
            value = config.parse_value(key, event.value)
        except ValueError as exc:
            self._say(str(exc), error=True)
            return
        if self._write(key, value):
            self._close_input()
            self._say(f"{key} = {_fmt(value)} ({self.scope})")

    def _close_input(self) -> None:
        self._editing = None
        inp = self.query_one("#settings-input", Input)
        inp.display = False
        self.query_one(DataTable).focus()

    def action_scope(self) -> None:
        if self._editing:
            return
        if not self._board_id and self.scope == "global":
            self._say("no board is open", error=True)
            return
        self.scope = "board" if self.scope == "global" else "global"
        self._title()
        self._say(f"now editing {'this board' if self.scope == 'board' else 'global settings'}")

    def action_remove(self) -> None:
        if self._editing:
            return
        s = self._current()
        have = config.overrides(self._target_board())
        if s.key not in have:
            self._say(f"no {self.scope} override for {s.key}")
            return
        if self._write(s.key, None):
            self._say(f"removed {self.scope} override of {s.key}")

    def action_close(self) -> None:
        if self._editing:
            self._close_input()
            self._say("")
            return
        self.dismiss(None)


# ---- repo picker -------------------------------------------------------------


def fuzzy_score(query: str, text: str) -> int | None:
    """Subsequence match; lower is better (tighter, earlier). ``None`` when it does not match."""
    q, t = query.lower(), text.lower()
    if not q:
        return 0
    pos, first, last = -1, -1, -1
    for ch in q:
        pos = t.find(ch, pos + 1)
        if pos < 0:
            return None
        if first < 0:
            first = pos
        last = pos
    return (last - first) + first


def board_counts(board_id: str) -> str:
    try:
        data = read_json(board_path(board_id), default={}) or {}
        counts: dict[str, int] = {}
        for it in data.get("items", []):
            counts[it.get("status", "?")] = counts.get(it.get("status", "?"), 0) + 1
    except (OSError, ValueError):
        return ""
    parts = [f"{counts[s]} {s}" for s in ("inbox", "todo", "doing", "review") if counts.get(s)]
    return " · ".join(parts) if parts else "empty"


class RepoPickerScreen(ModalScreen["RepoRef | None"]):
    """Fuzzy-filter the known boards; enter opens one, ctrl+n (or typing an existing path) registers a repo."""

    BINDINGS = [
        Binding("escape", "cancel", "close", key_display="esc", show=True),
        Binding("down", "move(1)", "down", show=False),
        Binding("up", "move(-1)", "up", show=False),
        Binding("ctrl+n", "register", "add repo path", show=True),
    ]

    def __init__(self, can_cancel: bool = True) -> None:
        super().__init__()
        self._boards: list[dict] = []
        self._shown: list[dict] = []
        self.can_cancel = can_cancel

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Input(placeholder="filter boards, or type a repo path and press enter", id="picker-input")
            yield OptionList(id="picker-list")
            yield Static("", id="picker-msg")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#picker").border_title = "Open a board"
        self._boards = list_boards()
        self._refilter("")
        self.query_one(Input).focus()

    def _refilter(self, query: str) -> None:
        scored = []
        for n, b in enumerate(self._boards):
            s = fuzzy_score(query, f"{b.get('name', '')} {b.get('path', '')}")
            if s is not None:
                scored.append((s, n, b))
        scored.sort(key=lambda x: (x[0], x[1]))
        self._shown = [b for _, _, b in scored]
        ol = self.query_one(OptionList)
        ol.clear_options()
        for n, b in enumerate(self._shown):
            row = Text()
            row.append(str(b.get("name", "?")), style="bold")
            row.append("   " + board_counts(b["board_id"]), style="")
            row.append("\n" + str(b.get("path", "")), style="dim")
            ol.add_option(Option(row, id=str(n)))
        if self._shown:
            ol.highlighted = 0
        else:
            ol.add_option(Option(Text("no matching boards", style="dim italic"), id="none", disabled=True))

    def _say(self, text: str, error: bool = True) -> None:
        self.query_one("#picker-msg", Static).update(Text(text, style="bold red" if error else "green"))

    def on_input_changed(self, event: Input.Changed) -> None:
        self._say("")
        self._refilter(event.value)

    def action_move(self, delta: int) -> None:
        ol = self.query_one(OptionList)
        if delta > 0:
            ol.action_cursor_down()
        else:
            ol.action_cursor_up()

    def _open_path(self, text: str) -> None:
        try:
            ref = resolve_repo(Path(text).expanduser())
        except RepoNotFound as exc:
            self._say(str(exc))
            return
        self.dismiss(ref)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        text = event.value.strip().strip('"').strip("'")
        if text and Path(text).expanduser().is_dir():
            self._open_path(text)
            return
        self._open_highlighted()

    def _open_highlighted(self) -> None:
        ol = self.query_one(OptionList)
        idx = ol.highlighted
        if idx is None or not self._shown:
            self._say("nothing to open — type a repo path and press enter")
            return
        board = self._shown[int(ol.get_option_at_index(idx).id)]
        path = board.get("path", "")
        if not path or not Path(path).is_dir():
            self._say(f"path no longer exists: {path}")
            return
        self._open_path(path)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self._open_highlighted()

    def action_register(self) -> None:
        text = self.query_one(Input).value.strip()
        if not text:
            self._say("type the path of a git repository first")
            return
        if not Path(text).expanduser().is_dir():
            self._say(f"not a directory: {text}")
            return
        self._open_path(text)

    def action_cancel(self) -> None:
        self.dismiss(None)
