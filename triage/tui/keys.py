"""The single source of truth for the main-screen keymap.

The Textual ``BINDINGS`` (and therefore the footer) and the ``?`` help screen are both
generated from :data:`KEYS` and :data:`CHORDS`, so they cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.binding import Binding

GROUPS = ("Navigate", "Capture", "Triage", "App")


@dataclass(frozen=True)
class KeyDef:
    keys: str  # Textual key names, comma separated
    action: str  # App action (may carry parameters, e.g. "goto_tab('inbox')")
    group: str
    display: str  # how the key is written in the footer and help
    desc: str  # short footer text
    help: str = ""  # help-screen text (defaults to desc)
    show: bool = False  # shown in the footer
    priority: bool = False
    help_hidden: bool = False  # alternate binding of an already listed action

    @property
    def help_text(self) -> str:
        return self.help or self.desc


@dataclass(frozen=True)
class Chord:
    """A two-key sequence: ``prefix`` followed by one of ``options``."""

    prefix: str
    group: str
    label: str  # "move to"
    options: tuple[tuple[str, str], ...]  # (second key, what it does)
    help: str


def _k(keys, action, group, display, desc, help="", **kw) -> KeyDef:
    return KeyDef(keys, action, group, display, desc, help, **kw)


KEYS: tuple[KeyDef, ...] = (
    # ---- Navigate -------------------------------------------------------
    _k("j,down", "cursor_down", "Navigate", "j/↓", "down", "move down (scrolls the detail pane when it has focus)"),
    _k("k,up", "cursor_up", "Navigate", "k/↑", "up", "move up"),
    _k("g,home", "go_top", "Navigate", "g/Home", "top", "jump to the top"),
    _k("G,end", "go_bottom", "Navigate", "G/End", "bottom", "jump to the bottom"),
    _k("ctrl+d", "half_down", "Navigate", "ctrl+d", "half page down", "half page down"),
    _k("ctrl+u", "half_up", "Navigate", "ctrl+u", "half page up", "half page up"),
    _k("l,right", "tab_next", "Navigate", "l/→", "next tab", "next status tab (also tab)"),
    _k("h,left", "tab_prev", "Navigate", "h/←", "prev tab", "previous status tab (also shift+tab)"),
    _k("tab", "tab_next", "Navigate", "tab", "next tab", priority=True, help_hidden=True),
    _k("shift+tab", "tab_prev", "Navigate", "shift+tab", "prev tab", priority=True, help_hidden=True),
    _k("1", "goto_tab('inbox')", "Navigate", "1-5", "tab", "jump to Inbox / Todo / Doing / Review / Done"),
    _k("2", "goto_tab('todo')", "Navigate", "2", "tab", help_hidden=True),
    _k("3", "goto_tab('doing')", "Navigate", "3", "tab", help_hidden=True),
    _k("4", "goto_tab('review')", "Navigate", "4", "tab", help_hidden=True),
    _k("5", "goto_tab('done')", "Navigate", "5", "tab", help_hidden=True),
    _k("0", "goto_tab('all')", "Navigate", "0", "all", "show All (every non-archived status)"),
    _k("9", "goto_tab('archived')", "Navigate", "9", "archived", "show Archived (also h/l past All)"),
    _k("slash", "filter", "Navigate", "/", "find", "filter by title/body (enter keeps it, esc clears it)", show=True),
    _k("enter", "focus_detail", "Navigate", "enter", "detail", "focus the detail pane to scroll it (esc returns)"),
    _k("escape", "detail_back", "Navigate", "esc", "back to list", "leave the detail pane (shown while it has focus)",
       show=True),
    _k("escape", "clear_filter", "Navigate", "esc", "clear filter", "clear the filter", show=True, help_hidden=True),
    # ---- Capture --------------------------------------------------------
    _k("a", "quick_add", "Capture", "a", "add", "quick add: !1-!4 priority, #fix type, >todo status "
       "(enter saves, alt+enter / ctrl+j saves and keeps open)", show=True),
    _k("A", "add_form", "Capture", "A", "add form", "full add form (ctrl+s saves, esc cancels)"),
    _k("e", "edit_form", "Capture", "e", "edit", "edit the selected item in the form"),
    _k("E", "edit_external", "Capture", "E", "$EDITOR", "edit the body in $VISUAL / $EDITOR"),
    _k("c", "note", "Capture", "c", "note", "add a note (how you reply to the agent)", show=True),
    # ---- Triage ---------------------------------------------------------
    _k("space", "advance", "Triage", "space", "next", "advance to the next status", show=True),
    _k("backspace", "retreat", "Triage", "backspace", "back", "move to the previous status"),
    _k("space", "restore", "Triage", "space", "restore", "restore an archived item to inbox", show=True, help_hidden=True),
    _k("m", "chord('m')", "Triage", "m", "move", "", show=True, help_hidden=True),
    _k("y", "accept", "Triage", "y", "accept", "accept (Review only): move to Done", show=True),
    _k("y", "accept_hint", "Triage", "y", "accept", help_hidden=True),
    _k("n", "bounce", "Triage", "n", "bounce", "bounce with a reason: back to Todo, logged for the agent"),
    _k("p", "chord('p')", "Triage", "p", "priority", "", help_hidden=True),
    _k("plus,equals_sign", "prio_up", "Triage", "+/=", "raise", "raise priority (lower number)"),
    _k("minus", "prio_down", "Triage", "-", "lower", "lower priority"),
    _k("t", "type_next", "Triage", "t", "type", "cycle the type forward"),
    _k("T", "type_prev", "Triage", "T", "type", "cycle the type backward"),
    _k("J", "reorder_down", "Triage", "J", "move down", "move the item down within its column"),
    _k("K", "reorder_up", "Triage", "K", "move up", "move the item up within its column"),
    _k("d", "chord('d')", "Triage", "d d", "archive", "", show=True, help_hidden=True),
    _k("D", "purge", "Triage", "D", "purge", "permanently delete (Archived tab; asks y/n)", show=True),
    _k("D", "purge_hint", "Triage", "D", "purge", help_hidden=True),
    _k("u", "undo", "Triage", "u", "undo", "undo the last change made in this session", show=True),
    _k("Y", "copy_handoff", "Triage", "Y", "copy", "copy `triage show <id>` to the clipboard"),
    # ---- App ------------------------------------------------------------
    _k("comma", "settings", "App", ",", "settings", "settings (global or per board)"),
    _k("R", "repos", "App", "R", "repos", "repo picker"),
    _k("question_mark", "help", "App", "?", "help", "this help", show=True),
    _k("q", "quit", "App", "q", "quit", "quit", show=True),
)

CHORDS: tuple[Chord, ...] = (
    Chord("m", "Triage", "move to", (("i", "inbox"), ("t", "todo"), ("d", "doing"), ("r", "review"), ("x", "done")),
          "move the item to a status"),
    Chord("p", "Triage", "priority", (("1", "urgent"), ("2", "high"), ("3", "normal"), ("4", "low")),
          "set the priority"),
    Chord("d", "Triage", "archive", (("d", "archive"),),
          "press d twice to archive (in Archived: purge, asks y/n)"),
)
CHORDS_BY_PREFIX = {c.prefix: c for c in CHORDS}


def bindings() -> list[Binding]:
    """The ``BINDINGS`` list for the app, generated from :data:`KEYS`."""
    return [
        Binding(k.keys, k.action, k.desc, show=k.show, key_display=k.display, priority=k.priority)
        for k in KEYS
    ]


def help_sections() -> list[tuple[str, list[tuple[str, str]]]]:
    """Grouped ``(key label, description)`` rows for the help screen."""
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    for group in GROUPS:
        rows = [(k.display, k.help_text) for k in KEYS if k.group == group and not k.help_hidden]
        for c in CHORDS:
            if c.group == group:
                opts = " ".join(f"{key} {name}" for key, name in c.options)
                rows.append((f"{c.prefix} …" if len(c.options) > 1 else f"{c.prefix} {c.options[0][0]}",
                             f"{c.help}: {opts}" if len(c.options) > 1 else c.help))
        sections.append((group, rows))
    return sections


def chord_prompt(chord: Chord) -> str:
    if chord.prefix == "d":
        return "press d again to archive · esc cancels"
    opts = " · ".join(f"{key} {name}" for key, name in chord.options)
    return f"{chord.label}: {opts}"
