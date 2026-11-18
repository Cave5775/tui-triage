"""The single source of truth for the main-screen keymap.

Every user-facing command has a stable name (``cursor_down``, ``quick_add``, ``edit``, ...) and a
default key list in :data:`COMMANDS`. The user can override the keys in ``config.toml``::

    [keys]
    quit = "q, ctrl+q"
    help = "?"

:func:`build_keymap` overlays that table on the defaults, validates it (unknown commands, empty or
unknown keys, one key bound to two commands) and falls back to the default for every invalid entry,
collecting :class:`Problem` objects instead of raising. The Textual bindings, the context-aware hint
bar (:data:`HINT_CONTEXTS`), the ``?`` help screen and ``triage config init|keys`` are all generated
from this table, so they cannot drift apart and always show the *effective* keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from textual.binding import Binding
from textual.keys import Keys, _character_to_key

GROUPS = ("Navigate", "Capture", "Triage", "App")

# Where a command is live. ``list``: the item list has focus; ``detail``: the detail pane has
# focus; ``filter``: the filter box has focus. Two commands may share a key only if their
# contexts never overlap.
CTX_LIST_DETAIL = ("list", "detail")
CTX_ALL = ("list", "detail", "filter")


@dataclass(frozen=True)
class Command:
    name: str  # stable name used in config.toml
    keys: tuple[str, ...]  # default Textual key names
    group: str
    desc: str  # help-screen text and the comment in the generated config
    actions: tuple[str, ...]  # app actions the keys trigger (context duplicates share one entry)
    priority: bool = False  # Textual priority binding (checked before the focused widget)
    contexts: tuple[str, ...] = CTX_LIST_DETAIL
    row: str = ""  # commands with the same non-empty row share one line in the help screen


def _c(name, keys, group, desc, actions=None, **kw) -> Command:
    ks = tuple(k.strip() for k in keys.split(",")) if isinstance(keys, str) else tuple(keys)
    acts = (actions,) if isinstance(actions, str) else tuple(actions or (name,))
    return Command(name, ks, group, desc, acts, **kw)


COMMANDS: tuple[Command, ...] = (
    # ---- Navigate -------------------------------------------------------
    _c("cursor_down", "j,down", "Navigate", "Move down (scrolls the detail pane when it has focus)"),
    _c("cursor_up", "k,up", "Navigate", "Move up (scrolls the detail pane when it has focus)"),
    _c("go_top", "g,home", "Navigate", "Jump to the top", "go_top"),
    _c("go_bottom", "G,end", "Navigate", "Jump to the bottom", "go_bottom"),
    _c("half_down", "ctrl+d,pagedown", "Navigate", "Half page down", "half_down"),
    _c("half_up", "ctrl+u,pageup", "Navigate", "Half page up", "half_up"),
    _c("tab_next", "l,right", "Navigate", "Next status tab", "tab_next"),
    _c("tab_prev", "h,left", "Navigate", "Previous status tab", "tab_prev"),
    _c("tab_inbox", "1", "Navigate", "Jump to the Inbox tab", "goto_tab('inbox')", row="tabs"),
    _c("tab_todo", "2", "Navigate", "Jump to the Todo tab", "goto_tab('todo')", row="tabs"),
    _c("tab_doing", "3", "Navigate", "Jump to the Doing tab", "goto_tab('doing')", row="tabs"),
    _c("tab_review", "4", "Navigate", "Jump to the Review tab", "goto_tab('review')", row="tabs"),
    _c("tab_done", "5", "Navigate", "Jump to the Done tab", "goto_tab('done')", row="tabs"),
    _c("tab_all", "0", "Navigate", "Show All (every non-archived status)", "goto_tab('all')"),
    _c("tab_archived", "9", "Navigate", "Show Archived (also h/l past All)", "goto_tab('archived')"),
    _c("filter", "slash", "Navigate", "Filter by title/body (enter keeps it, esc clears it)", "filter"),
    _c("sort_next", "o", "Navigate", "Sort by: priority, last activity, newest, oldest, title", "sort_next",
       row="sort"),
    _c("sort_prev", "O", "Navigate", "Previous sort order", "sort_prev", row="sort"),
    _c("focus_detail", "enter", "Navigate", "Focus the detail pane to scroll it", "focus_detail",
       contexts=("list",)),
    _c("toggle_detail", "tab", "Navigate", "Switch focus between the item list and the detail pane",
       "toggle_detail", priority=True, contexts=CTX_ALL),
    _c("back", "escape", "Navigate", "Leave the detail pane, or clear the filter",
       ("detail_back", "clear_filter"), contexts=CTX_ALL),
    # ---- Capture --------------------------------------------------------
    _c("quick_add", "a", "Capture",
       "Quick add: !1-!4 priority, #fix type, >todo status (enter saves, ctrl+j saves and keeps open)", "quick_add"),
    _c("add_form", "A", "Capture", "Full add form (ctrl+s saves, esc cancels)", "add_form"),
    _c("edit", "e", "Capture", "Edit the selected item in the form", "edit_form"),
    _c("edit_external", "E", "Capture", "Edit the body in $VISUAL / $EDITOR", "edit_external"),
    _c("note", "c", "Capture", "Add a note (how you reply to the agent)", "note"),
    # ---- Triage ---------------------------------------------------------
    _c("advance", "space", "Triage", "Advance to the next status (restores an item in Archived)",
       ("advance", "restore")),
    _c("retreat", "backspace", "Triage", "Move to the previous status", "retreat"),
    _c("move", "m", "Triage", "Move the item to a status (then i/t/d/r/x)", "chord('move')"),
    _c("accept", "y", "Triage", "Accept (Review only): move to Done", ("accept", "accept_hint")),
    _c("bounce", "n", "Triage", "Bounce with a reason: back to Todo, logged for the agent", "bounce"),
    _c("priority", "p", "Triage", "Set the priority (then 1-4)", "chord('priority')"),
    _c("prio_up", "plus,equals_sign", "Triage", "Raise priority (lower number)", "prio_up"),
    _c("prio_down", "minus", "Triage", "Lower priority", "prio_down"),
    _c("type_next", "t", "Triage", "Cycle the type forward", "type_next"),
    _c("type_prev", "T", "Triage", "Cycle the type backward", "type_prev"),
    _c("reorder_down", "J", "Triage", "Move the item down within its column (priority sort)", "reorder_down"),
    _c("reorder_up", "K", "Triage", "Move the item up within its column (priority sort)", "reorder_up"),
    _c("archive", "d", "Triage", "Press twice to archive (in Archived: delete, asks y/n)", "chord('archive')"),
    _c("purge", "D", "Triage", "Permanently delete (Archived tab; asks y/n)", ("purge", "purge_hint")),
    _c("undo", "u", "Triage", "Undo the last change made in this session", "undo"),
    _c("copy_handoff", "Y", "Triage", "Copy `triage show <id>` to the clipboard", "copy_handoff"),
    # ---- App ------------------------------------------------------------
    _c("settings", "comma", "App", "Settings (global or per board)", "settings"),
    _c("repos", "R", "App", "Repo picker", "repos"),
    _c("help", "question_mark", "App", "This help", "help"),
    _c("quit", "q", "App", "Quit", "quit"),
)
COMMANDS_BY_NAME = {c.name: c for c in COMMANDS}


@dataclass(frozen=True)
class Chord:
    """A two-key sequence: the command's key, then one of ``options``.

    The second keys are fixed (only the prefix is configurable). The ``archive`` chord is a
    double press: its second key is the prefix key itself.
    """

    command: str
    label: str  # "move to"
    options: tuple[tuple[str, str], ...]  # (second key, what it does); empty = press the prefix again
    help: str


CHORDS: tuple[Chord, ...] = (
    Chord("move", "move to", (("i", "inbox"), ("t", "todo"), ("d", "doing"), ("r", "review"), ("x", "done")),
          "move the item to a status"),
    Chord("priority", "priority", (("1", "urgent"), ("2", "high"), ("3", "normal"), ("4", "low")),
          "set the priority"),
    Chord("archive", "archive", (), "press twice to archive (in Archived: delete, asks y/n)"),
)
CHORDS_BY_NAME = {c.command: c for c in CHORDS}


# ---- key names ----------------------------------------------------------------

class KeyNameError(ValueError):
    pass


MODIFIERS = ("ctrl", "alt", "shift", "meta")
_MOD_ALIASES = {"control": "ctrl", "ctl": "ctrl", "option": "alt", "opt": "alt", "cmd": "meta", "super": "meta"}
_NAME_ALIASES = {
    "esc": "escape", "return": "enter", "pgup": "pageup", "pgdn": "pagedown", "pgdown": "pagedown",
    "del": "delete", "ins": "insert", "spacebar": "space", "bs": "backspace",
}
_PUNCT_NAMES = {chr(c): _character_to_key(chr(c)) for c in range(33, 127) if not chr(c).isalnum()}
_PUNCT_NAMES[" "] = "space"
_NAME_TO_CHAR = {v: k for k, v in _PUNCT_NAMES.items()}
_BASE_NAMES = (
    {k.value for k in Keys if "+" not in k.value and not k.value.startswith(("<", "ctrl-"))}
    | set(_NAME_TO_CHAR)
)

# Shown in hints and help (everything else is its Textual name, or the character for punctuation).
_DISPLAY = {"escape": "esc", "up": "↑", "down": "↓", "left": "←", "right": "→", "pageup": "PgUp",
            "pagedown": "PgDn", "home": "Home", "end": "End", "backspace": "backspace"}


def is_printable(key: str) -> bool:
    """True for keys that type a character (they must never be priority bindings)."""
    return len(key) == 1 or key in _NAME_TO_CHAR


def normalize_key(text: str) -> str:
    """Normalise one key as written by a user to its Textual name (``?`` -> ``question_mark``).

    Raises :class:`KeyNameError` for an empty or unknown key.
    """
    if text == " ":
        return "space"
    t = text.strip()
    if not t:
        raise KeyNameError("empty key")
    if len(t) == 1:
        return _character_to_key(t)
    low = t.lower()
    if low.endswith("++"):
        parts = low[:-2].split("+") + ["plus"]
    else:
        parts = low.split("+")
    if any(not p for p in parts):
        raise KeyNameError(f"unknown key {text!r}")
    mods: list[str] = []
    for m in parts[:-1]:
        m = _MOD_ALIASES.get(m, m)
        if m not in MODIFIERS:
            raise KeyNameError(f"unknown key {text!r}")
        if m not in mods:
            mods.append(m)
    base = _NAME_ALIASES.get(parts[-1], parts[-1])
    if len(base) == 1:
        base = _character_to_key(base)
    elif base not in _BASE_NAMES:
        raise KeyNameError(f"unknown key {text!r}")
    if mods == ["shift"] and len(base) == 1 and base.isalpha():
        return base.upper()  # Textual reports shift+d as "D"
    return "+".join([*sorted(mods, key=MODIFIERS.index), base])


def _map_base(key: str, table: dict[str, str]) -> str:
    head, sep, base = key.rpartition("+")
    return head + sep + table.get(base, base)


def display_key(key: str) -> str:
    """How a Textual key name is written in hints and help (``question_mark`` -> ``?``)."""
    return _map_base(key, {**{n: c for n, c in _NAME_TO_CHAR.items() if n != "space"}, **_DISPLAY})


def config_key(key: str) -> str:
    """How a key is written in ``config.toml``: the character for common punctuation, else its name."""
    literal = {n: c for n, c in _NAME_TO_CHAR.items() if c in "?/+-=" and n != "comma"}
    return _map_base(key, literal)


def parse_keys(raw: Any) -> tuple[str, ...]:
    """Parse a ``[keys]`` value: ``"j, down"`` or ``["j", "down"]``. A lone ``","`` is the comma key."""
    if isinstance(raw, str):
        s = raw.strip()
        tokens = ["comma"] if s == "," else [p for p in (x.strip() for x in s.split(",")) if p]
    elif isinstance(raw, list):
        if not all(isinstance(x, str) for x in raw):
            raise KeyNameError("keys must be text")
        tokens = [x for x in raw if x.strip()]
    else:
        raise KeyNameError("keys must be text such as \"j, down\"")
    if not tokens:
        raise KeyNameError("no keys given")
    out: list[str] = []
    for tok in tokens:
        k = normalize_key(tok)
        if k not in out:
            out.append(k)
    return tuple(out)


# ---- effective keymap ----------------------------------------------------------

@dataclass(frozen=True)
class Problem:
    command: str
    message: str
    unknown: bool = False  # not a command at all (as opposed to a command that fell back to its default)
    whole_file: bool = False  # the whole [keys] table (or file) was unusable


@dataclass
class Keymap:
    """The effective keys (defaults overlaid with ``[keys]``) plus what was wrong with the config."""

    keys: dict[str, tuple[str, ...]]
    problems: list[Problem] = field(default_factory=list)
    user_set: frozenset[str] = frozenset()  # commands whose keys come from the config
    source: str = "config.toml"

    def keys_for(self, name: str) -> tuple[str, ...]:
        return self.keys[name]

    def first(self, name: str) -> str:
        """The primary key of a command as shown in hints (``d`` for archive, written ``dd``)."""
        shown = display_key(self.keys[name][0])
        return shown + shown if name == "archive" else shown

    def display(self, name: str) -> str:
        """All keys of a command for the help screen: ``j/↓``."""
        return "/".join(display_key(k) for k in self.keys[name])

    def config_value(self, name: str) -> str:
        return ", ".join(config_key(k) for k in self.keys[name])

    def warning(self) -> str | None:
        """One line for the message bar, or None when the config is fine."""
        if not self.problems:
            return None
        whole = next((p for p in self.problems if p.whole_file), None)
        if whole is not None:
            return f"keys: {whole.message} — default keys used (see triage config keys)"
        n = len(self.problems)
        fell_back = list(dict.fromkeys(p.command for p in self.problems if not p.unknown))
        unknown = list(dict.fromkeys(p.command for p in self.problems if p.unknown))
        parts = []
        if fell_back:
            parts.append("default used for " + ", ".join(fell_back))
        if unknown:
            parts.append("ignored unknown " + ", ".join(unknown))
        return f"keys: {n} problem{'s' if n != 1 else ''} in {self.source} — {'; '.join(parts)} (see triage config keys)"


def default_keymap() -> Keymap:
    return Keymap({c.name: c.keys for c in COMMANDS})


def find_conflicts(effective: dict[str, tuple[str, ...]], commands: Iterable[Command] = COMMANDS) -> dict[str, set[str]]:
    """``{key: {command names}}`` for every key bound to two commands whose contexts overlap."""
    by_key: dict[str, list[Command]] = {}
    for c in commands:
        for k in effective[c.name]:
            by_key.setdefault(k, []).append(c)
    out: dict[str, set[str]] = {}
    for k, cmds in by_key.items():
        for i, a in enumerate(cmds):
            for b in cmds[i + 1:]:
                if a.name != b.name and set(a.contexts) & set(b.contexts):
                    out.setdefault(k, set()).update((a.name, b.name))
    return out


def build_keymap(user: Any = None, commands: tuple[Command, ...] = COMMANDS, source: str = "config.toml") -> Keymap:
    """Overlay the ``[keys]`` table ``user`` on the defaults. Never raises: bad entries fall back."""
    by_name = {c.name: c for c in commands}
    effective = {c.name: c.keys for c in commands}
    problems: list[Problem] = []
    chosen: dict[str, tuple[str, ...]] = {}
    if user is not None and not isinstance(user, dict):
        problems.append(Problem("keys", "[keys] must be a table of command = \"keys\"", whole_file=True))
        user = {}
    for name, raw in (user or {}).items():
        if name not in by_name:
            problems.append(Problem(str(name), f"unknown command {name!r}", unknown=True))
            continue
        try:
            chosen[name] = parse_keys(raw)
        except KeyNameError as exc:
            problems.append(Problem(name, f"{name}: {exc}"))
    effective.update(chosen)
    while True:
        conflicts = find_conflicts(effective, commands)
        bad = {n for names in conflicts.values() for n in names if n in chosen}
        if not bad:
            break
        for key, names in conflicts.items():
            for n in sorted(names & bad):
                others = ", ".join(sorted(names - {n}))
                problems.append(Problem(n, f"{n}: {display_key(key)} is also bound to {others}"))
        for n in bad:
            del chosen[n]
            effective[n] = by_name[n].keys
    return Keymap(effective, problems, frozenset(chosen), source)


def load_keymap() -> Keymap:
    """The keymap from the user's config. Never raises."""
    from .. import config

    source = config.config_path().name
    try:
        table = config.keys_table()
    except config.ConfigError as exc:
        why = "is not valid TOML" if "invalid TOML" in str(exc) else "could not be read (is it saved as UTF-8?)"
        return Keymap({c.name: c.keys for c in COMMANDS},
                      [Problem("keys", f"{source} {why}", whole_file=True)], frozenset(), source)
    except Exception:  # never let a broken config stop the TUI from starting
        return Keymap({c.name: c.keys for c in COMMANDS},
                      [Problem("keys", f"{source} could not be read", whole_file=True)], frozenset(), source)
    except OSError:
        table = None
    return build_keymap(table, source=source)


