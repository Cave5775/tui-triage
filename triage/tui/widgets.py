"""Widgets and pure rendering helpers for the main screen."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from ..model import FLOW, PRIORITY_LABELS, Item
from .keys import fit_hints

# ---- tabs --------------------------------------------------------------------

# (key shown on the tab, tab id, label, short label)
TABS: tuple[tuple[str, str, str, str], ...] = (
    ("1", "inbox", "Inbox", "Inbox"),
    ("2", "todo", "Todo", "Todo"),
    ("3", "doing", "Doing", "Doing"),
    ("4", "review", "Review", "Rev"),
    ("5", "done", "Done", "Done"),
    ("0", "all", "All", "All"),
    ("9", "archived", "Archived", "Arch"),
)
TAB_IDS = tuple(t[1] for t in TABS)
TAB_LABELS = {t[1]: t[2] for t in TABS}

TYPE_SHORT = {"feature": "feat", "fix": "fix", "change": "chg", "chore": "chore", "idea": "idea"}


def tab_statuses(tab: str) -> list[str]:
    if tab == "all":
        return list(FLOW)
    return [tab]


def tab_count(counts: dict[str, int], tab: str) -> int:
    return sum(counts.get(s, 0) for s in tab_statuses(tab))


# ---- palette -----------------------------------------------------------------

_FALLBACK = {
    "primary": "#0178d4", "secondary": "#004578", "accent": "#ffa62b", "error": "#ba3c5b", "warning": "#ffa62b",
    "success": "#4ebf71", "text": "#e0e0e0", "text-muted": "#9a9a9a", "foreground-muted": "#9a9a9a",
    "surface": "#1e1e1e", "panel": "#242f38", "boost": "#ffffff10",
}


_HEX = re.compile(r"^#[0-9a-fA-F]{6}")


def _mix(fg: str, bg: str, t: float) -> str:
    """Blend two ``#rrggbb`` colours (t = share of fg)."""
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * t + y * (1 - t)):02x}" for x, y in zip(f, b))


def palette(app) -> dict[str, str]:
    """Theme colours as plain ``#rrggbb`` strings Rich can use (alpha / ``auto`` values are resolved)."""
    try:
        css = app.get_css_variables()
        dark = bool(app.current_theme.dark)
    except Exception:  # pragma: no cover - app not ready
        css, dark = {}, True
    pal = dict(_FALLBACK)
    for k, v in css.items():
        if isinstance(v, str) and _HEX.match(v):
            pal[k] = v[:7]
    fg = pal.get("foreground", "#e0e0e0" if dark else "#1e1e1e")
    bg = pal.get("background", "#121212" if dark else "#f0f0f0")
    pal["text"] = _mix(fg, bg, 0.9)
    pal["text-muted"] = _mix(fg, bg, 0.6)
    return pal


def priority_style(p: int, pal: dict[str, str]) -> str:
    return {1: f"bold {pal['error']}", 2: f"bold {pal['warning']}", 3: pal["text"], 4: f"dim {pal['text-muted']}"}.get(p, "")


def type_style(t: str, pal: dict[str, str]) -> str:
    return {
        "feature": pal["primary"], "fix": pal["error"], "change": pal["warning"],
        "chore": pal["text-muted"], "idea": pal["success"],
    }.get(t, pal["text"])


def agent_badge(item: Item) -> str:
    """``?`` while an agent's question waits for the user, then ``⚑owner`` (or ``⚑agent`` after its last edit)."""
    who = f"⚑{item.claimed_by}" if item.claimed_by else ("⚑agent" if item.updated_by == "agent" else "")
    return f"? {who}".rstrip() if item.open_question() else who


# ---- time --------------------------------------------------------------------

