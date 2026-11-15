# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/Cave5775/tui-triage/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/Cave5775/tui-triage/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Cave5775/tui-triage/releases/tag/v0.1.0
