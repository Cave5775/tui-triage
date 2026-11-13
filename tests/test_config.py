import tomllib

import pytest

from triage import config
from triage.config import ConfigError, get_config, parse_value, set_value


def test_defaults():
    cfg = get_config()
    assert cfg["agent.finish_status"] == "review"
    assert cfg["agent.pickup_statuses"] == ["todo"]


def test_global_and_board_override_roundtrip():
    set_value("agent.finish_status", "done")
    set_value("agent.can_edit", True, board_id="b1")
    set_value("agent.pickup_statuses", ["inbox", "todo"], board_id="b1")
    assert get_config()["agent.finish_status"] == "done"
    assert get_config()["agent.can_edit"] is False
    b1 = get_config("b1")
    assert b1["agent.can_edit"] is True and b1["agent.finish_status"] == "done"
    assert b1["agent.pickup_statuses"] == ["inbox", "todo"]
    assert config.overrides("b1") == {"agent.can_edit": True, "agent.pickup_statuses": ["inbox", "todo"]}
    set_value("agent.can_edit", None, board_id="b1")
    assert "agent.can_edit" not in config.overrides("b1")


def test_validation():
    with pytest.raises(ConfigError):
        set_value("agent.finish_status", "doing")
    with pytest.raises(ConfigError):
        set_value("nope.key", 1)
    assert parse_value("agent.can_create", "off") is False
    assert parse_value("ui.poll_seconds", "0.5") == 0.5
    assert parse_value("agent.pickup_statuses", "inbox, todo") == ["inbox", "todo"]
    with pytest.raises(ConfigError):
        parse_value("agent.pickup_statuses", "done")


def test_bad_file_value_falls_back(triage_home):
    triage_home.mkdir(parents=True, exist_ok=True)
    (triage_home / "config.toml").write_text('[agent]\nfinish_status = "weird"\n')
    assert get_config()["agent.finish_status"] == "review"


# ---- set_value keeps the rest of the file --------------------------------------------------

COMMENTED = """\
# my notes about triage
[agent]
# Where `triage done` sends an item the agent finished
finish_status = "review"  # keep it safe
can_edit = false

[ui]
poll_seconds = 1.0

# ---- keybindings
[keys]
# Quit
quit = "q"
help = "?"

[boards.myrepo-1a2b3c4d.agent]
# board note
can_edit = true
"""


def _write(triage_home, text):
    triage_home.mkdir(parents=True, exist_ok=True)
    path = triage_home / "config.toml"
    path.write_text(text, encoding="utf-8", newline="")
    return path


def test_set_value_replaces_one_line_and_keeps_comments_and_keys(triage_home):
    path = _write(triage_home, COMMENTED)
    set_value("agent.finish_status", "done")
    text = path.read_text(encoding="utf-8")
    assert text == COMMENTED.replace('finish_status = "review"  # keep it safe', 'finish_status = "done"  # keep it safe')
    assert get_config()["agent.finish_status"] == "done"


def test_set_value_appends_a_missing_key_to_its_table(triage_home):
    path = _write(triage_home, COMMENTED)
    set_value("agent.can_archive", True)
    text = path.read_text(encoding="utf-8")
    assert text.replace("can_archive = true\n", "", 1) == COMMENTED
    lines = text.splitlines()
    assert lines.index("can_archive = true") == lines.index("can_edit = false") + 1  # inside [agent], after its last key
    set_value("ui.confirm_delete", False)
    assert path.read_text(encoding="utf-8").count("[ui]") == 1
    assert get_config()["ui.confirm_delete"] is False and get_config()["agent.can_archive"] is True


def test_set_value_creates_a_missing_table_at_the_end(triage_home):
    path = _write(triage_home, "# only a comment\n[agent]\ncan_edit = true\n")
    set_value("ui.poll_seconds", 2.5)
    assert path.read_text(encoding="utf-8") == "# only a comment\n[agent]\ncan_edit = true\n\n[ui]\npoll_seconds = 2.5\n"


def test_set_value_creates_the_file_when_there_is_none(triage_home):
    set_value("agent.can_edit", True)
    assert (triage_home / "config.toml").read_text(encoding="utf-8") == "[agent]\ncan_edit = true\n"


