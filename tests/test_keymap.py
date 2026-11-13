"""The configurable keymap: key-name normalisation, overlay, validation, hints and the generated config."""

from __future__ import annotations

import tomllib

import pytest
from textual.binding import Binding

from triage import config
from triage.tui import keys
from triage.tui.keys import (
    COMMANDS,
    Command,
    KeyNameError,
    build_keymap,
    default_keymap,
    display_key,
    find_conflicts,
    normalize_key,
    parse_keys,
)


# ---- key names ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("?", "question_mark"), ("/", "slash"), (",", "comma"), ("+", "plus"), ("-", "minus"), ("=", "equals_sign"),
        (" ", "space"), ("space", "space"), ("a", "a"), ("D", "D"), ("1", "1"), ("#", "number_sign"),
        ("ctrl+d", "ctrl+d"), ("Ctrl+D", "ctrl+d"), ("CTRL+shift+x", "ctrl+shift+x"), ("shift+d", "D"),
        ("down", "down"), ("Esc", "escape"), ("return", "enter"), ("pgdn", "pagedown"), ("shift+tab", "shift+tab"),
        ("question_mark", "question_mark"), ("f5", "f5"), ("ctrl++", "ctrl+plus"), ("alt+enter", "alt+enter"),
    ],
)
def test_normalize_key(text, expected):
    assert normalize_key(text) == expected


@pytest.mark.parametrize("bad", ["", "  ", "ctr+d", "blorp", "ctrl+", "+x", "ctrl+blorp"])
def test_normalize_key_rejects_nonsense(bad):
    with pytest.raises(KeyNameError):
        normalize_key(bad)


@pytest.mark.parametrize(
    "name, shown",
    [("question_mark", "?"), ("slash", "/"), ("comma", ","), ("plus", "+"), ("equals_sign", "="), ("space", "space"),
     ("escape", "esc"), ("down", "↓"), ("ctrl+d", "ctrl+d"), ("ctrl+question_mark", "ctrl+?"), ("j", "j"),
     ("pagedown", "PgDn")],
)
def test_display_key_goes_back_to_what_people_type(name, shown):
    assert display_key(name) == shown


def test_every_default_key_round_trips_through_its_display_and_config_forms():
    for c in COMMANDS:
        for k in c.keys:
            assert normalize_key(keys.config_key(k)) == k, (c.name, k)
            assert normalize_key(k) == k, (c.name, k)


def test_parse_keys_accepts_lists_commas_and_the_comma_key():
    assert parse_keys("j, down") == ("j", "down")
    assert parse_keys("j,down,j") == ("j", "down")  # duplicates collapse
    assert parse_keys(["?", "ctrl+h"]) == ("question_mark", "ctrl+h")
    assert parse_keys(",") == ("comma",)
    assert parse_keys("comma") == ("comma",)
    assert parse_keys("x, ") == ("x",)  # a trailing separator is harmless
    for bad in ("", "  ", [], [""], 5, True, ["a", 1]):
        with pytest.raises(KeyNameError):
            parse_keys(bad)


# ---- the table itself ------------------------------------------------------------------

def test_default_keymap_is_valid_and_conflict_free():
    km = default_keymap()
    assert find_conflicts(km.keys) == {}
    assert km.warning() is None
    names = [c.name for c in COMMANDS]
    assert len(names) == len(set(names))
    for c in COMMANDS:
        assert c.keys, c.name
        assert all(normalize_key(k) == k for k in c.keys), c.name


def test_tab_toggles_the_detail_pane_by_default():
    assert default_keymap().keys_for("toggle_detail") == ("tab", "shift+tab")
    assert "tab" not in default_keymap().keys_for("tab_next")


def test_shared_commands_use_one_config_entry():
    by = keys.COMMANDS_BY_NAME
    assert by["back"].actions == ("detail_back", "clear_filter")
    assert by["advance"].actions == ("advance", "restore")
    assert by["accept"].actions == ("accept", "accept_hint")
    assert by["purge"].actions == ("purge", "purge_hint")


def test_bindings_follow_the_effective_keys_and_only_special_keys_are_priority():
    km = build_keymap({"quit": "x", "toggle_detail": "tab, f2, z"})
    bound = {(b.key, b.action): b for b in keys.bindings(km)}
    assert ("x", "quit") in bound and ("q", "quit") not in bound
    assert bound[("tab", "toggle_detail")].priority
    assert bound[("f2", "toggle_detail")].priority
    assert not bound[("z", "toggle_detail")].priority  # printable: must not steal typing
    assert all(isinstance(b, Binding) for b in bound.values())


# ---- overlay and validation -------------------------------------------------------------------