# ---- Textual bindings ------------------------------------------------------------

def bindings(keymap: Keymap | None = None) -> list[Binding]:
    """The app's bindings for ``keymap`` (default keys when omitted), one per key and action."""
    km = keymap or default_keymap()
    out: list[Binding] = []
    for c in COMMANDS:
        for key in km.keys_for(c.name):
            for action in c.actions:
                # a printable key as a priority binding would steal typing from the filter box
                out.append(Binding(key, action, c.desc, show=False, priority=c.priority and not is_printable(key)))
    return out


# ---- the key-hint bar -------------------------------------------------------------

@dataclass(frozen=True)
class Hint:
    commands: tuple[str, ...]  # key text = the primary key of each, joined with "/"
    label: str  # may contain "{dest}"
    needs: str = ""  # "" always, "undo" only with something to undo, "dest" only when space can advance
    key: str = ""  # literal key text instead of commands (keys that are not commands)


def _h(commands, label, needs="", key="") -> Hint:
    return Hint((commands,) if isinstance(commands, str) else tuple(commands), label, needs, key)


_ITEM_HINTS = (
    _h("edit", "edit"), _h("note", "note"), _h("advance", "→ {dest}", "dest"), _h("move", "move"),
    _h("priority", "priority"), _h("toggle_detail", "detail"), _h("archive", "archive"),
    _h("undo", "undo", "undo"), _h("help", "help"),
)

