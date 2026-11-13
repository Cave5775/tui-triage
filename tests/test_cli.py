import io
import json
import subprocess

import pytest

from triage import skill
from triage.cli import main


@pytest.fixture
def run(repo, monkeypatch, capsys):
    """Run the CLI in-process from inside the scratch repo; returns (code, stdout, stderr)."""
    monkeypatch.chdir(repo)

    def _run(*argv):
        capsys.readouterr()
        code = main(list(argv))
        out = capsys.readouterr()
        return code, out.out, out.err

    return _run


def jrun(run, *argv):
    code, out, err = run(*argv, "--json")
    assert code == 0, err or out
    return json.loads(out)


def test_agent_loop(run):
    item = jrun(run, "add", "Fix the login crash", "--type", "fix", "--priority", "1", "--status", "todo", "--body", "stack trace")
    assert item["id"] == 1 and item["status"] == "todo" and item["created_by"] == "agent"
    assert item["type"] == "fix" and item["priority"] == 1

    assert jrun(run, "next")["id"] == 1
    claimed = jrun(run, "claim", "1")
    assert claimed["status"] == "doing" and claimed["claimed_by"] == "agent"
    assert jrun(run, "next") is None  # nothing unclaimed left

    noted = jrun(run, "note", "1", "found", "the", "cause")
    assert noted["log"][-1]["kind"] == "note" and noted["log"][-1]["text"] == "found the cause"

    done = jrun(run, "done", "1", "--summary", "fixed in auth.py; ran tests")
    assert done["status"] == "review"
    shown = jrun(run, "show", "1")
    kinds = [e["kind"] for e in shown["log"]]
    assert kinds == ["create", "status", "note", "summary", "status"]
    assert shown["body"] == "stack trace"

    listed = jrun(run, "list", "--status", "review")
    assert [i["id"] for i in listed] == [1]


def test_claim_without_id_takes_next(run):
    jrun(run, "add", "low", "--priority", "4", "--status", "todo")
    jrun(run, "add", "urgent", "--priority", "1", "--status", "todo")
    claimed = jrun(run, "claim", "--name", "worker-7")
    assert claimed["title"] == "urgent" and claimed["claimed_by"] == "worker-7"


def test_user_accept_and_bounce(run):
    jrun(run, "add", "Thing", "--status", "todo")
    jrun(run, "claim", "1")
    jrun(run, "done", "1", "--summary", "ok")
    code, _, err = run("accept", "1")  # agent may not accept
    assert code == 1 and "agent" in err
    accepted = jrun(run, "--as", "user", "accept", "1", "--note", "thanks")
    assert accepted["status"] == "done"

    jrun(run, "add", "Other", "--status", "todo")
    jrun(run, "claim", "2")
    jrun(run, "done", "2")
    bounced = jrun(run, "bounce", "2", "--as", "user", "needs", "tests")
    assert bounced["status"] == "todo"
    assert bounced["log"][-1]["text"] == "bounced: needs tests"


def test_actor_from_env(run, monkeypatch):
    monkeypatch.setenv("TRIAGE_ACTOR", "user")
    item = jrun(run, "add", "from the user")
    assert item["created_by"] == "user"


def test_permission_error_text_and_exit_code(run):
    jrun(run, "--as", "user", "add", "User item", "--status", "todo")
    code, out, err = run("set", "1", "--title", "Renamed")
    assert code == 1 and out == ""
    assert err.startswith("triage: error:") and "agent.can_edit" in err
    assert "Traceback" not in err


def test_json_error_shape(run):
    code, out, err = run("show", "99", "--json")
    assert code == 1 and err == ""
    doc = json.loads(out)
    assert doc["type"] == "NotFound" and "#99" in doc["error"]


def test_invalid_value_is_a_clean_error(run):
    code, _, err = run("add", "x", "--type", "banana")
    assert code == 1 and err.startswith("triage: error:")


def test_usage_error_exit_2(run):
    code, _, err = run("show")
    assert code == 2 and "usage" in err
    assert run("show", "abc")[0] == 2