def _parse(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def fmt_time(iso: str) -> str:
    d = _parse(iso)
    return d.astimezone().strftime("%m-%d %H:%M") if d else iso


def ago(iso: str) -> str:
    d = _parse(iso)
    if d is None:
        return iso
    secs = int((datetime.now(timezone.utc) - d).total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


# ---- tab bar -----------------------------------------------------------------

def render_tabs(counts: dict[str, int], active: str, width: int, pal: dict[str, str]) -> Text:
    """``1 Inbox 3 · 2 Todo 5 · ...``; the active tab is highlighted, Review glows when non-empty."""

    def build(short: bool, sep: str, pad: str = " ") -> Text:
        out = Text(no_wrap=True, overflow="ellipsis")
        for n, (key, tid, label, slabel) in enumerate(TABS):
            if n:
                out.append(sep, style="dim")
            count = tab_count(counts, tid)
            attention = tid == "review" and count > 0
            on = tid == active
            if on:
                style = f"bold {pal['surface']} on {pal['primary']}"
                count_style = style
            else:
                style = pal["warning"] if attention else pal["text"]
                count_style = f"bold {pal['warning']}" if attention else pal["text-muted"]
            out.append(f"{pad}{key} ", style=style if on else ("dim" if not attention else style))
            out.append((slabel if short else label), style=style)
            out.append(f" {count}{pad}", style=count_style)
        return out

    for short, sep, pad in ((False, " · ", " "), (False, "·", " "), (True, "·", " "), (True, " ", "")):
        t = build(short, sep, pad)
        if t.cell_len <= width:
            return t
    return t


# ---- list rows ---------------------------------------------------------------

def render_row(item: Item, width: int, pal: dict[str, str], show_status: bool, flash: bool = False) -> Text:
    """``#12  P1  fix   Title…   ⚑agent`` fitted to ``width`` cells."""
    row = Text(no_wrap=True, overflow="ellipsis")
    row.append(f"{item.ref:>4}  ", style=pal["text-muted"])
    row.append(f"P{item.priority}  ", style=priority_style(item.priority, pal))
    row.append(f"{TYPE_SHORT.get(item.type, item.type):<5} ", style=type_style(item.type, pal))
    if show_status:
        row.append(f"{item.status:<8}", style=pal["text-muted"])
    badge = agent_badge(item)
    badge_w = len(badge) + 1 if badge else 0
    room = max(8, width - row.cell_len - badge_w)
    title = item.title
    if len(title) > room:
        title = title[: max(1, room - 1)] + "…"
    row.append(title.ljust(room), style={1: "bold", 4: "dim"}.get(item.priority, ""))
    if badge:
        row.append(" " + badge, style=f"bold {pal['accent']}")
    if flash:
        row.stylize(f"reverse bold {pal['accent']}")
    return row


class ItemList(OptionList, inherit_bindings=False):
    """The compact item list. All keys are handled by the app (one keymap for footer and help)."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self._rows: list[tuple[int, Text]] = []
        self._signature: object = None

    @property
    def selected_id(self) -> int | None:
        idx = self.highlighted
        if idx is None or idx >= self.option_count:
            return None
        oid = self.get_option_at_index(idx).id
        return int(oid) if oid and oid.isdigit() else None

    @property
    def row_width(self) -> int:
        return max(20, self.scrollable_content_region.width - 2)

    def ids(self) -> list[int]:
        return [i for i, _ in self._rows]

    def set_items(
        self, items: list[Item], pal: dict[str, str], show_status: bool, flash: set[int], select_id: int | None = None,
        empty_text: str = "nothing here", reset: bool = False,
    ) -> None:
        """Re-render the rows, keeping the selection (by id) and the scroll position."""
        width = self.row_width
        rows = [(it.id, render_row(it, width, pal, show_status, it.id in flash)) for it in items]
        wanted = select_id if select_id is not None else (None if reset else self.selected_id)
        old_idx = 0 if reset else (self.highlighted or 0)
        signature = (width, rows, wanted if wanted in [i for i, _ in rows] else None, empty_text)
        if signature == self._signature:
            return
        self._signature = signature
        old_scroll = 0 if reset else self.scroll_y
        self._rows = rows
        self.clear_options()
        if rows:
            self.add_options([Option(text, id=str(i)) for i, text in rows])
            ids = [i for i, _ in rows]
            idx = ids.index(wanted) if wanted in ids else min(old_idx, len(ids) - 1)
            self.highlighted = idx
        else:
            self.add_option(Option(Text(empty_text, style="dim italic"), id="empty", disabled=True))
            self.highlighted = None

        def restore() -> None:
            self.scroll_to(y=old_scroll, animate=False)
            self.scroll_to_highlight()

        self.call_after_refresh(restore)

    def move(self, delta: int) -> None:
        n = len(self._rows)
        if not n:
            return
        cur = self.highlighted if self.highlighted is not None else 0
        self.highlighted = max(0, min(n - 1, cur + delta))

    def to_edge(self, bottom: bool) -> None:
        if self._rows:
            self.highlighted = len(self._rows) - 1 if bottom else 0


# ---- detail pane -------------------------------------------------------------

def render_question(item: Item, pal: dict[str, str], answer_key: str = "r") -> RenderableType | None:
    """The open question boxed in the accent colour, with numbered options; None when nothing is waiting."""
    q = item.open_question()
    if q is None:
        return None
    body = Text()
    body.append("? ", style=f"bold {pal['accent']}")
    body.append(q.text, style="bold")
    body.append(f"\n{'pick any' if q.multi else 'pick one'} · {q.by} asked {ago(q.at)}\n", style="dim")
    for n, option in enumerate(q.options, 1):
        body.append(f"\n  {n}  ", style=f"bold {pal['accent']}")
        body.append(option)
    body.append(f"\n  {len(q.options) + 1}  ", style=f"bold {pal['accent']}")
    body.append("Other: type your own answer", style="dim")
    body.append(f"\n\npress {answer_key} to answer", style=f"bold {pal['accent']}")
    return Panel(body, title="question", title_align="left", border_style=pal["accent"], padding=(0, 1))


def render_detail(item: Item, pal: dict[str, str], edit_key: str = "e", answer_key: str = "r") -> RenderableType:
    title = Text()
    title.append(f"{item.ref}  ", style=pal["text-muted"])
    title.append(item.title, style="bold")

    meta = Text()
    meta.append(item.type, style=type_style(item.type, pal))
    meta.append(" · ", style="dim")
    meta.append(f"P{item.priority} {PRIORITY_LABELS.get(item.priority, '')}", style=priority_style(item.priority, pal))
    meta.append(" · ", style="dim")
    meta.append(item.status, style="bold")
    if item.claimed_by:
        meta.append(" · ", style="dim")
        meta.append(f"⚑ {item.claimed_by}", style=f"bold {pal['accent']}")
    meta.append(f" · created by {item.created_by}", style="dim")
    meta.append(f" · updated {ago(item.updated_at)}", style="dim")
    if item.updated_by == "agent":
        meta.append(" by agent", style=f"dim {pal['accent']}")

    body: RenderableType
    if item.body.strip():
        body = Markdown(item.body)
    else:
        body = Text(f"(no description — press {edit_key} to add one)", style="dim italic")

    log = Text()
    for n, e in enumerate(item.log):
        if n:
            log.append("\n")
        agent = e.by == "agent"
        bar_style = pal["accent"] if agent else pal["primary"]
        log.append("▌ ", style=bar_style)
        log.append(fmt_time(e.at) + " ", style="dim")
        log.append(f"{e.by:<5} ", style=f"bold {pal['accent']}" if agent else "bold")
        if e.kind in ("status", "create", "edit"):
            log.append(f"{e.text}", style="dim" if not agent else f"dim {pal['accent']}")
        elif e.kind == "summary":
            log.append("summary: ", style=f"bold {pal['success']}")
            log.append(e.text)
        elif e.kind == "question":
            log.append("asks: ", style=f"bold {pal['accent']}")
            log.append(e.text, style=pal["accent"] if agent else "")
            if e.data.get("options"):
                log.append("  [" + " | ".join(str(o) for o in e.data["options"]) + "]", style="dim")
        elif e.kind == "answer":
            log.append("answered: ", style=f"bold {pal['success']}")
            log.append(e.text)
        else:
            log.append(e.text, style=pal["accent"] if agent else "")
    if not item.log:
        log.append("(no activity)", style="dim italic")

    question = render_question(item, pal, answer_key)
    head = [title, meta, Rule(style="dim")] + ([question, Text("")] if question is not None else [])
    return Group(*head, body, Rule("activity", style="dim", align="left"), log)


class DetailPane(VerticalScroll, inherit_bindings=False):
    can_focus = True

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self._shown: tuple | None = None
        self._shown_id: int | None = None

    def compose(self):
        yield Static(id="detail-content")

    def show(self, item: Item | None, pal: dict[str, str], edit_key: str = "e", answer_key: str = "r") -> None:
        content = self.query_one("#detail-content", Static)
        key = None if item is None else (str(item.to_dict()), tuple(sorted(pal.items())), edit_key, answer_key)
        if key == self._shown:
            return
        previous_id = self._shown_id
        self._shown = key
        self._shown_id = None if item is None else item.id
        if item is None:
            content.update(Text("No item selected.", style="dim italic"))
            self.scroll_home(animate=False)
            self.border_title = ""
            return
        content.update(render_detail(item, pal, edit_key, answer_key))
        self.border_title = item.ref
        if previous_id != item.id:
            self.scroll_home(animate=False)


# ---- key-hint bar --------------------------------------------------------------

def render_hints(entries: list[tuple[str, str]], width: int, pal: dict[str, str]) -> tuple[Text, list[tuple[str, str]]]:
    """``e edit  c note  ...`` fitted to ``width`` cells (``? help`` is never dropped).

    Returns the styled text and the entries that were kept.
    """
    kept, sep = fit_hints(entries, max(1, width))
    out = Text(no_wrap=True, overflow="ellipsis")
    for n, (key, label) in enumerate(kept):
        if n:
            out.append(sep)
        out.append(key, style=f"bold {pal['accent']}")
        out.append(" " + label, style=pal["text-muted"])
    return out, kept


class KeyHints(Static):
    """The context-aware key-hint bar at the bottom of the main screen."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.entries: list[tuple[str, str]] = []  # everything the context wants to show
        self.shown: list[tuple[str, str]] = []  # what fits the current width
        self.text = Text()  # what is drawn

    def set_entries(self, entries: list[tuple[str, str]]) -> None:
        self.entries = list(entries)
        self._redraw()

    def on_resize(self) -> None:
        self._redraw()

    def _redraw(self) -> None:
        width = self.size.width or 200  # the content width: the CSS padding is already excluded
        self.text, self.shown = render_hints(self.entries, width, palette(self.app))
        self.update(self.text)
