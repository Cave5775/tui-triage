"""Command-line interface for agents and scripts.

Every board mutation goes through :mod:`triage.ops` and every config write through
:mod:`triage.config`; this module only parses arguments and formats output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from . import config as cfgmod
from . import ops, store as storemod
from .model import ACTORS, FLOW, PRIORITY_LABELS, SORTS, STATUSES, Item, LogEntry, normalize_status
from .paths import RepoNotFound, resolve_repo
from .store import LockTimeout

EXPECTED_ERRORS = (ops.TriageError, ValueError, RepoNotFound, LockTimeout, OSError)


# ---- output helpers ---------------------------------------------------------

def _emit_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _owner(item: Item) -> str:
    return f"  [{item.claimed_by}]" if item.claimed_by else ""


def _line(item: Item) -> str:
    return f"#{item.id} P{item.priority} {item.type} {item.status}  {item.title}{_owner(item)}"


def _table(items: list[Item]) -> str:
    if not items:
        return "(no items)"
    idw = max(len(f"#{i.id}") for i in items)
    tw = max(len(i.type) for i in items)
    sw = max(len(i.status) for i in items)
    rows = []
    for i in items:
        rows.append(f"{f'#{i.id}':<{idw}}  P{i.priority}  {i.type:<{tw}}  {i.status:<{sw}}  {i.title}{_owner(i)}")
    return "\n".join(rows)


def _full(item: Item) -> str:
    out = [
        f"#{item.id}  {item.title}",
        f"{item.type}  P{item.priority} ({PRIORITY_LABELS.get(item.priority, '?')})  {item.status}"
        + (f"  taken by {item.claimed_by}" if item.claimed_by else ""),
        f"created {item.created_at} by {item.created_by}; updated {item.updated_at} by {item.updated_by}",
    ]
    if item.body.strip():
        out += ["", item.body.rstrip()]
    q, a = item.open_question(), item.latest_answer()
    if q:
        out += ["", f"Open question ({'pick any' if q.multi else 'pick one'}): {q.text}"]
        out += [f"  {n}. {o}" for n, o in enumerate(q.options, 1)]
    elif a:
        out += ["", f"Question: {a.question}", f"Answer ({a.by}): {a.summary()}"]
    out += ["", "Log:"]
    if not item.log:
        out.append("  (empty)")
    for e in item.log:
        text = e.text.replace("\n", "\n" + " " * 4)
        out.append(f"  {e.at}  {e.by:<5}  {e.kind:<7}  {text}")
    return "\n".join(out)


def _show_change(args: argparse.Namespace, verb: str, change: ops.Change, full: bool = False) -> int:
    item = change.item
    if args.json:
        _emit_json(ops.item_json(item))
    elif full:
        print(f"{verb} #{item.id}\n")
        print(_full(item))
    else:
        print(f"{verb} {_line(item)}")
    return 0


def _fmt_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return ",".join(str(x) for x in v)
    return str(v)


# ---- input helpers ----------------------------------------------------------

def _item_id(text: str) -> int:
    try:
        return int(text.lstrip("#"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid item id {text!r} (expected a number such as 12)") from None


def _read_stdin() -> str:
    """Read stdin as UTF-8 regardless of the Windows console/pipe code page."""
    buf = getattr(sys.stdin, "buffer", None)
    if buf is not None:
        return buf.read().decode("utf-8-sig", errors="replace")
    return sys.stdin.read()


def _read_body(args: argparse.Namespace) -> str | None:
    if getattr(args, "body_file", None):
        if args.body_file == "-":
            return _read_stdin()
        try:
            return Path(args.body_file).read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise ValueError(f"cannot read --body-file {args.body_file}: {exc}") from None
    body = getattr(args, "body", None)
    if body == "-":
        return _read_stdin()
    return body


def _words(words: list[str]) -> str:
    return " ".join(words).strip()


def _store(args: argparse.Namespace):
    return ops.open_store(args.repo)


# ---- commands ---------------------------------------------------------------

def cmd_tui(args: argparse.Namespace) -> int:
    try:
        from .tui.app import run
    except ImportError as exc:
        raise ValueError(f"the TUI is not available ({exc}); the other commands still work") from None
    run(args.repo)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    st = _store(args)
    board = ops.load(st)
    if args.status:
        wanted = [normalize_status(s) for s in args.status.split(",") if s.strip()]
    elif args.all:
        wanted = list(STATUSES)
    else:
        wanted = list(FLOW)
    items: list[Item] = []
    if args.sort != "priority":  # a view across the selected statuses, e.g. what changed last
        items = board.sorted_items(wanted, args.sort)
    else:
        for status in STATUSES:
            if status in wanted:
                items.extend(board.sorted_items(status))
    if args.json:
        _emit_json([ops.item_json(i) for i in items])
    else:
        print(_table(items))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    item = ops.get(_store(args), args.id)
    if args.json:
        _emit_json(ops.item_json(item))
    else:
        print(_full(item))
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    st = _store(args)
    item = ops.next_item(ops.load(st), ops.config_for(st))
    if args.json:
        _emit_json(ops.item_json(item) if item else None)
    elif item is None:
        print("nothing to pick up")
    else:
        print(_full(item))
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    change = ops.claim(_store(args), args.id, actor=args.actor, who=args.name, force=args.force)
    return _show_change(args, "claimed", change, full=True)


def cmd_release(args: argparse.Namespace) -> int:
    return _show_change(args, "released", ops.release(_store(args), args.id, actor=args.actor, note=args.note))


def cmd_tag(args: argparse.Namespace) -> int:
    return _show_change(args, "tagged", ops.update(_store(args), args.id, actor=args.actor, taken_by=args.who))


def cmd_note(args: argparse.Namespace) -> int:
    return _show_change(args, "noted", ops.note(_store(args), args.id, _words(args.text), actor=args.actor))


WAIT_POLL_SECONDS = 0.5
EXIT_NO_ANSWER = 3  # `ask --wait` ended without an answer (timeout, interrupted, or the question was replaced)


def _answer_view(item: Item, asked: LogEntry) -> dict[str, Any]:
    """``{id, answered, replaced, question, answer}`` for the ``asked`` question entry.

    The entry is matched by value, not position: undo removes log entries, which shifts the indexes.
    ``replaced`` means a newer question took over (or the entry is gone), so no answer to this one can come.
    """
    index = next((i for i in range(len(item.log) - 1, -1, -1) if item.log[i] == asked), None)
    reply = None
    replaced = index is None
    for e in item.log[index + 1:] if index is not None else ():
        if e.kind == "answer":
            reply = e
            break
        if e.kind == "question":
            replaced = True
            break
    question = {"text": asked.text, "options": asked.data.get("options", []), "multi": bool(asked.data.get("multi"))}
    answer = None
    if reply is not None:
        choices, text = reply.answer_parts()
        answer = {"choices": list(choices), "text": text, "by": reply.by, "at": reply.at}
    return {"id": item.id, "answered": answer is not None, "replaced": replaced, "question": question, "answer": answer}


def cmd_ask(args: argparse.Namespace) -> int:
    if args.wait is not None and not args.wait >= 0:
        raise ValueError("--wait takes a number of seconds, 0 or more")
    st = _store(args)
    change = ops.ask(st, args.id, _words(args.question), args.option or [], multi=args.multi, actor=args.actor)
    asked = change.item.log[-1]
    view = _answer_view(change.item, asked)
    if args.wait is not None and not view["answered"]:
        deadline = time.monotonic() + args.wait
        try:
            while not (view["answered"] or view["replaced"]) and time.monotonic() < deadline:
                time.sleep(max(0.0, min(WAIT_POLL_SECONDS, deadline - time.monotonic())))
                view = _answer_view(ops.get(st, args.id), asked)
        except KeyboardInterrupt:
            pass  # stop waiting; the question stays open
    if args.json:
        _emit_json(view)
    elif view["answered"]:
        a = view["answer"]
        print(f"#{args.id} answered by {a['by']}: " + ", ".join(a["choices"] + ([f"other: {a['text']}"] if a["text"] else [])))
    elif view["replaced"]:
        print(f"#{args.id}: this question was replaced; see `triage show {args.id}`")
    elif args.wait is not None:
        print(f"#{args.id}: no answer yet; read it later with `triage show {args.id}`")
    else:
        print(f"asked #{args.id}: {view['question']['text']}")
    return EXIT_NO_ANSWER if args.wait is not None and not view["answered"] else 0


def cmd_answer(args: argparse.Namespace) -> int:
    change = ops.answer(_store(args), args.id, args.choice or [], args.text or "", actor=args.actor)
    a = change.item.latest_answer()
    if args.json:
        _emit_json(ops.item_json(change.item))
    else:
        print(f"answered #{change.item.id}: {a.summary() if a else ''}")
    return 0


def cmd_done(args: argparse.Namespace) -> int:
    return _show_change(args, "finished", ops.finish(_store(args), args.id, actor=args.actor, summary=args.summary or ""))


def cmd_accept(args: argparse.Namespace) -> int:
    return _show_change(args, "accepted", ops.accept(_store(args), args.id, actor=args.actor, note=args.note))


def cmd_bounce(args: argparse.Namespace) -> int:
    return _show_change(args, "bounced", ops.bounce(_store(args), args.id, _words(args.reason), actor=args.actor))


def cmd_add(args: argparse.Namespace) -> int:
    body = _read_body(args)
    change = ops.add(
        _store(args), _words(args.title), actor=args.actor, body=body or "",
        type=args.type, priority=args.priority, status=args.status,
    )
    return _show_change(args, "added", change)


def cmd_set(args: argparse.Namespace) -> int:
    body = _read_body(args)
    fields = {"title": args.title, "type": args.type, "priority": args.priority, "body": body}
    edits = {k: v for k, v in fields.items() if v is not None}
    if not edits and args.status is None:
        raise ValueError("nothing to change: give at least one of --title --type --priority --status --body --body-file")
    if args.status is not None:
        normalize_status(args.status)  # fail before anything is written
    st = _store(args)
    change = None
    if edits:
        change = ops.update(st, args.id, actor=args.actor, **edits)
    if args.status is not None:
        change = ops.set_status(st, args.id, args.status, actor=args.actor)
    return _show_change(args, "updated", change)


def cmd_archive(args: argparse.Namespace) -> int:
    return _show_change(args, "archived", ops.archive(_store(args), args.id, actor=args.actor))


def cmd_delete(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError(f"refusing to delete #{args.id} permanently without --yes (use `triage archive {args.id}` to keep it)")
    change = ops.purge(_store(args), args.id, actor=args.actor)
    item = change.item
    if args.json:
        _emit_json(ops.item_json(item))
    else:
        print(f"deleted #{item.id}  {item.title}")
    return 0


def cmd_repos(args: argparse.Namespace) -> int:
    rows = storemod.list_boards()
    if args.json:
        _emit_json(rows)
    elif not rows:
        print("(no boards yet)")
    else:
        w = max(len(r["name"]) for r in rows)
        for r in rows:
            print(f"{r['name']:<{w}}  {r.get('path', '')}  [{r['board_id']}]")
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    ref = resolve_repo(args.repo)
    if args.json:
        _emit_json({"path": str(ref.board_path), "board_id": ref.board_id, "repo": str(ref.root), "name": ref.name})
    else:
        print(ref.board_path)
    return 0


def _source(key: str, glob: dict, board: dict) -> str:
    if key in board:
        return "board"
    if key in glob:
        return "global"
    return "default"


def _config_scope(args: argparse.Namespace, need_board: bool) -> str | None:
    """Board id to use, or None for the global scope."""
    if args.board:
        return resolve_repo(args.repo).board_id
    if need_board:
        return None
    try:  # reading: show what applies to the current repo when there is one
        return resolve_repo(args.repo).board_id
    except RepoNotFound:
        return None


def _config_entry(s: cfgmod.Setting, eff: dict, glob: dict, board: dict, board_id: str | None) -> dict:
    return {
        "key": s.key,
        "value": eff[s.key],
        "source": _source(s.key, glob, board),
        "help": s.help,
        "choices": list(s.choices) if s.choices else None,
    }


def _config_init(args: argparse.Namespace, rest: list[str]) -> int:
    from .tui import keys

    if len(rest) > 1:
        raise ValueError("usage: triage config init [PATH] [--force]")
    if rest and args.actor != "user":
        raise ops.PermissionDenied(
            "choosing where to write a config file belongs to the user; agents may only create the "
            "default one (a human can run `triage config init PATH --as user`)"
        )
    target = cfgmod.init_target(rest[0] if rest else None)
    exists = target.exists()
    if exists and not args.force:
        raise cfgmod.ConfigError(f"{target} already exists; pass --force to overwrite it (as the user: --as user)")
    if exists and args.actor != "user":
        raise ops.PermissionDenied(
            "overwriting settings belongs to the user; agents may not "
            "(a human can run `triage config init --force --as user`)"
        )
    # only the user may overwrite: re-checked under the lock inside init_config
    path = cfgmod.init_config(target, keys.default_keys_toml(), force=args.force and args.actor == "user")
    if args.json:
        _emit_json({"path": str(path), "overwritten": exists})
    else:
        print(f"{'overwrote' if exists else 'wrote'} {path}")
        if not exists and path != cfgmod.config_path():
            print(f"to use it, set TRIAGE_CONFIG={path}")
    return 0


def _config_keys(args: argparse.Namespace) -> int:
    from .tui import keys

    km = keys.load_keymap()
    rows = []
    for c in keys.COMMANDS:
        rows.append({
            "command": c.name,
            "keys": list(km.keys_for(c.name)),
            "config": km.config_value(c.name),
            "default": list(c.keys),
            "source": "config" if c.name in km.user_set else "default",
            "group": c.group,
            "description": c.desc,
        })
    problems = [{"command": p.command, "message": p.message} for p in km.problems]
    if args.json:
        _emit_json({"path": str(cfgmod.config_path()), "keys": rows, "problems": problems})
        return 0
    w = max(len(r["command"]) for r in rows)
    kw = max(len(r["config"]) for r in rows)
    for r in rows:
        mark = "*" if r["source"] == "config" else " "
        print(f"{r['command']:<{w}}  {r['config']:<{kw}} {mark} {r['description']}")
    print(f"\n(* = set in {cfgmod.config_path()})")
    for p in problems:
        print(f"problem: {p['message']}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    words = args.words
    action = words[0] if words else "get"
    rest = words[1:]
    if action not in ("get", "set", "unset", "init", "keys"):
        raise ValueError(
            f"unknown config action {action!r}; use `config get [KEY]`, `config set KEY VALUE`, `config unset KEY`, "
            "`config init [PATH] [--force]` or `config keys`"
        )
    if action == "init":
        return _config_init(args, rest)
    if action == "keys":
        if rest:
            raise ValueError("usage: triage config keys")
        return _config_keys(args)
    if action == "get":
        if len(rest) > 1:
            raise ValueError("usage: triage config get [KEY]")
        board_id = _config_scope(args, need_board=False)
        eff = cfgmod.get_config(board_id)
        glob = cfgmod.overrides(None)
        board = cfgmod.overrides(board_id) if board_id else {}
        if rest and rest[0] not in cfgmod.SETTINGS_BY_KEY:
            raise cfgmod.ConfigError(f"unknown setting {rest[0]!r}; known: {', '.join(cfgmod.SETTINGS_BY_KEY)}")
        settings = [cfgmod.SETTINGS_BY_KEY[rest[0]]] if rest else list(cfgmod.SETTINGS)
        entries = [_config_entry(s, eff, glob, board, board_id) for s in settings]
        if args.json:
            _emit_json(entries[0] if rest else entries)
        else:
            w = max(len(e["key"]) for e in entries)
            vw = max(len(_fmt_value(e["value"])) for e in entries)
            for e in entries:
                print(f"{e['key']:<{w}}  {_fmt_value(e['value']):<{vw}}  ({e['source']})  {e['help']}")
        return 0
    if args.actor != "user":
        raise ops.PermissionDenied(
            "settings belong to the user; agents may not change them "
            "(a human can run `triage config set ... --as user` or use the TUI settings screen)"
        )
    board_id = _config_scope(args, need_board=True)
    if action == "set":
        if len(rest) < 2:
            raise ValueError("usage: triage config set KEY VALUE")
        key, text = rest[0], " ".join(rest[1:])
        value = cfgmod.parse_value(key, text)
        cfgmod.set_value(key, value, board_id)
    else:
        if len(rest) != 1:
            raise ValueError("usage: triage config unset KEY")
        key, value = rest[0], None
        cfgmod.set_value(key, None, board_id)
    scope = "board" if board_id else "global"
    eff = cfgmod.get_config(board_id)
    if args.json:
        _emit_json({"key": key, "value": eff[key], "scope": scope, "board_id": board_id,
                    "action": action})
    elif action == "set":
        print(f"{key} = {_fmt_value(value)}  ({scope})")
    else:
        print(f"{key} unset ({scope}); effective value is now {_fmt_value(eff[key])}")
    return 0


def cmd_install_skill(args: argparse.Namespace) -> int:
    from .skill import install_skill

    path = install_skill(args.dir, force=args.force)
    if args.json:
        _emit_json({"path": str(path)})
    else:
        print(path)
    return 0


# ---- parser -----------------------------------------------------------------

def _common(suppress: bool) -> argparse.ArgumentParser:
    """Global options. Subparsers reuse them (with suppressed defaults) so they work before or after the command."""
    p = argparse.ArgumentParser(add_help=False)
    sup = argparse.SUPPRESS
    p.add_argument("--repo", metavar="PATH", default=sup if suppress else None,
                   help="repository to use (default: $TRIAGE_REPO, else the current directory)")
    p.add_argument("--as", dest="actor", choices=ACTORS, metavar="{agent,user}", default=sup if suppress else None,
                   help="who is acting (default: agent, or $TRIAGE_ACTOR)")
    p.add_argument("--json", action="store_true", default=sup if suppress else False,
                   help="print one JSON document instead of text")
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="triage",
        description="Per-repository triage board shared between you (TUI) and coding agents (this CLI).",
        parents=[_common(False)],
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    common = _common(True)

    def add(name: str, func, help: str, **kw) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, parents=[common], help=help, description=help, **kw)
        sp.set_defaults(func=func)
        return sp

    def body_opts(sp: argparse.ArgumentParser) -> None:
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--body", help="item body text; `-` reads stdin")
        g.add_argument("--body-file", metavar="PATH", help="read the body from a file (`-` for stdin)")

    add("tui", cmd_tui, "open the board (also the default with no command)")

    sp = add("list", cmd_list, "list items grouped by status in flow order")
    sp.add_argument("--status", help="comma-separated statuses to show, e.g. todo,doing")
    sp.add_argument("--all", action="store_true", help="include archived items")
    sp.add_argument("--sort", choices=tuple(SORTS), default="priority",
                    help="priority (default: grouped by status), or one list by activity (latest first), "
                         "created (newest first), oldest or number (item number)")

    sp = add("show", cmd_show, "show one item with its body and full log")
    sp.add_argument("id", type=_item_id)

    add("next", cmd_next, "show the item an agent should pick up next (does not claim it)")

    sp = add("claim", cmd_claim, "start work on an item (-> doing); no ID claims the next item")
    sp.add_argument("id", nargs="?", type=_item_id)
    sp.add_argument("--force", action="store_true", help="take over an item claimed by someone else")
    sp.add_argument("--name", help="name recorded as the claimer (default: the actor)")

    sp = add("release", cmd_release, "give up a claim; the item returns to todo")
    sp.add_argument("id", type=_item_id)
    sp.add_argument("--note", help="why you are releasing it")

    sp = add("tag", cmd_tag, "set who has taken an item (user only): none, agent, or user (the agent must not touch it)")
    sp.add_argument("id", type=_item_id)
    sp.add_argument("who", choices=("none", "agent", "user"))

    sp = add("note", cmd_note, "append a note to an item's log")
    sp.add_argument("id", type=_item_id)
    sp.add_argument("text", nargs="+")

    sp = add("ask", cmd_ask, "ask the user a multiple-choice question (they answer in the TUI)")
    sp.add_argument("id", type=_item_id)
    sp.add_argument("question", nargs="+")
    sp.add_argument("--option", action="append", metavar="TEXT", help="an answer to offer; repeat for 2-6 options")
    sp.add_argument("--multi", action="store_true", help="the user may pick several options")
    sp.add_argument("--wait", nargs="?", type=float, const=float("inf"), default=None, metavar="SECONDS",
                    help="wait for the answer and print it (bare --wait: until answered); "
                         "exits 3 without an answer, and the question stays open")

    sp = add("answer", cmd_answer, "answer an item's open question (the user's job: use --as user)")
    sp.add_argument("id", type=_item_id)
    sp.add_argument("--choice", action="append", metavar="OPTION", help="an option to pick; repeat for several")
    sp.add_argument("--text", help="free text (\"Other\"), alone or with choices")

    sp = add("done", cmd_done, "finish an item (-> review unless configured otherwise)")
    sp.add_argument("id", type=_item_id)
    sp.add_argument("--summary", help="what changed, which files, how it was verified")

    sp = add("accept", cmd_accept, "approve reviewed work (review -> done)")
    sp.add_argument("id", type=_item_id)
    sp.add_argument("--note")

    sp = add("bounce", cmd_bounce, "send reviewed work back to todo with a reason")
    sp.add_argument("id", type=_item_id)
    sp.add_argument("reason", nargs="+")

    sp = add("add", cmd_add, "add an item")
    sp.add_argument("title", nargs="+")
    sp.add_argument("--type", default="feature", help="feature, fix, change, chore or idea (default: feature)")
    sp.add_argument("--priority", default="3", help="1 (urgent) to 4 (low), default 3")
    sp.add_argument("--status", help="initial status (default from settings)")
    body_opts(sp)

    sp = add("set", cmd_set, "edit an item's fields and/or status")
    sp.add_argument("id", type=_item_id)
    sp.add_argument("--title")
    sp.add_argument("--type")
    sp.add_argument("--priority")
    sp.add_argument("--status")
    body_opts(sp)

    sp = add("archive", cmd_archive, "soft-delete an item")
    sp.add_argument("id", type=_item_id)

    sp = add("delete", cmd_delete, "permanently delete an item (requires --yes)")
    sp.add_argument("id", type=_item_id)
    sp.add_argument("--yes", action="store_true", help="confirm the permanent delete")

    add("repos", cmd_repos, "list known boards")
    add("path", cmd_path, "print the board file path for the current repo")

    sp = add("config", cmd_config,
             "show or change settings: config [get [KEY]] | set KEY VALUE | unset KEY | init [PATH] [--force] | keys")
    sp.add_argument("words", nargs="*", metavar="get|set|unset|init|keys [KEY|PATH] [VALUE]")
    sp.add_argument("--board", action="store_true", help="target this repo's board instead of the global settings")
    sp.add_argument("--force", action="store_true",
                    help="init: overwrite an existing config file (requires --as user)")

    sp = add("install-skill", cmd_install_skill, "install the Claude Code skill (SKILL.md)")
    sp.add_argument("--force", action="store_true", help="overwrite a different existing SKILL.md")
    sp.add_argument("--dir", metavar="PATH", help="target directory (default: ~/.claude/skills/triage)")
    return parser


# ---- entry point ------------------------------------------------------------

def _utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse: 0 for --help, 2 for usage errors
        code = exc.code if isinstance(exc.code, int) else 2
        if code and "--json" in (argv if argv is not None else sys.argv[1:]):
            _emit_json({"error": "usage error (details on stderr; see `triage --help`)", "type": "UsageError"})
        return code
    if args.actor is None:
        args.actor = os.environ.get("TRIAGE_ACTOR") or "agent"
    func = getattr(args, "func", cmd_tui)
    try:
        if args.actor not in ACTORS:
            raise ValueError(f"$TRIAGE_ACTOR must be one of {', '.join(ACTORS)}, got {args.actor!r}")
        return func(args)
    except EXPECTED_ERRORS as exc:
        if args.json:
            _emit_json({"error": str(exc), "type": type(exc).__name__})
        else:
            print(f"triage: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
