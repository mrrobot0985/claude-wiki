#!/usr/bin/env python3
"""Regenerate shell completion scripts for claude-wiki.

This script introspects the live argparse parser (the same one the CLI uses)
and writes bash, zsh, and fish completion scripts to ``completions/``.
Run it whenever a subcommand or flag is added.

Usage:
    python scripts/generate_completions.py
    python scripts/generate_completions.py --check   # exit 0 only if no drift
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from claude_wiki._completions import COMPLETION_NAMES, generate_all

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "completions"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate claude-wiki shell completion scripts"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit with status 1 if the committed scripts differ from generated ones",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Directory to write scripts to (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)

    if args.check:
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            generated = Path(tmpdir)
            generate_all(generated)
            drift = False
            for name in COMPLETION_NAMES:
                expected = args.output / name
                actual = generated / name
                if not expected.exists():
                    print(f"missing committed script: {expected}", file=sys.stderr)
                    drift = True
                    continue
                if expected.read_bytes() != actual.read_bytes():
                    print(f"drift detected: {expected}", file=sys.stderr)
                    drift = True
            if drift:
                return 1
            print("completion scripts are up to date")
            return 0

    generate_all(args.output)
    for name in COMPLETION_NAMES:
        print(f"wrote {args.output / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
