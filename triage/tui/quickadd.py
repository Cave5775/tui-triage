"""Quick-add: the inline token parser and the one-line input docked at the bottom."""

from __future__ import annotations

from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Static

from ..model import PRIORITY_LABELS, STATUS_ALIASES, TYPE_ALIASES


def parse_quick_add(text: str) -> dict:
    """Split quick-add text into ``dict(title, priority, type, status)``.

    Tokens may appear anywhere: ``!1``-``!4`` priority, ``#fix`` (any ``model.TYPE_ALIASES`` key)
    type, ``>todo`` (any ``model.STATUS_ALIASES`` key) initial status. Everything else is the
    title. Unspecified fields are ``None`` so the caller can apply context defaults.
    A later token of the same kind wins; unknown ``#x`` / ``>x`` / ``!9`` stay in the title.
    """
    priority: int | None = None
    type_: str | None = None
    status: str | None = None
    words: list[str] = []
    for tok in text.split():
        low = tok.lower()
        if len(tok) == 2 and tok[0] == "!" and tok[1] in "1234":
            priority = int(tok[1])
        elif tok[0] == "#" and low[1:] in TYPE_ALIASES:
            type_ = TYPE_ALIASES[low[1:]]
        elif tok[0] == ">" and low[1:] in STATUS_ALIASES:
            status = STATUS_ALIASES[low[1:]]
        else:
            words.append(tok)
    return {"title": " ".join(words), "priority": priority, "type": type_, "status": status}


def describe(parsed: dict, default_status: str) -> Text:
    """The live preview line for a parsed quick-add."""
    t = Text()
    title = parsed["title"]
    t.append("title ", style="dim")
    t.append(f'"{title}"' if title else "(empty)", style="bold" if title else "dim italic")
    p = parsed["priority"] or 3
    t.append("  P%d %s" % (p, PRIORITY_LABELS[p]), style="bold" if parsed["priority"] else "dim")
    t.append("  " + (parsed["type"] or "feature"), style="bold" if parsed["type"] else "dim")
    t.append("  → " + (parsed["status"] or default_status), style="bold" if parsed["status"] else "dim")
    return t


class QuickAddScreen(ModalScreen[None]):
    """A one-line input docked at the bottom. Modal, so no key can leak to the list."""

    BINDINGS = [
        Binding("escape", "cancel", "cancel", key_display="esc"),
        Binding("ctrl+enter,alt+enter,ctrl+j", "save_keep", "save + next", key_display="alt+enter", show=True),
    ]

    def __init__(self, save: Callable[[dict], str | None], default_status: str) -> None:
        super().__init__()
        self._save = save  # returns an error message, or None when saved
        self._default_status = default_status
        self.added = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="quickadd"):
            yield Static(id="quickadd-preview")
            yield Input(placeholder="new item — !1-!4 priority  #fix #feat #change #chore #idea  >todo", id="quickadd-input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        self._update_preview("")

    def _update_preview(self, text: str) -> None:
        self.query_one("#quickadd-preview", Static).update(describe(parse_quick_add(text), self._default_status))

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_preview(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if self._submit(event.value):
            self.dismiss(None)

    def action_save_keep(self) -> None:
        inp = self.query_one(Input)
        if self._submit(inp.value):
            inp.value = ""
            self.added += 1

    def _submit(self, text: str) -> bool:
        parsed = parse_quick_add(text)
        if not parsed["title"]:
            self.query_one("#quickadd-preview", Static).update(Text("type a title first", style="bold red"))
            return False
        err = self._save(parsed)
        if err:
            self.query_one("#quickadd-preview", Static).update(Text(err, style="bold red"))
            return False
        return True

    def action_cancel(self) -> None:
        self.dismiss(None)
