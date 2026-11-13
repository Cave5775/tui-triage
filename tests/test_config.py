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
