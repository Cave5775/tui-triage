"""User settings: global ``config.toml`` with optional per-board overrides.

File layout (all keys optional; missing keys use DEFAULTS)::

    [agent]
    finish_status = "review"

    [boards."myrepo-1a2b3c4d".agent]
    finish_status = "done"

    [keys]            # global only: TUI keybindings, command = "key1, key2"
    quit = "q, ctrl+q"

The file location is ``$TRIAGE_CONFIG`` when set, else ``<triage home>/config.toml``. ``triage config init``
writes a complete, commented file; writes by :func:`set_value` edit only the one line they change, so
comments and the ``[keys]`` table survive.
"""

from __future__ import annotations

import copy
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import FLOW
from .paths import config_path
from .store import atomic_write_text, file_lock


@dataclass(frozen=True)
class Setting:
    key: str
    kind: type  # str, bool, float, list
    default: Any
    help: str
    choices: tuple[str, ...] | None = None  # for str, or the element choices for list


SETTINGS: tuple[Setting, ...] = (
    Setting("agent.finish_status", str, "review",
            "Where `triage done` sends an item the agent finished", ("review", "done")),
    Setting("agent.pickup_statuses", list, ["todo"],
            "Statuses the agent may claim work from", ("inbox", "todo")),
    Setting("agent.create_status", str, "inbox",
            "Status for items the agent creates", ("inbox", "todo")),
    Setting("agent.can_create", bool, True, "Agent may add new items"),
    Setting("agent.can_edit", bool, False,
            "Agent may edit title/body/type/priority of items the user created (notes are always allowed)"),
    Setting("agent.can_archive", bool, False, "Agent may archive or delete items"),
    Setting("agent.require_claim", bool, True, "Agent must claim an item before marking it done"),
    Setting("ui.new_item_status", str, "inbox", "Status for items added in the TUI", ("inbox", "todo")),
    Setting("ui.confirm_delete", bool, True, "Ask before permanently deleting"),
    Setting("ui.poll_seconds", float, 1.0, "How often the TUI checks the board file for outside changes"),
)
SETTINGS_BY_KEY = {s.key: s for s in SETTINGS}
DEFAULTS = {s.key: s.default for s in SETTINGS}


class ConfigError(ValueError):
    pass


def _flatten(table: dict, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in table.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def load_raw() -> dict:
    path = config_path()
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path} is not UTF-8 text (save it as UTF-8): {exc}") from exc
    except IsADirectoryError as exc:
        raise ConfigError(f"{path} is a directory, not a config file") from exc


def keys_table() -> Any:
    """The raw global ``[keys]`` table (``None`` when absent); validation lives in ``triage.tui.keys``."""
    return load_raw().get("keys")


def get_config(board_id: str | None = None) -> dict[str, Any]:
    """Effective settings as a flat ``{"agent.finish_status": ...}`` dict."""
    raw = load_raw()
    boards = raw.pop("boards", {}) or {}
    cfg = dict(DEFAULTS)
    for layer in (_flatten(raw), _flatten(boards.get(board_id, {})) if board_id else {}):
        for k, v in layer.items():
            if k in SETTINGS_BY_KEY:
                try:
                    cfg[k] = validate(k, v)
                except ConfigError:
                    pass  # ignore bad values, keep the default
    return cfg


def overrides(board_id: str | None = None) -> dict[str, Any]:
    """Only the values explicitly set at one level (global if board_id is None)."""
    raw = load_raw()
    boards = raw.pop("boards", {}) or {}
    layer = _flatten(boards.get(board_id, {})) if board_id else _flatten(raw)
    return {k: v for k, v in layer.items() if k in SETTINGS_BY_KEY}


def validate(key: str, value: Any) -> Any:
    s = SETTINGS_BY_KEY.get(key)
    if s is None:
        raise ConfigError(f"unknown setting {key!r}; known: {', '.join(SETTINGS_BY_KEY)}")
    if s.kind is bool:
        if not isinstance(value, bool):
            raise ConfigError(f"{key} must be true/false")
    elif s.kind is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ConfigError(f"{key} must be a positive number")
        value = float(value)
    elif s.kind is str:
        if not isinstance(value, str) or (s.choices and value not in s.choices):
            raise ConfigError(f"{key} must be one of {', '.join(s.choices or ())}")
    elif s.kind is list:
        if not isinstance(value, list) or not value or any(v not in FLOW for v in value):
            raise ConfigError(f"{key} must be a non-empty list of statuses")
        if s.choices and any(v not in s.choices for v in value):
            raise ConfigError(f"{key} entries must be among {', '.join(s.choices)}")
    return value


