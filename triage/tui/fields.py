"""A keyboard-first inline choice field: ``◀ feature ▶``.

Focus it and use ``←``/``→`` (or ``h``/``l``, or ``space``) to cycle, or type the first letter or digit of a value
to jump to it. Clicking an arrow works too. ``enter`` posts :class:`ChoiceField.Submitted` so a form can move on.
"""

from __future__ import annotations

from typing import Any, Sequence

from rich.text import Text
from textual import events
from textual.message import Message
from textual.widget import Widget

_ARROW_W = 3  # " ◀ " and " ▶ "


class ChoiceField(Widget, can_focus=True):
    """One value out of a short, fixed list. ``options`` are ``(label, value)`` pairs.

    ``jump`` maps each value to the text its jump-by-typing match is made against (default: the label), so a
    priority can be reached with its digit even though its label reads ``P3 normal``.
    """

    DEFAULT_CSS = """
    ChoiceField {
        height: 1;
        width: auto;
    }
    """

    class Changed(Message):
        def __init__(self, field: "ChoiceField", value: Any) -> None:
            super().__init__()
            self.field = field
            self.value = value

    class Submitted(Message):
        """``enter`` pressed on the field."""

        def __init__(self, field: "ChoiceField") -> None:
            super().__init__()
            self.field = field

    def __init__(
        self,
        options: Sequence[tuple[str, Any]],
        value: Any = None,
        *,
        jump: dict[Any, str] | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._options = list(options)
        if not self._options:
            raise ValueError("ChoiceField needs at least one option")
        values = [v for _, v in self._options]
        self._index = values.index(value) if value in values else 0
        self._jump = {v: (jump or {}).get(v, label).lower() for label, v in self._options}
        self._label_w = max(len(label) for label, _ in self._options)

    # ---- value --------------------------------------------------------------
    @property
    def value(self) -> Any:
        return self._options[self._index][1]

    @value.setter
    def value(self, new: Any) -> None:
        values = [v for _, v in self._options]
        if new not in values:
            raise ValueError(f"{new!r} is not one of {values!r}")
        self._select(values.index(new))

    @property
    def label(self) -> str:
        return self._options[self._index][0]

    def _select(self, index: int) -> None:
        index %= len(self._options)
        if index != self._index:
            self._index = index
            self.refresh(layout=True)
            self.post_message(self.Changed(self, self.value))

    def cycle(self, step: int) -> None:
        self._select(self._index + step)

    def jump_to(self, char: str) -> bool:
        """Select the next value (after the current one, wrapping) whose jump text starts with ``char``."""
        char = char.lower()
        n = len(self._options)
        for k in range(1, n + 1):
            i = (self._index + k) % n
            if self._jump[self._options[i][1]].startswith(char):
                self._select(i)
                return True
        return False

    # ---- rendering ----------------------------------------------------------
    def render(self) -> Text:
        arrow = "bold" if self.has_focus else "dim"
        text = Text(no_wrap=True, overflow="crop")
        text.append(" ◀ ", style=arrow)
        text.append(self.label.center(self._label_w), style="bold" if self.has_focus else "")
        text.append(" ▶ ", style=arrow)
        return text

    def get_content_width(self, container, viewport) -> int:
        return self._label_w + 2 * _ARROW_W

    # ---- input --------------------------------------------------------------
    def on_key(self, event: events.Key) -> None:
        key, char = event.key, event.character
        if key in ("right", "l", "space"):
            self.cycle(1)
        elif key in ("left", "h"):
            self.cycle(-1)
        elif key == "enter":
            self.post_message(self.Submitted(self))
        elif char and char.isalnum() and not key.startswith(("ctrl+", "alt+")):
            self.jump_to(char)  # an unknown letter does nothing, but is still swallowed
        else:
            return  # tab, shift+tab, escape, ctrl+s ...: left to focus handling and the screen bindings
        event.stop()
        event.prevent_default()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.focus()
        width = self._label_w + 2 * _ARROW_W
        if event.x < _ARROW_W:
            self.cycle(-1)
        elif event.x >= width - _ARROW_W:
            self.cycle(1)
