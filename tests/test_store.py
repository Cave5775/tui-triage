import subprocess
import sys
import textwrap

from triage.paths import RepoNotFound, resolve_repo
from triage.store import BoardStore, list_boards
from triage import ops

import pytest


def test_board_stored_outside_repo(store, repo, triage_home):
    ops.add(store, "first")
    assert store.path.is_relative_to(triage_home)
    assert not any(p.name != ".git" for p in repo.iterdir()), "nothing may be written inside the repo"


def test_worktree_shares_board(repo, tmp_path):
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", str(wt)], cwd=repo, check=True, capture_output=True)
    assert resolve_repo(wt).board_id == resolve_repo(repo).board_id
    sub = repo / "sub"
    sub.mkdir()
    assert resolve_repo(sub).board_id == resolve_repo(repo).board_id


def test_not_a_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(RepoNotFound):
        resolve_repo(plain)


def test_rev_increments_and_registry(store):
    ops.add(store, "a")
    ops.add(store, "b")
    assert store.load().rev == 2
    assert [b["board_id"] for b in list_boards()] == [store.ref.board_id]


def test_failed_transaction_writes_nothing(store):
    ops.add(store, "a")
    token = store.stat_token()
    with pytest.raises(RuntimeError):
        with store.transaction() as board:
            board.items.clear()
            raise RuntimeError("boom")
    assert store.stat_token() == token
    assert len(store.load().items) == 1


WORKER = textwrap.dedent(
    """
    import sys
    from triage import ops
    store = ops.open_store(sys.argv[1])
    for n in range(int(sys.argv[2])):
        ops.add(store, f"{sys.argv[3]}-{n}", actor="agent")
    """
)


def test_concurrent_processes_lose_no_writes(repo, triage_home):
    procs = [
        subprocess.Popen([sys.executable, "-c", WORKER, str(repo), "50", name])
        for name in ("p1", "p2")
    ]
    assert all(p.wait(timeout=120) == 0 for p in procs)
    board = BoardStore(resolve_repo(repo)).load()
    assert len(board.items) == 100
    assert len({i.id for i in board.items}) == 100
    assert board.rev == 100
