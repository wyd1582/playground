"""make scorecard — DESIGN.md §3.4 system scorecard from the registry."""
from __future__ import annotations

import sys

from campaigns.scorecard import write_scorecard
from registry import Registry


def main() -> int:
    df, text = write_scorecard(Registry())
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
