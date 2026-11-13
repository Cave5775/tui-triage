"""The triage board TUI.

Every mutation goes through ``triage.ops`` with ``actor="user"`` and every render starts
from a fresh ``store.load()``; the app never writes board or config files itself.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding, BindingsMap
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Input, OptionList, Static

from .. import config, ops
from ..model import FLOW, TYPES, Board, Item
from ..paths import RepoNotFound, RepoRef, resolve_repo
from ..store import BoardStore, LockTimeout, touch_registry
from . import keys
from .quickadd import QuickAddScreen
from .screens import ConfirmScreen, HelpScreen, ItemFormScreen, PromptScreen, RepoPickerScreen, SettingsScreen
from .widgets import (
    TAB_IDS,
    TAB_LABELS,
    DetailPane,
    ItemList,
    KeyHints,
    palette,
    render_tabs,
    tab_statuses,
)

OP_ERRORS = (ops.TriageError, ValueError, LockTimeout, OSError)
CHORD_SECONDS = 1.0  # the second `d` of `d d` must follow within this long
FLASH_SECONDS = 2.0
MESSAGE_SECONDS = 8.0

STATUS_KEYS = {"i": "inbox", "t": "todo", "d": "doing", "r": "review", "x": "done"}


# ---- helpers (module level so they can be tested without a running app) ------

def resolve_editor() -> list[str]:
    """``$VISUAL`` / ``$EDITOR`` as an argv list; ``notepad`` on Windows, ``vi`` elsewhere."""
    raw = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("notepad" if sys.platform == "win32" else "vi")
    try:
        parts = shlex.split(raw, posix=sys.platform != "win32")
    except ValueError:
        parts = [raw]
    return [p[1:-1] if len(p) > 1 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts] or ["vi"]


def edit_text_externally(text: str, name: str = "triage-edit", run=subprocess.run) -> str:
    """Round-trip ``text`` through the user's editor using a temp file outside any repo."""
    fd, tmp = tempfile.mkstemp(prefix=f"{name}-", suffix=".md")
    path = Path(tmp)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    try:
        argv = resolve_editor()
        exe = shutil.which(argv[0])
        if exe is None:
            raise FileNotFoundError(f"editor not found: {argv[0]} (set $VISUAL or $EDITOR)")
        run([exe, *argv[1:], str(path)], check=False)
        return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    finally:
        path.unlink(missing_ok=True)


def copy_to_system_clipboard(text: str) -> None:
    """Windows terminals often ignore OSC 52, so also pipe to ``clip.exe``."""
    if sys.platform == "win32":
        subprocess.run(["clip"], input=text.encode("utf-8"), check=False, timeout=5, capture_output=True)


# ---- terminal driver ---------------------------------------------------------

KITTY_KEYS_ON = "\x1b[>1u"
KITTY_KEYS_OFF = "\x1b[<u"


def without_kitty_keyboard(driver_class: type) -> type:
    """Wrap a Textual driver so it never asks the terminal for the kitty keyboard protocol.

    On Windows, Textual writes ``ESC[>1u`` at startup. ConPTY passes it through to the
    terminal (Windows Terminal, Alacritty, Terax, VS Code, ...); a terminal that honours it
    then encodes Esc, Alt- and Shift-modified keys as CSI-u sequences, which the Windows 10
    ConPTY input layer cannot translate back into key events. Result: Esc / Alt keys are
    dead and you cannot cancel or quit. Without the request, terminals keep sending
    classic keys, which work everywhere.
    """

    class NoKittyKeyboardDriver(driver_class):  # type: ignore[misc, valid-type]
        def write(self, data: str) -> None:
            data = data.replace(KITTY_KEYS_ON, "").replace(KITTY_KEYS_OFF, "")
            if data:
                super().write(data)

    NoKittyKeyboardDriver.__name__ = f"NoKitty{driver_class.__name__}"
    return NoKittyKeyboardDriver


