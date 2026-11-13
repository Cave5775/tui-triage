"""Command-line interface (agent + scripting). Implemented in the CLI phase."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    print("triage: CLI not implemented yet", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
