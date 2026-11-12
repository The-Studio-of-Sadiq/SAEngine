"""Prints the pytest files of one CI shard: ``shard_tests.py <tests dir> <shard 1..n> <n>``.

The files are sorted by size (largest first) and dealt round robin, so every shard gets a
similar share of the suite; the split is stable for a given set of files.
"""

from __future__ import annotations

import sys
from pathlib import Path


def shard(folder: Path, index: int, count: int) -> list[str]:
    files = sorted(folder.glob("test_*.py"), key=lambda p: (-p.stat().st_size, p.name))
    return [p.as_posix() for i, p in enumerate(files) if i % count == index - 1]


if __name__ == "__main__":
    tests, index, count = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    if not 1 <= index <= count:
        raise SystemExit(f"shard {index} is not in 1..{count}")
    print(" ".join(shard(tests, index, count)))