def kitty_keyboard_wanted() -> bool:
    """Off on Windows unless TRIAGE_KITTY_KEYS=1; elsewhere Textual's default (on)."""
    flag = os.environ.get("TRIAGE_KITTY_KEYS", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    return sys.platform != "win32"


# ---- app ---------------------------------------------------------------------

class TriageApp(App[None]):
    CSS_PATH = "app.tcss"
    TITLE = "triage"
    ENABLE_COMMAND_PALETTE = False
    # No class-level BINDINGS: Textual collects those once per class, but the keys are configurable.
    # The effective bindings are added per instance in __init__ (the App's own defaults stay).

    def get_driver_class(self):  # type: ignore[override]
        driver_class = super().get_driver_class()
        return driver_class if kitty_keyboard_wanted() else without_kitty_keyboard(driver_class)

    def __init__(self, store: BoardStore | None = None, keymap: keys.Keymap | None = None) -> None:
        super().__init__()
        self.keymap: keys.Keymap = keymap if keymap is not None else keys.load_keymap()
        extra = []
        if not any("shift+tab" in ks for ks in self.keymap.keys.values()):
            # Textual's screen default would make shift+tab a hidden second toggle; tab alone
            # switches panes (triage #7), so swallow it on the main screen (modals keep it).
            extra.append(Binding("shift+tab", "swallow_key", show=False, priority=True))
        self._bindings = BindingsMap.merge(
            [self._bindings, BindingsMap(keys.bindings(self.keymap)), BindingsMap(extra)]
        )
        self.store: BoardStore | None = None
        self._initial_store = store
        self._main_screen = None  # the default screen that holds the board UI (modals are pushed over it)
        self.board: Board | None = None
        self.cfg: dict = dict(config.DEFAULTS)
        self.tab = "inbox"
        self.filter_text = ""
        self.undo_stack: list[ops.Change] = []
        self._chord: tuple[str, float | None] | None = None
        self._flash: set[int] = set()
        self._token = None
        self._config_token = None
        self._poll_timer: Timer | None = None
        self._message_timer: Timer | None = None
        self._flash_timer: Timer | None = None
        self.message = ""

    # ---- layout -----------------------------------------------------------
    def compose(self) -> ComposeResult:
        with Vertical(id="topbar"):
            yield Static("triage", id="repo")
            yield Static(id="tabs")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Input(placeholder="filter title / body", id="filter", compact=True)
                yield ItemList(id="items")
            yield DetailPane(id="detail")
        yield Static(id="message")
        yield KeyHints(id="hints")

    def _q(self, selector: str, cls=None):
        """Query the board UI even while a modal screen is on top (``App.query`` only sees the top screen)."""
        return self._main_screen.query_one(selector, cls) if cls else self._main_screen.query_one(selector)

    @property
    def items_view(self) -> ItemList:
        return self._q("#items", ItemList)

    @property
    def detail(self) -> DetailPane:
        return self._q("#detail", DetailPane)

    @property
    def filter_input(self) -> Input:
        return self._q("#filter", Input)

    def on_mount(self) -> None:
        self._main_screen = self.screen
        self._q("#filter").display = False
        self._q("#left").border_title = ""
        self.items_view.focus()
        if self._initial_store is not None:
            self._attach(self._initial_store)
        else:
            self.render_all()
            self.say(f"no repository here — pick one ({self.keymap.first('repos')}) or type a path")
            self.push_screen(RepoPickerScreen(), self._picked)
        warning = self.keymap.warning()
        if warning:
            self.say(warning, error=True)

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self.render_all)

    def watch_theme(self, theme: str) -> None:
        self.call_after_refresh(self.render_all)

    # ---- board lifecycle --------------------------------------------------
    def _attach(self, store: BoardStore) -> None:
        self.store = store
        self.board = None
        self.undo_stack.clear()
        self._chord = None
        self._flash.clear()
        self._token = None
        try:
            touch_registry(store.ref, opened=True)
        except (OSError, LockTimeout) as exc:
            self.say(f"could not update the repo list: {exc}", error=True)
        self.sub_title = store.ref.name
        self.refresh_config()
        self.reload()

    def refresh_config(self) -> None:
        """Re-read the effective config (and re-arm the poll timer if it changed)."""
        try:
            self.cfg = ops.config_for(self.store) if self.store else dict(config.DEFAULTS)
        except config.ConfigError as exc:
            self.say(str(exc), error=True)
        try:
            self._config_token = config.config_path().stat().st_mtime_ns
        except OSError:
            self._config_token = None
        interval = float(self.cfg.get("ui.poll_seconds", 1.0))
        if self._poll_timer is None or getattr(self._poll_timer, "_triage_interval", None) != interval:
            if self._poll_timer is not None:
                self._poll_timer.stop()
            self._poll_timer = self.set_interval(interval, self._poll)
            self._poll_timer._triage_interval = interval  # type: ignore[attr-defined]

    def _on_config_changed(self) -> None:
        self.refresh_config()
        self.render_all()

    def _poll(self) -> None:
        if self.store is None:
            return
        try:
            cfg_token = config.config_path().stat().st_mtime_ns
        except OSError:
            cfg_token = None
        if cfg_token != self._config_token:
            self.refresh_config()
        if self.store.stat_token() != self._token:
            self.reload(external=True)

    def reload(self, select_id: int | None = None, external: bool = False) -> None:
        """Re-read the board from disk and re-render, keeping selection and scroll."""
        if self.store is None:
            return
        token = self.store.stat_token()
        try:
            board = self.store.load()
        except Exception as exc:  # half-written, locked or malformed file: never crash the poll timer
            self.say(f"could not read the board: {exc}", error=True)
            return
        old, self.board = self.board, board
        self._token = token
        if old is not None:
            self._note_agent_changes(old, board)
        self.render_all(select_id)

    def _note_agent_changes(self, old: Board, new: Board) -> None:
        changed = []
        for it in new.items:
            before = old.get(it.id)
            # compare the agent's own markers, not the whole item: a user reorder rewrites other items' ranks
            if it.updated_by == "agent" and (
                before is None or before.updated_by != "agent"
                or before.updated_at != it.updated_at or len(before.log) != len(it.log)
            ):
                changed.append(it.id)
        if not changed:
            return
        self._flash.update(changed)
        if self._flash_timer is not None:
            self._flash_timer.stop()
        self._flash_timer = self.set_timer(FLASH_SECONDS, self._end_flash)
        refs = ", ".join(f"#{i}" for i in changed[:4]) + (f" +{len(changed) - 4}" if len(changed) > 4 else "")
        self.say(f"agent updated {refs}")

    def _end_flash(self) -> None:
        self._flash.clear()
        self.render_all()

    # ---- rendering --------------------------------------------------------
    def visible_items(self) -> list[Item]:
        if self.board is None:
            return []
        items = self.board.sorted_items(tab_statuses(self.tab))
        q = self.filter_text.strip().lower()
        if q:
            items = [i for i in items if q in i.title.lower() or q in i.body.lower()]
        return items

    def current_item(self) -> Item | None:
        if self.board is None:
            return None
        try:
            sel = self.items_view.selected_id
        except Exception:
            return None
        return self.board.get(sel) if sel is not None else None

    def render_all(self, select_id: int | None = None, reset: bool = False) -> None:
        if not self.is_attached_ui():
            return
        pal = palette(self)
        name = self.board.repo_name if self.board else (self.store.ref.name if self.store else "no repo")
        where = Text(f" {name} ", style=f"bold {pal['primary']}")
        if self.board is not None and self.board.repo_path:
            where.append(f" {self.board.repo_path}", style="dim")
        self._q("#repo", Static).update(where)
        counts = self.board.counts() if self.board else {}
        tabs = self._q("#tabs", Static)
        tabs.update(render_tabs(counts, self.tab, max(20, tabs.size.width or self.size.width), pal))
        items = self.visible_items()
        total = len(self.board.sorted_items(tab_statuses(self.tab))) if self.board else 0
        km = self.keymap
        empty = f"no board open — press {km.first('repos')}" if self.board is None else (
            "no matches" if self.filter_text else f"no {TAB_LABELS[self.tab].lower()} items"
            + (f" — press {km.first('quick_add')} to add" if self.tab != "archived" else ""))
        self.items_view.set_items(items, pal, self.tab in ("all", "archived"), self._flash, select_id, empty, reset)
        title = TAB_LABELS[self.tab] + (f" · {len(items)}/{total}" if self.filter_text else f" · {total}")
        self._q("#left").border_title = title
        self.update_detail()
        self.refresh_bindings()
        self.update_hints()

    def is_attached_ui(self) -> bool:
        return self._main_screen is not None

    def update_detail(self) -> None:
        self.detail.show(self.current_item(), palette(self), self.keymap.first("edit"))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "items":
            self.update_detail()
            self.refresh_bindings()
            self.update_hints()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        self.update_hints()

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        self.update_hints()

    # ---- messages ---------------------------------------------------------
    def say(self, text: str, error: bool = False, sticky: bool = False) -> None:
        self.message = text
        if self._main_screen is None:
            return
        area = self._q("#message", Static)
        area.set_class(error, "-error")
        area.update(Text(text))
        if self._message_timer is not None:
            self._message_timer.stop()
            self._message_timer = None
        if text and not sticky and not error:
            self._message_timer = self.set_timer(MESSAGE_SECONDS, lambda: self.say(""))

    # ---- key hints ---------------------------------------------------------
    def hint_context(self) -> str:
        """Which key-hint list applies: empty / item / review / archived / detail / filter."""
        focused = self.focused
        if focused is not None and focused is self.filter_input:
            return "filter"
        if focused is not None and focused is self.detail:
            return "detail"
        if self.store is None:
            return "noboard"
        item = self.current_item()
        if item is None:
            return "empty"
        if self.tab == "archived" or item.status == "archived":
            return "archived"
        return "review" if item.status == "review" else "item"

    def hint_entries(self) -> list[tuple[str, str]]:
        item = self.current_item()
        dest = None
        if item is not None and item.status in FLOW and item.status != FLOW[-1]:
            dest = FLOW[FLOW.index(item.status) + 1]
        return keys.hint_entries(
            self.hint_context(), self.keymap, dest=dest, can_undo=bool(self.undo_stack),
            filter_active=bool(self.filter_text.strip()),
        )

    def update_hints(self) -> None:
        if not self.is_attached_ui():
            return
        try:
            self._q("#hints", KeyHints).set_entries(self.hint_entries())
        except Exception:  # never let the hint bar break a key press
            pass

    # ---- action state ------------------------------------------------------
    def check_action(self, action: str, parameters: tuple) -> bool | None:
        main = not isinstance(self.screen, ModalScreen)
        if action in ("toggle_detail", "swallow_key"):
            return main  # priority bindings (tab, shift+tab): keep them out of modals, whose forms use them
        if not main:
            return True
        if action == "advance":
            return self.tab != "archived"
        if action == "restore":
            return self.tab == "archived"
        if action == "purge":
            return self.tab == "archived"
        if action == "purge_hint":
            return self.tab != "archived"
        if action in ("accept", "accept_hint"):
            item = self.current_item()
            in_review = bool(item and item.status == "review")
            return in_review if action == "accept" else not in_review
        if action == "detail_back":
            return self.focused is self.detail
        if action == "clear_filter":
            return bool(self.filter_text) or self.focused is self.filter_input
        return True

    # ---- chords -----------------------------------------------------------
    async def on_event(self, event: events.Event) -> None:
        if isinstance(event, events.Key) and self._chord is not None and not isinstance(self.screen, ModalScreen):
            if self._chord_key(event):
                event.stop()
                return
        await super().on_event(event)

    def action_chord(self, name: str) -> None:
        item = self._need_item()
        if item is None:
            return
        chord = keys.CHORDS_BY_NAME[name]
        deadline = time.monotonic() + CHORD_SECONDS if not chord.options else None  # a double press has a time limit
        self._chord = (name, deadline)
        self.say(keys.chord_prompt(chord, self.keymap), sticky=True)
        if deadline is not None:
            self.set_timer(CHORD_SECONDS, self._expire_chord)

    def _expire_chord(self) -> None:
        if self._chord and self._chord[1] is not None and time.monotonic() >= self._chord[1]:
            self._chord = None
            self.say("")

    def _chord_key(self, event: events.Key) -> bool:
        """Handle the second key of a pending chord. Returns True when the key was consumed."""
        name, deadline = self._chord  # type: ignore[misc]
        self._chord = None
        self.say("")
        if event.key == "escape":
            self.say("cancelled")
            return True
        if deadline is not None and time.monotonic() > deadline:
            return False  # too late: treat as a normal key
        chord = keys.CHORDS_BY_NAME[name]
        if not chord.options:  # a double press: the same key again
            if event.key in self.keymap.keys_for(name):
                self._run_chord(name, event.key)
                return True
            return False  # the prefix then something else: just a normal key press
        if event.key in dict(chord.options):
            self._run_chord(name, event.key)
            return True
        self.say("cancelled")
        return True

    def _run_chord(self, name: str, key: str) -> None:
        item = self._need_item()
        if item is None:
            return
        if name == "move":
            self._op(ops.set_status, item.id, STATUS_KEYS[key], what=f"moved {item.ref} to {STATUS_KEYS[key]}")
        elif name == "priority":
            self._op(ops.update, item.id, priority=int(key), what=f"{item.ref} priority P{key}")
        elif name == "archive":
            self._archive_or_purge(item)

    # ---- operations -------------------------------------------------------
    def _need_item(self) -> Item | None:
        if self.store is None:
            self.say(f"no board open — press {self.keymap.first('repos')} to pick a repo", error=True)
            return None
        item = self.current_item()
        if item is None:
            self.say("no item selected", error=True)
        return item

    def _op(self, fn, *args, what: str = "", undoable: bool = True, select: int | None = None, **kw) -> ops.Change | None:
        """Run one ``ops`` call as the user, then re-render from a fresh load."""
        if self.store is None:
            self.say(f"no board open — press {self.keymap.first('repos')} to pick a repo", error=True)
            return None
        try:
            change = fn(self.store, *args, actor="user", **kw)
        except OP_ERRORS as exc:
            self.say(str(exc), error=True)
            self.reload()
            return None
        if undoable and change.changed:
            self.undo_stack.append(change)
        target = select if select is not None else (change.item.id if change.item else None)
        self.reload(select_id=target)
        if what:
            self.say(what + (f" — {self.keymap.first('undo')} to undo" if undoable and change.changed else ""))
        return change

    def action_advance(self) -> None:
        item = self._need_item()
        if item:
            self._op(ops.advance, item.id, step=1, what=f"{item.ref} advanced")

    def action_retreat(self) -> None:
        item = self._need_item()
        if item:
            self._op(ops.advance, item.id, step=-1, what=f"{item.ref} moved back")

    def action_restore(self) -> None:
        item = self._need_item()
        if item:
            self._op(ops.set_status, item.id, "inbox", what=f"restored {item.ref} to inbox")

    def action_accept(self) -> None:
        item = self._need_item()
        if item:
            self._op(ops.accept, item.id, what=f"accepted {item.ref}")

    def action_accept_hint(self) -> None:
        if self._need_item():
            self.say(f"{self.keymap.first('accept')} accepts items in Review — this one is not there", error=True)

    def action_bounce(self) -> None:
        item = self._need_item()
        if item is None:
            return
        if item.status not in ("review", "done"):
            self.say(f"{self.keymap.first('bounce')} bounces items from Review or Done back to Todo", error=True)
            return

        def done(reason: str | None) -> None:
            if reason is not None:
                self._op(ops.bounce, item.id, reason, what=f"bounced {item.ref} to todo")

        self.push_screen(PromptScreen(f"bounce {item.ref} — reason for the agent (optional)", allow_empty=True,
                                      placeholder="what needs to change?"), done)

    def _step_priority(self, step: int) -> None:
        item = self._need_item()
        if item is None:
            return
        new = item.priority + step
        if not 1 <= new <= 4:
            self.say(f"{item.ref} is already {'urgent (P1)' if step < 0 else 'lowest (P4)'}")
            return
        self._op(ops.update, item.id, priority=new, what=f"{item.ref} priority P{new}")

    def action_prio_up(self) -> None:
        self._step_priority(-1)

    def action_prio_down(self) -> None:
        self._step_priority(1)

    def _cycle_type(self, step: int) -> None:
        item = self._need_item()
        if item:
            new = TYPES[(TYPES.index(item.type) + step) % len(TYPES)]
            self._op(ops.update, item.id, type=new, what=f"{item.ref} type {new}")

    def action_type_next(self) -> None:
        self._cycle_type(1)

    def action_type_prev(self) -> None:
        self._cycle_type(-1)

    def _reorder(self, delta: int) -> None:
        item = self._need_item()
        if item is None:
            return
        change = self._op(ops.reorder, item.id, delta, select=item.id)
        if change is not None and not change.changed:
            self.say(f"{item.ref} is already at the {'bottom' if delta > 0 else 'top'}")
        elif change is not None:
            moved = change.after.priority != change.before.priority
            self.say(f"moved {item.ref} {'down' if delta > 0 else 'up'}" + (f" (now P{change.after.priority})" if moved else ""))

    def action_reorder_down(self) -> None:
        self._reorder(1)

    def action_reorder_up(self) -> None:
        self._reorder(-1)

    def _archive_or_purge(self, item: Item) -> None:
        if item.status == "archived":
            self._purge(item)
        else:
            self._op(ops.archive, item.id, what=f"archived {item.ref}")

    def action_purge(self) -> None:
        item = self._need_item()
        if item:
            self._purge(item)

    def action_purge_hint(self) -> None:
        if self._need_item():
            self.say(f"{self.keymap.first('purge')} deletes permanently and only works in the Archived tab "
                     f"({self.keymap.first('tab_archived')}); use {self.keymap.first('archive')} to archive", error=True)

    def _purge(self, item: Item) -> None:
        def go() -> None:
            self._op(ops.purge, item.id, what=f"deleted {item.ref}")

        if self.cfg.get("ui.confirm_delete", True):
            def answered(yes: bool | None) -> None:
                if yes:
                    go()

            self.push_screen(ConfirmScreen(f"Permanently delete {item.ref} “{item.title}”?"), answered)
        else:
            go()

    def action_undo(self) -> None:
        if self.store is None:
            return
        if not self.undo_stack:
            self.say("nothing to undo")
            return
        change = self.undo_stack[-1]
        try:
            result = ops.revert(self.store, change, actor="user")
        except (LockTimeout, OSError) as exc:  # transient: keep the entry so u can retry
            self.say(f"cannot undo right now: {exc}", error=True)
            return
        except OP_ERRORS as exc:
            self.undo_stack.pop()
            self.say(f"cannot undo: {exc}", error=True)
            self.reload()
            return
        self.undo_stack.pop()
        item = change.item
        self.reload(select_id=item.id if result.after is not None else None)
        self.say(f"undid: {change.op} {item.ref}")

    def action_copy_handoff(self) -> None:
        item = self._need_item()
        if item is None:
            return
        text = f"triage show {item.id}"
        ok = False
        try:
            self.copy_to_clipboard(text)
            ok = True
        except Exception:
            pass
        try:
            copy_to_system_clipboard(text)
            ok = True
        except (OSError, subprocess.SubprocessError):
            pass
        self.say(f"copied: {text}" if ok else f"could not copy; run: {text}", error=not ok)

    # ---- capture ----------------------------------------------------------
    def new_item_status(self) -> str:
        return self.tab if self.tab in ("inbox", "todo") else self.cfg.get("ui.new_item_status", "inbox")

    def _add(self, title: str, *, type: str | None, priority: int | None, status: str | None, body: str = "") -> str | None:
        """Create an item. Returns an error message, or None on success."""
        if self.store is None:
            return "no board open"
        status = status or self.new_item_status()
        change = self._op(ops.add, title, body=body, type=type or "feature", priority=priority or 3, status=status)
        if change is None:
            return self.message or "could not add"
        where = "" if status == self.tab or self.tab == "all" else f" → {status}"
        self.say(f"added {change.item.ref}{where} — {self.keymap.first('undo')} to undo")
        return None

    def action_quick_add(self) -> None:
        if self.store is None:
            self.say(f"no board open — press {self.keymap.first('repos')} to pick a repo", error=True)
            return

        def save(parsed: dict) -> str | None:
            return self._add(parsed["title"], type=parsed["type"], priority=parsed["priority"], status=parsed["status"])

        self.push_screen(QuickAddScreen(save, self.new_item_status()))

    def action_add_form(self) -> None:
        if self.store is None:
            self.say(f"no board open — press {self.keymap.first('repos')} to pick a repo", error=True)
            return

        def save(v: dict) -> str | None:
            if not v["title"].strip():
                return "title must not be empty"
            return self._add(v["title"], type=v["type"], priority=v["priority"], status=None, body=v["body"])

        self.push_screen(ItemFormScreen(None, save))

    def action_edit_form(self) -> None:
        item = self._need_item()
        if item is None:
            return

        def save(v: dict) -> str | None:
            if not v["title"].strip():
                return "title must not be empty"
            orig = {"title": item.title, "body": item.body, "type": item.type, "priority": item.priority}
            edits = {k: v[k] for k in orig if v[k] != orig[k]}
            if not edits:
                self.say(f"{item.ref}: no changes")
                return None
            change = self._op(ops.update, item.id, **edits)
            if change is None:
                return self.message or "could not save"
            self.say(f"saved {item.ref}" + (f" — {self.keymap.first('undo')} to undo" if change.changed else " (no changes)"))
            return None

        self.push_screen(ItemFormScreen(item, save))

    def action_edit_external(self) -> None:
        item = self._need_item()
        if item is None:
            return
        failure: Exception | None = None
        new = item.body
        try:
            with self.suspend():
                try:
                    new = edit_text_externally(item.body, name=f"triage-{item.id}")
                except (OSError, subprocess.SubprocessError) as exc:
                    failure = exc
        except SuspendNotSupported:
            self.say("cannot open an external editor in this terminal", error=True)
            return
        if failure is not None:
            self.say(f"editor failed: {failure}", error=True)
            self.reload()
            return
        if new.rstrip() == item.body.rstrip():
            self.say("body unchanged")
            self.reload()
            return
        try:
            current = ops.get(self.store, item.id)
        except OP_ERRORS as exc:
            self.say(str(exc), error=True)
            self.reload()
            return
        if current.body != item.body:
            self.say(f"{item.ref} body was changed by {current.updated_by} while you edited; not saved", error=True)
            self.reload(select_id=item.id)
            return
        self._op(ops.update, item.id, body=new, what=f"updated body of {item.ref}")

    def action_note(self) -> None:
        item = self._need_item()
        if item is None:
            return

        def done(text: str | None) -> None:
            if text:
                self._op(ops.note, item.id, text, what=f"noted on {item.ref}", undoable=False)

        self.push_screen(PromptScreen(f"note on {item.ref} — the agent sees this", placeholder="write a note…"), done)

    # ---- navigation -------------------------------------------------------
    def _detail_focused(self) -> bool:
        return self.focused is self.detail

    def action_cursor_down(self) -> None:
        if self._detail_focused():
            self.detail.scroll_down(animate=False)
        else:
            self.items_view.move(1)

    def action_cursor_up(self) -> None:
        if self._detail_focused():
            self.detail.scroll_up(animate=False)
        else:
            self.items_view.move(-1)

    def action_go_top(self) -> None:
        if self._detail_focused():
            self.detail.scroll_home(animate=False)
        else:
            self.items_view.to_edge(False)

    def action_go_bottom(self) -> None:
        if self._detail_focused():
            self.detail.scroll_end(animate=False)
        else:
            self.items_view.to_edge(True)

    def _half(self, sign: int) -> None:
        if self._detail_focused():
            d = self.detail
            d.scroll_to(y=max(0, d.scroll_y + sign * max(1, d.size.height // 2)), animate=False)
        else:
            self.items_view.move(sign * max(1, self.items_view.size.height // 2))

    def action_half_down(self) -> None:
        self._half(1)

    def action_half_up(self) -> None:
        self._half(-1)

    def action_goto_tab(self, tab: str) -> None:
        if tab == self.tab:
            return
        self.tab = tab
        self.render_all(reset=True)

    def _step_tab(self, step: int) -> None:
        self.action_goto_tab(TAB_IDS[(TAB_IDS.index(self.tab) + step) % len(TAB_IDS)])

    def action_tab_next(self) -> None:
        self._step_tab(1)

    def action_tab_prev(self) -> None:
        self._step_tab(-1)

    def action_focus_detail(self) -> None:
        if self.focused is self.filter_input:
            return
        if self.current_item() is None:
            self.say("no item selected")
            return
        self.detail.focus()
        self.refresh_bindings()

    def action_detail_back(self) -> None:
        self.items_view.focus()
        self.refresh_bindings()

    def action_swallow_key(self) -> None:
        """Deliberately do nothing (used for shift+tab on the main screen)."""

    def action_toggle_detail(self) -> None:
        """tab: switch focus between the item list and the detail pane."""
        if self.focused is self.filter_input:  # leave the filter box like enter does
            if self.filter_text.strip():
                self.items_view.focus()
            else:
                self.action_clear_filter()
        elif self._detail_focused():
            self.action_detail_back()
        else:
            self.action_focus_detail()
        self.refresh_bindings()

    # ---- filter -----------------------------------------------------------
    def action_filter(self) -> None:
        inp = self.filter_input
        inp.display = True
        inp.focus()

    def action_clear_filter(self) -> None:
        inp = self.filter_input
        inp.value = ""
        self.filter_text = ""
        inp.display = False
        self.items_view.focus()
        self.render_all()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.filter_text = event.value
            self.render_all(reset=False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter":
            event.stop()
            if not event.value.strip():
                self.action_clear_filter()
            else:
                self.items_view.focus()
            self.refresh_bindings()

    # ---- screens ----------------------------------------------------------
    def action_help(self) -> None:
        self.push_screen(HelpScreen(self.keymap, self.hint_entries()))

    def action_settings(self) -> None:
        board_id = self.store.ref.board_id if self.store else None
        self.push_screen(SettingsScreen(board_id, self._on_config_changed))

    def action_repos(self) -> None:
        self.push_screen(RepoPickerScreen(), self._picked)

    def _picked(self, ref: RepoRef | None) -> None:
        if ref is None:
            return
        if self.store is not None and ref.board_id == self.store.ref.board_id:
            self.say(f"already on {ref.name}")
            return
        self.filter_text = ""
        self.filter_input.value = ""
        self.filter_input.display = False
        self._attach(BoardStore(ref))
        self.say(f"opened {ref.name}")


def run(repo: str | None = None) -> None:
    """Open the board for ``repo`` (default: the cwd / ``$TRIAGE_REPO``); fall back to the repo picker."""
    store: BoardStore | None = None
    try:
        store = BoardStore(resolve_repo(repo))
    except RepoNotFound:
        store = None
    TriageApp(store).run()
