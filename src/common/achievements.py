"""The rules of achievements: web/achievements.json, the one list of them
(docs/app-plan/01-product.md, "The rules", D11). The events Lambda counts by
the same file; it ships without src/common and reads it itself.
"""

import json
from functools import lru_cache
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# Beside this module in a Lambda's package (the Makefile's copy-common);
# in web/ in the repository.
_CANDIDATES = (_HERE / "achievements.json", _HERE.parents[1] / "web" / "achievements.json")


@lru_cache(maxsize=1)
def rules():
    for path in _CANDIDATES:
        if path.exists():
            return json.loads(path.read_text())
    raise FileNotFoundError("achievements.json is not beside common/ nor in web/")


def level_of(points):
    """{level, from, next}: the level these points are at, the points it
    starts at, and the points the next one starts at (None at the top)."""
    starts = rules()["levels"]
    level = max(n for n, start in enumerate(starts, 1) if points >= start)
    return {
        "level": level,
        "from": starts[level - 1],
        "next": starts[level] if level < len(starts) else None,
    }