# context -> hints, most relevant first. The help hint is never dropped when the bar is truncated.
HINT_CONTEXTS: dict[str, tuple[Hint, ...]] = {
    "empty": (
        _h("quick_add", "add"), _h("add_form", "add form"), _h(("tab_prev", "tab_next"), "tabs"),
        _h("filter", "find"), _h("help", "help"), _h("quit", "quit"),
    ),
    "noboard": (_h("repos", "pick a repo"), _h("help", "help"), _h("quit", "quit")),
    "item": _ITEM_HINTS,
    "review": (_h("accept", "accept"), _h("bounce", "bounce")) + _ITEM_HINTS,
    "archived": (
        _h("advance", "restore"), _h("purge", "delete"), _h("undo", "undo", "undo"),
        _h(("cursor_down", "cursor_up"), "move"), _h(("tab_prev", "tab_next"), "tabs"),
        _h("filter", "find"), _h("help", "help"), _h("quit", "quit"),
    ),
    "detail": (
        _h(("cursor_down", "cursor_up"), "scroll"), _h(("toggle_detail", "back"), "back to list"),
        _h("edit", "edit"), _h("note", "note"), _h("help", "help"),
    ),
    # typing in the filter box: `?` and `q` are just characters there, so no help/quit hints
    "filter": (_h((), "keep", key="enter"), _h("back", "clear filter")),
}
LIST_CONTEXTS = ("empty", "item", "review", "archived")


