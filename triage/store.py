"""Durable, concurrency-safe storage.

Writers (the TUI and any number of agent CLI processes) never overwrite each
other: every mutation runs inside :meth:`BoardStore.transaction`, which takes an
exclusive lock file, re-reads the board from disk, lets the caller mutate it,
bumps ``rev`` and atomically replaces the file.  Readers never lock.
"""

from __future__ import annotations

import json
import os
import random
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .model import Board, now_iso
from .paths import RepoRef, boards_dir, registry_path

LOCK_TIMEOUT = 10.0  # seconds to wait for a lock before giving up
LOCK_STALE = 10.0  # a lock file older than this is considered abandoned


class LockTimeout(Exception):
    """Could not acquire a board lock in time."""


@contextmanager
def file_lock(target: Path, timeout: float = LOCK_TIMEOUT, stale: float = LOCK_STALE) -> Iterator[None]:
    """Exclusive cross-process lock implemented with an O_EXCL lock file next to ``target``."""
    lock = target.with_name(target.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, f"{os.getpid()} {time.time()}".encode())
            finally:
                os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale:
                    lock.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            except PermissionError:
                pass
            if time.monotonic() > deadline:
                raise LockTimeout(f"timed out waiting for {lock}") from None
            time.sleep(0.01 + random.random() * 0.02)
        except PermissionError:  # Windows: lock file being deleted right now
            if time.monotonic() > deadline:
                raise LockTimeout(f"timed out waiting for {lock}") from None
            time.sleep(0.01)
    try:
        yield
    finally:
        for _ in range(50):
            try:
                lock.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.01)


def _retry(fn, attempts: int = 100, delay: float = 0.01):
    """Retry on transient Windows sharing violations."""
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def atomic_write_json(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{random.randrange(1 << 30)}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        _retry(lambda: os.replace(tmp, path))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read_json(path: Path, default=None):
    """Read JSON, tolerating a file that is momentarily locked by a concurrent replace."""

    def _read():
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    try:
        return _retry(_read)
    except FileNotFoundError:
        return default


class BoardStore:
    """Access to one repository's board file."""

    def __init__(self, ref: RepoRef):
        self.ref = ref
        self.path = ref.board_path

    def _fresh(self) -> Board:
        return Board(board_id=self.ref.board_id, repo_name=self.ref.name, repo_path=str(self.ref.root))

    def load(self) -> Board:
        """Lock-free snapshot of the board (empty board if none exists yet)."""
        data = read_json(self.path)
        if not data:
            return self._fresh()
        board = Board.from_dict(data)
        board.board_id = board.board_id or self.ref.board_id
        return board

    def exists(self) -> bool:
        return self.path.exists()

    def stat_token(self) -> tuple[int, int] | None:
        """Cheap change detector for polling: (mtime_ns, size), or None if missing."""
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return None
        return (st.st_mtime_ns, st.st_size)

    @contextmanager
    def transaction(self) -> Iterator[Board]:
        """Lock, load the latest board, yield it for mutation, then save atomically.

        If the body raises, nothing is written.
        """
        with file_lock(self.path):
            board = self.load()
            yield board
            board.rev += 1
            board.updated_at = now_iso()
            board.repo_name = self.ref.name
            board.repo_path = str(self.ref.root)
            atomic_write_json(self.path, board.to_dict())
        touch_registry(self.ref)


# ---- registry of known boards ---------------------------------------------

def load_registry() -> dict[str, dict]:
    data = read_json(registry_path(), default={}) or {}
    return data.get("boards", {}) if isinstance(data, dict) else {}


def touch_registry(ref: RepoRef, opened: bool = False) -> None:
    """Record (or refresh) a board in the registry used by the repo picker."""
    path = registry_path()
    with file_lock(path):
        data = read_json(path, default={}) or {}
        boards = data.setdefault("boards", {})
        entry = boards.setdefault(ref.board_id, {})
        entry.update({"name": ref.name, "path": str(ref.root), "updated_at": now_iso()})
        if opened:
            entry["opened_at"] = now_iso()
        atomic_write_json(path, data)


def list_boards() -> list[dict]:
    """Known boards, most recently used first. Each dict has board_id, name, path, timestamps."""
    reg = load_registry()
    # Include board files that exist but are missing from the registry.
    if boards_dir().exists():
        for p in boards_dir().glob("*.json"):
            if p.stem not in reg:
                data = read_json(p, default={}) or {}
                reg[p.stem] = {"name": data.get("repo_name", p.stem), "path": data.get("repo_path", "")}
    rows = [{"board_id": k, **v} for k, v in reg.items()]
    rows.sort(key=lambda r: max(r.get("opened_at", ""), r.get("updated_at", "")), reverse=True)
    return rows
