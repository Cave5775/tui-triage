"""Filesystem locations and repository identity.

Every board lives under ``triage_home()``; repositories are never written to.
A repository is identified by its git *common* dir, so all worktrees of a repo
(including agent worktrees under ``.claude/worktrees``) share one board.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class RepoNotFound(Exception):
    """Raised when a path is not inside a git repository."""


def triage_home() -> Path:
    env = os.environ.get("TRIAGE_HOME")
    return Path(env).expanduser() if env else Path.home() / ".triage"


def boards_dir() -> Path:
    return triage_home() / "boards"


def registry_path() -> Path:
    return triage_home() / "registry.json"


def config_path() -> Path:
    return triage_home() / "config.toml"


def board_path(board_id: str) -> Path:
    return boards_dir() / f"{board_id}.json"


def _normalize(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path))).replace("\\", "/").rstrip("/")


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-").lower()
    return s or "repo"


@dataclass(frozen=True)
class RepoRef:
    """A resolved repository: its main working root, display name and board id."""

    root: Path
    name: str
    board_id: str

    @property
    def board_path(self) -> Path:
        return board_path(self.board_id)


def resolve_repo(path: str | Path | None = None) -> RepoRef:
    """Resolve ``path`` (default: ``$TRIAGE_REPO`` or the cwd) to a :class:`RepoRef`.

    Raises :class:`RepoNotFound` if the path is not inside a git repository.
    """
    start = str(path or os.environ.get("TRIAGE_REPO") or os.getcwd())
    if not os.path.isdir(start):
        raise RepoNotFound(f"not a directory: {start}")
    try:
        out = subprocess.run(
            ["git", "-C", start, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # git missing or hung
        raise RepoNotFound(f"could not run git: {exc}") from exc
    if out.returncode != 0 or not out.stdout.strip():
        raise RepoNotFound(f"not inside a git repository: {start}")
    common = Path(out.stdout.strip())
    root = common.parent if common.name == ".git" else common  # bare repos: use the dir itself
    name = root.name or "repo"
    digest = hashlib.sha1(_normalize(common).encode("utf-8")).hexdigest()[:8]
    return RepoRef(root=root, name=name, board_id=f"{_slug(name)}-{digest}")
