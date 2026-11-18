"""Data model: items, their activity log, and the board that holds them."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# Workflow order. "archived" is a soft-delete bin outside the flow.
FLOW: tuple[str, ...] = ("inbox", "todo", "doing", "review", "done")
STATUSES: tuple[str, ...] = FLOW + ("archived",)
TYPES: tuple[str, ...] = ("feature", "fix", "change", "chore", "idea")
PRIORITIES: tuple[int, ...] = (1, 2, 3, 4)  # 1 = urgent ... 4 = low
PRIORITY_LABELS = {1: "urgent", 2: "high", 3: "normal", 4: "low"}
ACTORS: tuple[str, ...] = ("user", "agent")
LOG_KINDS: tuple[str, ...] = ("note", "status", "edit", "summary", "create", "question", "answer")
MIN_OPTIONS, MAX_OPTIONS = 2, 6  # choices an agent may offer with a question

# Aliases accepted wherever a type/status is parsed from text.
TYPE_ALIASES = {
    "feat": "feature", "feature": "feature", "f": "feature",
    "fix": "fix", "bug": "fix", "bugfix": "fix",
    "change": "change", "chg": "change", "refactor": "change",
    "chore": "chore", "task": "chore",
    "idea": "idea", "maybe": "idea",
}
STATUS_ALIASES = {
    "inbox": "inbox", "in": "inbox", "new": "inbox",
    "todo": "todo", "ready": "todo",
    "doing": "doing", "wip": "doing", "progress": "doing", "in_progress": "doing",
    "review": "review", "rev": "review",
    "done": "done", "closed": "done",
    "archived": "archived", "archive": "archived", "trash": "archived",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class LogEntry:
    """One activity entry. ``data`` carries the structured part of a ``question`` / ``answer`` entry."""

    at: str
    by: str
    kind: str
    text: str
    data: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "LogEntry":
        data = d.get("data")
        return cls(at=d.get("at", ""), by=d.get("by", "user"), kind=d.get("kind", "note"), text=d.get("text", ""),
                   data=dict(data) if isinstance(data, dict) else {})


@dataclass(frozen=True)
class Question:
    """A multiple-choice question an agent put to the user (the ``question`` log entry, parsed)."""

    text: str
    options: tuple[str, ...]
    multi: bool
    at: str
    by: str

    def to_dict(self) -> dict:
        return {"text": self.text, "options": list(self.options), "multi": self.multi, "at": self.at, "by": self.by}


@dataclass(frozen=True)
class Answer:
    """The user's reply to the latest question: the options picked and/or free text ("Other")."""

    choices: tuple[str, ...]
    text: str
    question: str
    at: str
    by: str

    def to_dict(self) -> dict:
        return {"choices": list(self.choices), "text": self.text, "question": self.question, "at": self.at, "by": self.by}

    def summary(self) -> str:
        parts = list(self.choices) + ([f"other: {self.text}"] if self.text else [])
        return ", ".join(parts)


@dataclass
class Item:
    id: int
    title: str
    body: str = ""
    type: str = "feature"
    priority: int = 3
    status: str = "inbox"
    rank: float = 0.0
    created_by: str = "user"
    updated_by: str = "user"
    claimed_by: str | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    log: list[LogEntry] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"#{self.id}"

    def to_dict(self) -> dict:
        d = asdict(self)
        for entry in d["log"]:
            if not entry["data"]:
                del entry["data"]  # keep plain entries (and old board files) byte-for-byte as they were
        return d

    # ---- questions ------------------------------------------------------
    def _latest_question_index(self) -> int | None:
        for i in range(len(self.log) - 1, -1, -1):
            if self.log[i].kind == "question":
                return i
        return None

    def open_question(self) -> Question | None:
        """The latest question, unless an ``answer`` entry came after it."""
        i = self._latest_question_index()
        if i is None or any(e.kind == "answer" for e in self.log[i + 1:]):
            return None
        e = self.log[i]
        return Question(
            text=e.text, options=tuple(str(o) for o in e.data.get("options") or ()),
            multi=bool(e.data.get("multi")), at=e.at, by=e.by,
        )

    def latest_answer(self) -> Answer | None:
        """The answer to the latest question (None while it is still open, or when nothing was asked)."""
        i = self._latest_question_index()
        if i is None:
            return None
        for e in reversed(self.log[i + 1:]):
            if e.kind == "answer":
                return Answer(
                    choices=tuple(str(c) for c in e.data.get("choices") or ()), text=str(e.data.get("text") or ""),
                    question=self.log[i].text, at=e.at, by=e.by,
                )
        return None

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        d = dict(d)
        d["log"] = [LogEntry.from_dict(e) for e in d.get("log", [])]
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    def copy(self) -> "Item":
        return copy.deepcopy(self)