def test_overlay_replaces_only_the_named_commands():
    km = build_keymap({"quit": "x, ctrl+q", "help": "F1"})
    assert km.keys_for("quit") == ("x", "ctrl+q")
    assert km.keys_for("help") == ("f1",)
    assert km.keys_for("edit") == ("e",)
    assert km.problems == [] and km.user_set == {"quit", "help"}


def test_swapping_two_keys_is_not_a_conflict():
    km = build_keymap({"quit": "e", "edit": "q"})
    assert km.problems == []
    assert (km.keys_for("quit"), km.keys_for("edit")) == (("e",), ("q",))


def test_conflict_falls_back_to_default_for_the_entry_that_collides():
    km = build_keymap({"quit": "e"})  # e is the default of edit
    assert km.keys_for("quit") == ("q",) and km.keys_for("edit") == ("e",)
    assert [p.command for p in km.problems] == ["quit"]
    assert "quit" not in km.user_set


def test_two_entries_claiming_one_key_both_fall_back():
    km = build_keymap({"quit": "x", "help": "x"})
    assert km.keys_for("quit") == ("q",) and km.keys_for("help") == ("question_mark",)
    assert {p.command for p in km.problems} == {"quit", "help"}


def test_unknown_command_is_ignored_and_reported():
    km = build_keymap({"explode": "x", "quit": "q"})
    assert [(p.command, p.unknown) for p in km.problems] == [("explode", True)]
    assert km.keys_for("quit") == ("q",)
    assert "ignored unknown explode" in km.warning()


def test_empty_and_unknown_key_values_fall_back():
    km = build_keymap({"quit": "", "edit": "blorp", "help": 7, "note": ["a", 2]})
    for name in ("quit", "edit", "help", "note"):
        assert km.keys_for(name) == keys.COMMANDS_BY_NAME[name].keys
    assert {p.command for p in km.problems} == {"quit", "edit", "help", "note"}


def test_keys_section_that_is_not_a_table_never_crashes():
    km = build_keymap("oops")
    assert km.keys_for("quit") == ("q",) and len(km.problems) == 1
    assert build_keymap(None).problems == []


def test_warning_line_names_the_commands():
    km = build_keymap({"quit": "", "edit": "nope", "ghost": "x"})
    assert km.warning() == "keys: 3 problems in config.toml — default used for quit, edit; ignored unknown ghost (see triage config keys)"
    assert build_keymap({"quit": ""}).warning() == "keys: 1 problem in config.toml — default used for quit (see triage config keys)"


def test_contexts_that_never_overlap_may_share_a_key():
    a = Command("a", ("x",), "App", "a", ("a",), contexts=("list",))
    b = Command("b", ("x",), "App", "b", ("b",), contexts=("detail",))
    c = Command("c", ("x",), "App", "c", ("c",), contexts=("list", "detail"))
    assert find_conflicts({"a": ("x",), "b": ("x",)}, (a, b)) == {}
    assert find_conflicts({"a": ("x",), "b": ("x",), "c": ("x",)}, (a, b, c)) == {"x": {"a", "b", "c"}}
    km = build_keymap({"b": "y"}, commands=(a, b))  # no conflict: b keeps its own key
    assert km.keys_for("a") == ("x",) and km.keys_for("b") == ("y",)


def test_load_keymap_reads_the_config_file(triage_home):
    assert keys.load_keymap().problems == []
    triage_home.mkdir(parents=True, exist_ok=True)
    (triage_home / "config.toml").write_text('[keys]\nquit = "x"\nghost = "y"\n', encoding="utf-8")
    km = keys.load_keymap()
    assert km.keys_for("quit") == ("x",) and "ghost" in km.warning()


def test_load_keymap_survives_a_broken_file(triage_home):
    triage_home.mkdir(parents=True, exist_ok=True)
    (triage_home / "config.toml").write_text("this is = = not toml [", encoding="utf-8")
    km = keys.load_keymap()
    assert km.keys_for("quit") == ("q",) and "not valid TOML" in km.warning()


# ---- chord prefixes -------------------------------------------------------------------------------

def test_chord_prefixes_follow_the_config_in_prompts_and_help():
    km = build_keymap({"move": "M", "archive": "x", "priority": "P"})
    assert km.first("move") == "M" and km.first("archive") == "xx"
    assert keys.chord_prompt(keys.CHORDS_BY_NAME["archive"], km) == "press x again to archive · esc cancels"
    rows = dict(dict(keys.help_sections(km))["Triage"])
    assert "M …" in rows and "x x" in rows and "P …" in rows and "m …" not in rows


# ---- hints -----------------------------------------------------------------------------------------

def test_hint_contexts_only_name_real_commands():
    for ctx, hints in keys.HINT_CONTEXTS.items():
        for h in hints:
            for c in h.commands:
                assert c in keys.COMMANDS_BY_NAME, (ctx, c)