def parse_value(key: str, text: str) -> Any:
    """Parse a CLI/TUI string into a typed, validated value for ``key``."""
    s = SETTINGS_BY_KEY.get(key)
    if s is None:
        raise ConfigError(f"unknown setting {key!r}; known: {', '.join(SETTINGS_BY_KEY)}")
    t = text.strip()
    if s.kind is bool:
        low = t.lower()
        if low in ("true", "yes", "on", "1"):
            value: Any = True
        elif low in ("false", "no", "off", "0"):
            value = False
        else:
            raise ConfigError(f"{key} must be true/false")
    elif s.kind is float:
        try:
            value = float(t)
        except ValueError:
            raise ConfigError(f"{key} must be a number") from None
    elif s.kind is list:
        value = [v.strip() for v in t.replace(";", ",").split(",") if v.strip()]
    else:
        value = t
    return validate(key, value)


def set_value(key: str, value: Any, board_id: str | None = None) -> None:
    """Persist a setting globally or for one board. ``value=None`` removes the override."""
    if value is not None:
        value = validate(key, value)
    elif key not in SETTINGS_BY_KEY:
        raise ConfigError(f"unknown setting {key!r}")
    path = config_path()
    with file_lock(path):
        raw = load_raw()
        expected = copy.deepcopy(raw)
        node = expected
        if board_id:
            node = expected.setdefault("boards", {}).setdefault(board_id, {})
        *parents, leaf = key.split(".")
        for p in parents:
            node = node.setdefault(p, {})
        if value is None:
            node.pop(leaf, None)
        else:
            node[leaf] = value
        _prune(expected)
        table = (("boards", board_id) if board_id else ()) + tuple(parents)
        try:
            text = ""
            if path.exists():
                # open() rather than read_text(newline=...), which needs Python 3.13+
                with path.open(encoding="utf-8", newline="") as f:
                    text = f.read()
        except OSError:
            text = ""
        new = _edit_line(text, table, leaf, value)
        if new is None or not _same_config(new, expected):
            new = dumps_toml(expected)  # could not edit in place safely: rewrite (comments are lost)
        atomic_write_text(path, new)


def _prune(table: dict) -> bool:
    """Drop empty sub-tables. Returns True if ``table`` itself became empty."""
    for k in list(table):
        if isinstance(table[k], dict) and _prune(table[k]):
            del table[k]
    return not table


# ---- line-level edit that keeps comments and unrelated tables ------------

_HEADER = re.compile(r"^\s*\[(?!\[)(?P<name>[^\]]+)\]\s*(?:#.*)?$")
_SEGMENT = re.compile(r"""\s*(?:"(?P<d>(?:[^"\\]|\\.)*)"|'(?P<s>[^']*)'|(?P<b>[A-Za-z0-9_-]+))\s*(?:\.|$)""")
_ANY_KEY_LINE = re.compile(r"^\s*(?:[A-Za-z0-9_-]+|\"[^\"]*\"|'[^']*')\s*=")
_SIMPLE_VALUE = re.compile(r"""^(?P<v>"(?:[^"\\]|\\.)*"|'[^']*'|\[[^\]]*\]|[^\s#]+)\s*(?P<c>#.*)?$""")


def _split_dotted(name: str) -> tuple[str, ...] | None:
    """``agent`` / ``boards."my.repo".agent`` -> parts, or None when it is not simple enough to trust."""
    parts: list[str] = []
    pos = 0
    while pos < len(name):
        m = _SEGMENT.match(name, pos)
        if m is None or m.end() == pos:
            return None
        if m.group("d") is not None:
            parts.append(m.group("d").replace('\\"', '"').replace("\\\\", "\\"))
        else:
            parts.append(m.group("s") if m.group("s") is not None else m.group("b"))
        pos = m.end()
    return tuple(parts)


