"""Amue KeyFlow entry point."""

from __future__ import annotations

import sys


def main() -> int:
    from app.application import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