def hint_entries(
    context: str, keymap: Keymap, *, dest: str | None = None, can_undo: bool = False, filter_active: bool = False,
) -> list[tuple[str, str]]:
    """``(key text, label)`` pairs for a context, using the effective keys."""
    hints = HINT_CONTEXTS[context]
    if filter_active and context in LIST_CONTEXTS:
        hints = (_h("back", "clear filter"), *hints)
    out: list[tuple[str, str]] = []
    for h in hints:
        if h.needs == "undo" and not can_undo:
            continue
        if h.needs == "dest" and not dest:
            continue
        if h.key:
            key = h.key
        elif context == "filter":
            usable = [k for c in h.commands for k in keymap.keys[c] if not is_printable(k)]
            if not usable:
                continue  # every key of this command would just type a character here
            key = display_key(usable[0])
        else:
            key = "/".join(keymap.first(c) for c in h.commands)
        out.append((key, h.label.format(dest=dest or "")))
    return out


def fit_hints(entries: list[tuple[str, str]], width: int) -> tuple[list[tuple[str, str]], str]:
    """Drop entries from the end until the bar fits ``width`` cells; ``help`` is never dropped.

    Returns the kept entries and the separator to use (two spaces, or one when that avoids dropping).
    """

    def cells(es: list[tuple[str, str]], sep: str) -> int:
        return sum(len(k) + 1 + len(label) for k, label in es) + len(sep) * max(0, len(es) - 1)

    es = list(entries)
    for sep in ("  ", " "):  # prefer airy spacing, but squeeze before dropping anything
        if cells(es, sep) <= width:
            return es, sep
    sep = "  "
    while cells(es, sep) > width:
        drop = [i for i in range(len(es) - 1, -1, -1) if es[i][1] != "help"]
        if len(es) <= 1 or not drop:
            break
        del es[drop[0]]
    return es, sep


