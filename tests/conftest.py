import subprocess
from pathlib import Path

import pytest

from triage.paths import resolve_repo
from triage.store import BoardStore


@pytest.fixture(autouse=True)
def triage_home(tmp_path, monkeypatch) -> Path:
    """Every test gets an isolated TRIAGE_HOME so the real ~/.triage is never touched."""
    home = tmp_path / "triage-home"
    monkeypatch.setenv("TRIAGE_HOME", str(home))
    monkeypatch.delenv("TRIAGE_REPO", raising=False)
    return home


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path) -> Path:
    """A scratch git repo with one commit (so worktrees can be added)."""
    path = tmp_path / "scratch-repo"
    path.mkdir()
    _git("init", "-q", "-b", "main", cwd=path)
    _git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "init", cwd=path)
    return path


@pytest.fixture
def store(repo) -> BoardStore:
    return BoardStore(resolve_repo(repo))