def test_hint_entries_use_the_effective_keys():
    km = build_keymap({"edit": "x", "help": "F1"})
    ents = dict(keys.hint_entries("item", km, dest="todo"))
    assert ents["x"] == "edit" and ents["space"] == "→ todo" and "e" not in ents
    assert ents["f1"] == "help"


def test_hint_entries_omit_conditional_hints():
    km = default_keymap()
    plain = [label for _, label in keys.hint_entries("item", km, dest=None, can_undo=False)]
    assert "undo" not in plain and not any(label.startswith("→") for label in plain)
    assert "undo" in [label for _, label in keys.hint_entries("item", km, dest="doing", can_undo=True)]


def test_review_hints_put_accept_and_bounce_first():
    ents = keys.hint_entries("review", default_keymap(), dest="done")
    assert ents[:2] == [("y", "accept"), ("n", "bounce")]


def test_filter_active_prepends_clear_filter_in_list_contexts_only():
    km = default_keymap()
    assert keys.hint_entries("item", km, dest="todo", filter_active=True)[0] == ("esc", "clear filter")
    assert keys.hint_entries("detail", km, filter_active=True)[0] != ("esc", "clear filter")


def test_fit_hints_always_keeps_help():
    ents = keys.hint_entries("item", default_keymap(), dest="todo", can_undo=True)
    for width in (200, 80, 40, 20, 8, 1):
        kept, sep = keys.fit_hints(ents, width)
        assert ("?", "help") in kept, width
        total = sum(len(k) + 1 + len(v) for k, v in kept) + len(sep) * (len(kept) - 1)
        assert total <= width or len(kept) == 1, width
    kept, _ = keys.fit_hints(ents, 200)
    assert kept == ents


def test_help_sections_show_the_effective_keys():
    km = build_keymap({"quit": "x", "cursor_down": "w, down"})
    flat = {desc: key for _, rows in keys.help_sections(km) for key, desc in rows}
    assert flat["Quit"] == "x"
    assert flat["Move down (scrolls the detail pane when it has focus)"] == "w/↓"
    assert flat["jump to Inbox / Todo / Doing / Review / Done"] == "1-5"


# ---- the generated default config ---------------------------------------------------------------------

def test_generated_default_config_round_trips_through_tomllib():
    text = config.default_config_text(keys.default_keys_toml())
    data = tomllib.loads(text)
    assert set(data["keys"]) == {c.name for c in COMMANDS}
    km = build_keymap(data["keys"])
    assert km.problems == []
    assert km.keys == default_keymap().keys
    for s in config.SETTINGS:
        head, _, leaf = s.key.partition(".")
        assert data[head][leaf] == s.default, s.key
    # every setting and every command carries a comment line
    lines = text.splitlines()
    for s in config.SETTINGS:
        i = next(n for n, line in enumerate(lines) if line.startswith(s.key.partition(".")[2] + " = "))
        assert lines[i - 1].startswith("# "), s.key
    for c in COMMANDS:
        i = next(n for n, line in enumerate(lines) if line.startswith(c.name + " = "))
        assert lines[i - 1] == f"# {c.desc}", c.name


def test_a_generated_config_is_the_reference_for_the_effective_settings(triage_home):
    path = config.init_config(keys_section=keys.default_keys_toml())
    assert path == triage_home / "config.toml"
    assert config.get_config() == config.DEFAULTS
    assert keys.load_keymap().problems == []
    config.set_value("agent.finish_status", "done")
    assert config.get_config()["agent.finish_status"] == "done"
    assert tomllib.loads(path.read_text(encoding="utf-8"))["keys"]["quit"] == "q"


def test_filter_hint_never_advertises_a_printable_key():
    km = keys.build_keymap({"back": "b, escape"})
    entries = dict((label, key) for key, label in keys.hint_entries("filter", km))
    assert entries["clear filter"] == "esc"
    only_printable = keys.build_keymap({"back": "b"})
    labels = [label for _, label in keys.hint_entries("filter", only_printable)]
    assert "clear filter" not in labels


def test_noboard_context_leads_with_repo_picker():
    entries = keys.hint_entries("noboard", keys.default_keymap())
    assert entries[0] == ("R", "pick a repo")


def test_readme_custom_keys_example_is_valid():
    import re
    from pathlib import Path

    readme = Path(__file__).resolve().parent.parent / "README.md"
    block = re.search(r"```toml\n(\[keys\].*?)```", readme.read_text(encoding="utf-8"), re.S)
    assert block, "README has a [keys] example"
    table = tomllib.loads(block.group(1))["keys"]
    assert not keys.build_keymap(table).problems
