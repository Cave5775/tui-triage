"""User settings: global ``config.toml`` with optional per-board overrides.

File layout (all keys optional; missing keys use DEFAULTS)::

    [agent]
    finish_status = "review"

    [boards."myrepo-1a2b3c4d".agent]
    finish_status = "done"
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
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
        node = raw
        if board_id:
            node = raw.setdefault("boards", {}).setdefault(board_id, {})
        *parents, leaf = key.split(".")
        chain = [node]
        for p in parents:
            node = node.setdefault(p, {})
            chain.append(node)
        if value is None:
            node.pop(leaf, None)
        else:
            node[leaf] = value
        _prune(raw)
        atomic_write_text(path, dumps_toml(raw))


def _prune(table: dict) -> bool:
    """Drop empty sub-tables. Returns True if ``table`` itself became empty."""
    for k in list(table):
        if isinstance(table[k], dict) and _prune(table[k]):
            del table[k]
    return not table


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