# ---- help screen ----------------------------------------------------------------

ROW_HELP = {
    "tabs": "jump to Inbox / Todo / Doing / Review / Done",
    "sort": "sort by priority / last activity / newest / oldest / title (forward / back)",
}


def _compress(keys: list[str]) -> str:
    if len(keys) > 2 and all(k.isdigit() and len(k) == 1 for k in keys) and \
            all(int(b) - int(a) == 1 for a, b in zip(keys, keys[1:])):
        return f"{keys[0]}-{keys[-1]}"
    return "/".join(keys)


def help_sections(keymap: Keymap | None = None) -> list[tuple[str, list[tuple[str, str]]]]:
    """Grouped ``(key label, description)`` rows for the help screen, from the effective keys."""
    km = keymap or default_keymap()
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    for group in GROUPS:
        out: list[tuple[str, str]] = []
        seen_rows: set[str] = set()
        for c in COMMANDS:
            if c.group != group:
                continue
            if c.row:
                if c.row in seen_rows:
                    continue
                seen_rows.add(c.row)
                firsts = [display_key(km.keys_for(x.name)[0]) for x in COMMANDS if x.row == c.row]
                out.append((_compress(firsts), ROW_HELP[c.row]))
            elif c.name in CHORDS_BY_NAME:
                ch = CHORDS_BY_NAME[c.name]
                first = display_key(km.keys_for(c.name)[0])
                if ch.options:
                    opts = " ".join(f"{k} {v}" for k, v in ch.options)
                    out.append((f"{first} …", f"{ch.help}: {opts}"))
                else:
                    out.append((f"{first} {first}", ch.help))
            else:
                out.append((km.display(c.name), c.desc))
        sections.append((group, out))
    return sections