def _edit_line(text: str, table: tuple[str, ...], leaf: str, value: Any) -> str | None:
    """Set (or, for ``value=None``, remove) ``leaf`` in ``[table]`` touching only that line.

    Returns the new text, or None when the file has a shape this cannot edit safely.
    """
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # the final newline; re-added below
    headers = [(i, _split_dotted(m.group("name"))) for i, line in enumerate(lines) if (m := _HEADER.match(line))]
    start = next((i for i, parts in headers if parts == table), None)
    new_line = None if value is None else f"{_toml_key(leaf)} = {_toml_value(value)}"
    if start is None:
        if value is None:
            return text
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.append("")
        lines += ["[" + ".".join(_toml_key(p) for p in table) + "]", new_line]  # type: ignore[list-item]
        return nl.join(lines) + nl
    end = next((i for i, _ in headers if i > start), len(lines))
    key_re = re.compile(r"^\s*(?:%s|\"%s\"|'%s')\s*=\s*(?P<val>.*)$" % ((re.escape(leaf),) * 3))
    found = None
    for j in range(start + 1, end):
        m = key_re.match(lines[j])
        if m:
            found = (j, m.group("val").strip())
            break
    if found is not None:
        j, val = found
        if val.startswith('"' * 3) or val.startswith("'" * 3) or (val.startswith("[") and "]" not in val):
            return None  # a multi-line value: leave it to the full rewrite
        if value is None:
            del lines[j]
        else:
            sv = _SIMPLE_VALUE.match(val)
            comment = f"  {sv.group('c')}" if sv and sv.group("c") else ""
            lines[j] = new_line + comment  # type: ignore[operator]
    elif value is not None:
        last = max((j for j in range(start + 1, end) if _ANY_KEY_LINE.match(lines[j])), default=start)
        lines.insert(last + 1, new_line)  # type: ignore[arg-type]
    return nl.join(lines) + nl if lines else ""


def _same_config(text: str, expected: dict) -> bool:
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False
    _prune(parsed)
    return parsed == expected


# ---- generated default config -----------------------------------------------

def default_config_text(keys_section: str = "") -> str:
    """A complete ``config.toml`` with every setting at its default and a comment for each.

    ``keys_section`` is the ``[keys]`` table text (``triage.tui.keys.default_keys_toml()``).
    """
    lines = [
        "# tui-triage configuration (written by `triage config init`).",
        "# Every setting is shown at its default; edit a value or delete a line to get the default back.",
        "# `triage config set` and the TUI settings screen edit single lines and keep your comments.",
        "# Per-board overrides go in tables like [boards.\"<board id>\".agent] (set with `triage config set --board KEY VALUE`).",
    ]
    section = ""
    for s in SETTINGS:
        head, _, leaf = s.key.partition(".")
        if head != section:
            section = head
            lines += ["", f"[{section}]"]
        note = s.help + (f" ({'any of' if s.kind is list else 'one of'}: {', '.join(s.choices)})" if s.choices else "")
        lines.append(f"# {note}")
        lines.append(f"{leaf} = {_toml_value(s.default)}")
    if keys_section:
        lines += ["", keys_section.rstrip("\n")]
    return "\n".join(lines) + "\n"


def init_config(path: str | Path | None = None, keys_section: str = "", force: bool = False) -> Path:
    """Write the default config to ``path`` (default: :func:`config_path`) and return where it went.

    A directory means ``<dir>/config.toml``. Refuses to overwrite an existing file unless ``force``.
    """
    target = init_target(path)
    with file_lock(target):
        if target.exists() and not force:
            raise ConfigError(f"{target} already exists (use --force to overwrite it)")
        atomic_write_text(target, default_config_text(keys_section))
    return target


def init_target(path: str | Path | None = None) -> Path:
    target = Path(path).expanduser() if path else config_path()
    return target / "config.toml" if target.is_dir() else target


# ---- minimal TOML writer (stdlib has a reader only) ------------------------

def _toml_key(k: str) -> str:
    return k if k.replace("_", "").replace("-", "").isalnum() else '"' + k.replace('"', '\\"') + '"'


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{s}"'


def dumps_toml(data: dict) -> str:
    lines: list[str] = []

    def emit(table: dict, path: list[str]) -> None:
        scalars = {k: v for k, v in table.items() if not isinstance(v, dict)}
        subs = {k: v for k, v in table.items() if isinstance(v, dict)}
        if scalars and path:
            lines.append("[" + ".".join(_toml_key(p) for p in path) + "]")
        for k, v in scalars.items():
            lines.append(f"{_toml_key(k)} = {_toml_value(v)}")
        if scalars:
            lines.append("")
        for k, v in subs.items():
            emit(v, path + [k])

    emit(data, [])
    return "\n".join(lines).rstrip() + "\n"