def test_set_value_unset_removes_only_that_line(triage_home):
    path = _write(triage_home, COMMENTED)
    set_value("agent.can_edit", None)
    assert path.read_text(encoding="utf-8") == COMMENTED.replace("can_edit = false\n", "", 1)
    assert get_config()["agent.can_edit"] is False
    set_value("agent.can_archive", None)  # not there: nothing changes
    assert path.read_text(encoding="utf-8") == COMMENTED.replace("can_edit = false\n", "", 1)


def test_set_value_per_board_tables(triage_home):
    path = _write(triage_home, COMMENTED)
    set_value("agent.can_edit", False, board_id="myrepo-1a2b3c4d")
    text = path.read_text(encoding="utf-8")
    assert text == COMMENTED.replace("# board note\ncan_edit = true", "# board note\ncan_edit = false")
    set_value("agent.finish_status", "done", board_id="myrepo-1a2b3c4d")
    assert config.overrides("myrepo-1a2b3c4d") == {"agent.can_edit": False, "agent.finish_status": "done"}
    set_value("ui.poll_seconds", 3.0, board_id="other.repo-1")  # a new board table; the id needs quoting
    text = path.read_text(encoding="utf-8")
    assert '[boards."other.repo-1".ui]\npoll_seconds = 3.0\n' in text
    assert config.get_config("other.repo-1")["ui.poll_seconds"] == 3.0
    assert text.startswith("# my notes about triage\n")
    assert '[keys]\n# Quit\nquit = "q"\nhelp = "?"\n' in text


def test_set_value_never_touches_the_keys_table(triage_home):
    path = _write(triage_home, COMMENTED)
    for key, value in (("agent.finish_status", "done"), ("ui.confirm_delete", False), ("agent.can_edit", None)):
        set_value(key, value)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["keys"] == {"quit": "q", "help": "?"}
    assert config.keys_table() == {"quit": "q", "help": "?"}


def test_set_value_keeps_crlf_line_endings(triage_home):
    path = _write(triage_home, COMMENTED.replace("\n", "\r\n"))
    set_value("agent.can_archive", True)
    raw = path.read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n") and b"can_archive = true\r\n" in raw


def test_set_value_falls_back_to_a_rewrite_when_the_file_cannot_be_edited_in_place(triage_home):
    # a dotted key at the top level defines [agent] too: appending an [agent] table would be invalid TOML
    path = _write(triage_home, 'agent.can_edit = true\n# note\n')
    set_value("agent.finish_status", "done")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data == {"agent": {"can_edit": True, "finish_status": "done"}}
    # a multi-line array value is not edited line by line either
    path = _write(triage_home, '[agent]\npickup_statuses = [\n  "todo",\n]\n')
    set_value("agent.pickup_statuses", ["inbox", "todo"])
    assert config.get_config()["agent.pickup_statuses"] == ["inbox", "todo"]


def test_set_value_still_rejects_an_invalid_file(triage_home):
    _write(triage_home, "[agent\nbroken")
    with pytest.raises(ConfigError):
        set_value("agent.can_edit", True)


def test_triage_config_env_var_picks_the_file(triage_home, tmp_path, monkeypatch):
    other = tmp_path / "other.toml"
    other.write_text('[agent]\nfinish_status = "done"\n', encoding="utf-8")
    assert get_config()["agent.finish_status"] == "review"
    monkeypatch.setenv("TRIAGE_CONFIG", str(other))
    assert config.config_path() == other
    assert get_config()["agent.finish_status"] == "done"
    set_value("agent.can_edit", True)
    assert "can_edit = true" in other.read_text(encoding="utf-8")
    assert not (triage_home / "config.toml").exists()


def test_init_config_refuses_to_overwrite_unless_forced(triage_home):
    path = config.init_config()
    assert path == triage_home / "config.toml"
    with pytest.raises(ConfigError, match="already exists"):
        config.init_config()
    path.write_text("# mine\n", encoding="utf-8")
    config.init_config(force=True)
    assert path.read_text(encoding="utf-8").startswith("# triage-board configuration")
