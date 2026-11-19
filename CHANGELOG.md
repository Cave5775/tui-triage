# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-11-18

### Added
- Agents can ask a multiple-choice question: `triage ask ID "question" --option A --option B [--multi] [--wait]`. The item shows a `?` in the list, the question appears in the detail pane, and `r` opens an answer dialog (pick an option, tick several, or type your own answer). `triage show` returns the open question and the latest answer. `--wait` exits `3` when no answer came.
- Sort orders: priority (the manual order), last activity, newest, oldest and item number. `o` / `O` cycle them in the TUI, the `ui.sort` setting picks the starting order, and `triage list --sort` gives one list across statuses. `J` / `K` reorder only in the priority sort.
### Changed
- The agent flag is now a "taken by" tag shown as plain text (`agent`, the agent's name, or `user`) instead of a flag symbol, and only while an item is taken. The edit form switches it between none, agent and user, and an item tagged `user` is refused for every agent command (`triage next` skips it). New `triage tag ID none|agent|user` for the user.
- The agent skill mentions `triage ask` and the `user` tag; reinstall it with `triage install-skill --force`.

## [0.1.1] - 2026-11-15

First public release on PyPI.

### Fixed
- `triage config set` and the settings screen crashed with a `TypeError` on Python 3.11 and 3.12.

## [0.1.0] - 2026-11-15

Tagged but not published: its release stopped at the Python 3.11/3.12 test failures fixed in 0.1.1.

- Keyboard-driven TUI board per git repository (Inbox → Todo → Doing → Review → Done), with live updates.
- `triage` CLI for coding agents, with JSON output and a permission model that keeps the human in charge.
- `triage install-skill` installs a Claude Code skill that teaches agents to use the board.
- Customisable keybindings and settings in `~/.triage/config.toml`.

[Unreleased]: https://github.com/Cave5775/tui-triage/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Cave5775/tui-triage/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/Cave5775/tui-triage/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Cave5775/tui-triage/releases/tag/v0.1.0