def test_not_a_repo(tmp_path, monkeypatch, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    assert main(["list"]) == 1
    err = capsys.readouterr().err
    assert "not inside a git repository" in err
    assert main(["list", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["type"] == "RepoNotFound"


def test_next_with_nothing(run):
    code, out, _ = run("next")
    assert code == 0 and "nothing to pick up" in out
    assert jrun(run, "next") is None
    code, out, _ = run("claim")
    assert code == 1 and "nothing to pick up" in out + _


def test_list_human_table_and_grouping(run):
    jrun(run, "add", "in doing", "--status", "todo", "--priority", "4")
    jrun(run, "add", "in todo", "--status", "todo", "--priority", "1", "--type", "fix")
    jrun(run, "claim", "1", "--name", "bot")
    jrun(run, "add", "mine", "--status", "inbox")
    code, out, _ = run("list")
    assert code == 0
    lines = out.splitlines()
    assert [ln.split()[0] for ln in lines] == ["#3", "#2", "#1"]  # inbox, todo, doing
    assert "P1" in lines[1] and "fix" in lines[1] and "todo" in lines[1]
    assert lines[2].endswith("in doing  [bot]")


def test_list_all_includes_archived(run):
    jrun(run, "--as", "user", "add", "gone")
    jrun(run, "--as", "user", "archive", "1")
    assert jrun(run, "list") == []
    assert [i["id"] for i in jrun(run, "list", "--all")] == [1]


def test_show_human_has_log(run):
    jrun(run, "add", "Titled", "--body", "the body", "--status", "todo")
    run("note", "1", "hello")
    code, out, _ = run("show", "1")
    assert code == 0 and "Titled" in out and "the body" in out and "hello" in out and "agent" in out


def test_set_fields_and_status(run):
    jrun(run, "add", "Mine", "--status", "todo")
    changed = jrun(run, "set", "1", "--title", "Better", "--priority", "2", "--status", "inbox")
    assert changed["title"] == "Better" and changed["priority"] == 2 and changed["status"] == "inbox"
    code, _, err = run("set", "1")
    assert code == 1 and "nothing to change" in err
    code, _, err = run("set", "1", "--title", "X", "--status", "nonsense")
    assert code == 1
    assert jrun(run, "show", "1")["title"] == "Better"  # nothing half-applied


def test_release(run):
    jrun(run, "add", "Mine", "--status", "todo")
    jrun(run, "claim", "1")
    rel = jrun(run, "release", "1", "--note", "blocked on API key")
    assert rel["status"] == "todo" and rel["claimed_by"] is None
    assert rel["log"][-1]["text"] == "blocked on API key"


def test_delete_requires_yes(run):
    jrun(run, "--as", "user", "add", "doomed")
    code, _, err = run("delete", "1", "--as", "user")
    assert code == 1 and "--yes" in err
    assert len(jrun(run, "list")) == 1
    jrun(run, "delete", "1", "--yes", "--as", "user")
    assert jrun(run, "list") == []


def test_add_body_from_stdin(run, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("line one\nline two\n"))
    item = jrun(run, "add", "Piped", "--body", "-")
    assert item["body"] == "line one\nline two\n"


def test_add_body_file(run, tmp_path):
    f = tmp_path / "body.md"
    f.write_text("from file ✓", encoding="utf-8")
    assert jrun(run, "add", "File", "--body-file", str(f))["body"] == "from file ✓"
    code, _, err = run("add", "Missing", "--body-file", str(tmp_path / "nope.md"))
    assert code == 1 and "cannot read" in err


def test_global_options_before_or_after_command(run, repo, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # not a repo; --repo must be honoured in either position
    code, out, _ = run("--repo", str(repo), "--json", "list")
    assert code == 0 and json.loads(out) == []
    code, out, _ = run("list", "--repo", str(repo), "--json")
    assert code == 0 and json.loads(out) == []


def test_repo_from_env(run, repo, tmp_path, monkeypatch):
    run("add", "here")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRIAGE_REPO", str(repo))
    assert len(jrun(run, "list")) == 1


def test_worktree_sees_same_items(run, repo, tmp_path, monkeypatch):
    jrun(run, "add", "shared item", "--status", "todo")
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "other", str(wt)], cwd=repo, check=True, capture_output=True)
    monkeypatch.chdir(wt)
    items = jrun(run, "list")
    assert [i["title"] for i in items] == ["shared item"]
    assert jrun(run, "claim", "1")["status"] == "doing"
    monkeypatch.chdir(repo)
    assert jrun(run, "show", "1")["status"] == "doing"
    assert jrun(run, "path")["path"] == jrun(run, "--repo", str(wt), "path")["path"]


def test_repos_and_path(run, triage_home):
    jrun(run, "add", "x")
    boards = jrun(run, "repos")
    assert len(boards) == 1 and boards[0]["name"] == "scratch-repo"
    code, out, _ = run("path")
    assert code == 0 and out.strip().startswith(str(triage_home)) and out.strip().endswith(".json")
    assert "scratch-repo" in run("repos")[1]


def test_config_list_and_board_scope(run):
    entries = jrun(run, "config", "get")
    by_key = {e["key"]: e for e in entries}
    assert by_key["agent.finish_status"]["source"] == "default"
    assert by_key["agent.finish_status"]["help"]

    code, out, _ = run("config", "set", "agent.finish_status", "done")
    assert code == 0 and "global" in out
    assert jrun(run, "config", "get", "agent.finish_status")["source"] == "global"

    code, out, _ = run("config", "set", "agent.can_edit", "true", "--board")
    assert code == 0 and "board" in out
    entry = jrun(run, "config", "get", "agent.can_edit", "--board")
    assert entry["value"] is True and entry["source"] == "board"
    assert jrun(run, "config", "get", "agent.finish_status", "--board")["source"] == "global"

    # the board override changes agent behaviour
    jrun(run, "--as", "user", "add", "user made")
    assert jrun(run, "set", "1", "--title", "edited by agent")["title"] == "edited by agent"

    jrun(run, "config", "unset", "agent.can_edit", "--board")
    assert jrun(run, "config", "get", "agent.can_edit")["source"] == "default"


def test_config_errors(run):
    code, _, err = run("config", "set", "agent.nope", "1")
    assert code == 1 and "unknown setting" in err
    code, _, err = run("config", "set", "agent.finish_status", "bogus")
    assert code == 1 and "review, done" in err
    assert run("config", "get", "agent.nope")[0] == 1
    assert run("config", "frobnicate")[0] == 1
    assert run("config", "set", "agent.can_edit")[0] == 1


def test_done_goes_to_done_when_configured(run):
    run("config", "set", "agent.finish_status", "done", "--board")
    jrun(run, "add", "x", "--status", "todo")
    jrun(run, "claim", "1")
    assert jrun(run, "done", "1")["status"] == "done"


def test_install_skill(tmp_path, run):
    target = tmp_path / "skills" / "triage"
    code, out, _ = run("install-skill", "--dir", str(target))
    path = target / "SKILL.md"
    assert code == 0 and out.strip() == str(path)
    text = path.read_text(encoding="utf-8")
    assert text == skill.SKILL_MD and text.startswith("---\nname: triage\ndescription:")

    assert run("install-skill", "--dir", str(target))[0] == 0  # identical: fine

    path.write_text("my own edits", encoding="utf-8")
    code, _, err = run("install-skill", "--dir", str(target))
    assert code == 1 and "--force" in err
    assert path.read_text(encoding="utf-8") == "my own edits"
    assert run("install-skill", "--dir", str(target), "--force")[0] == 0
    assert path.read_text(encoding="utf-8") == skill.SKILL_MD


def test_install_skill_default_dir_is_under_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    path = skill.install_skill()
    assert path == tmp_path / ".claude" / "skills" / "triage" / "SKILL.md" and path.exists()


def test_skill_content():
    lines = skill.SKILL_MD.splitlines()
    assert len(lines) <= 80
    for needle in ("triage claim", "triage done", "triage note", "triage release", "triage add", "--json", "triage config get", "bounced"):
        assert needle in skill.SKILL_MD


def test_no_command_launches_tui(monkeypatch, repo):
    import sys
    import types

    calls = []
    app = types.ModuleType("triage.tui.app")
    app.run = lambda repo=None: calls.append(repo)
    monkeypatch.setitem(sys.modules, "triage.tui.app", app)
    monkeypatch.chdir(repo)
    assert main([]) == 0
    assert main(["tui", "--repo", str(repo)]) == 0
    assert calls == [None, str(repo)]