@dataclass
class Board:
    board_id: str
    repo_name: str = ""
    repo_path: str = ""
    rev: int = 0
    next_id: int = 1
    updated_at: str = field(default_factory=now_iso)
    items: list[Item] = field(default_factory=list)

    # ---- queries -------------------------------------------------------
    def get(self, item_id: int) -> Item | None:
        for it in self.items:
            if it.id == item_id:
                return it
        return None

    def sorted_items(self, statuses: str | list[str] | tuple[str, ...] | None = None, by: str = "priority") -> list[Item]:
        """Items in display order (see :data:`SORTS`; default priority, then manual rank, then id).

        ``statuses`` may be a single status, a collection, or None for all non-archived.
        """
        if statuses is None:
            wanted = set(FLOW)
        elif isinstance(statuses, str):
            wanted = {statuses}
        else:
            wanted = set(statuses)
        return sort_items([i for i in self.items if i.status in wanted], by)

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in STATUSES}
        for it in self.items:
            out[it.status] = out.get(it.status, 0) + 1
        return out

    # ---- serialization -------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "version": 1,
            "board_id": self.board_id,
            "repo_name": self.repo_name,
            "repo_path": self.repo_path,
            "rev": self.rev,
            "next_id": self.next_id,
            "updated_at": self.updated_at,
            "items": [i.to_dict() for i in self.items],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Board":
        return cls(
            board_id=d.get("board_id", ""),
            repo_name=d.get("repo_name", ""),
            repo_path=d.get("repo_path", ""),
            rev=int(d.get("rev", 0)),
            next_id=int(d.get("next_id", 1)),
            updated_at=d.get("updated_at", now_iso()),
            items=[Item.from_dict(i) for i in d.get("items", [])],
        )


def sort_key(item: Item) -> tuple:
    return (item.priority, item.rank, item.id)


# sort name -> label. "priority" is the manual order (priority, then rank); the others are views.
SORTS: dict[str, str] = {
    "priority": "priority",
    "activity": "last activity",
    "created": "newest",
    "oldest": "oldest",
    "number": "item number",
}


def sort_items(items: list[Item], by: str = "priority") -> list[Item]:
    """``items`` in the order named by ``by`` (a :data:`SORTS` key); ties fall back to id."""
    if by == "activity":
        return sorted(items, key=lambda i: (i.updated_at, i.id), reverse=True)
    if by == "created":
        return sorted(items, key=lambda i: (i.created_at, i.id), reverse=True)
    if by == "oldest":
        return sorted(items, key=lambda i: (i.created_at, i.id))
    if by == "number":
        return sorted(items, key=lambda i: i.id)
    if by != "priority":
        raise ValueError(f"unknown sort {by!r}; expected one of {', '.join(SORTS)}")
    return sorted(items, key=sort_key)


def normalize_type(value: str) -> str:
    t = TYPE_ALIASES.get(str(value).strip().lower())
    if not t:
        raise ValueError(f"unknown type {value!r}; expected one of {', '.join(TYPES)}")
    return t


def normalize_status(value: str) -> str:
    s = STATUS_ALIASES.get(str(value).strip().lower())
    if not s:
        raise ValueError(f"unknown status {value!r}; expected one of {', '.join(STATUSES)}")
    return s


def normalize_priority(value: int | str) -> int:
    try:
        p = int(str(value).strip().lstrip("pP!"))
    except ValueError:
        raise ValueError(f"priority must be 1-4, got {value!r}") from None
    if p not in PRIORITIES:
        raise ValueError(f"priority must be 1-4, got {value!r}")
    return p