def chord_prompt(chord: Chord, keymap: Keymap | None = None) -> str:
    if not chord.options:
        key = display_key((keymap or default_keymap()).keys_for(chord.command)[0])
        return f"press {key} again to {chord.label} · esc cancels"
    opts = " · ".join(f"{key} {name}" for key, name in chord.options)
    return f"{chord.label}: {opts}"


# ---- generated config ---------------------------------------------------------------

def default_keys_toml() -> str:
    """The complete ``[keys]`` table (every command, its default keys and a comment) as TOML text."""
    km = default_keymap()
    lines = [
        "# ---- keybindings ------------------------------------------------------------",
        "# command = \"key1, key2\": a Textual key name (ctrl+d, down, shift+tab, f5, question_mark)",
        "# or a literal character (? / + - = space). Write the comma key as `comma`.",
        "# One key may not be bound to two commands; an invalid entry falls back to its default",
        "# (the TUI shows a warning). Changes apply the next time the TUI starts.",
        "# Two-key commands (move, priority, archive) only change their first key; the second",
        "# keys stay fixed (archive is that key pressed twice).",
        "# See the effective keys with `triage config keys`.",
        "[keys]",
    ]
    group = ""
    for c in COMMANDS:
        if c.group != group:
            group = c.group
            lines += ["", f"# {group}"]
        lines.append(f"# {c.desc}")
        lines.append(f'{c.name} = "{km.config_value(c.name)}"')
    return "\n".join(lines) + "\n"
