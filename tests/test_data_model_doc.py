"""docs/data-model.md names every key prefix and sort key that src/ writes.

A new kind of item that is not in the catalogue fails here, so the file
stays the one place that lists them (docs/app-plan/, milestone F2).
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOC = (REPO / "docs" / "data-model.md").read_text()

# "SESSION#", "PREDICTION#" ... in a string literal; "META", "PICK" ... as an SK.
PREFIX = re.compile(r"""["']([A-Z][A-Z_]+#)""")
SORT_KEY = re.compile(r"""["']SK["']\s*:\s*f?["']([A-Z][A-Z_]*)["'#{]""")


def source():
    for path in sorted((REPO / "src").rglob("*.py")):
        yield path, path.read_text()


def test_every_key_prefix_in_the_code_is_in_the_catalogue():
    missing = {
        f"{prefix} ({path.relative_to(REPO)})"
        for path, text in source()
        for prefix in PREFIX.findall(text)
        if f"`{prefix}" not in DOC
    }
    assert not missing, f"docs/data-model.md does not name: {sorted(missing)}"


def test_every_sort_key_in_the_code_is_in_the_catalogue():
    missing = {
        f"{key} ({path.relative_to(REPO)})"
        for path, text in source()
        for key in SORT_KEY.findall(text)
        if f"`{key}" not in DOC
    }
    assert not missing, f"docs/data-model.md does not name: {sorted(missing)}"


def test_the_check_finds_what_it_is_meant_to():
    # The patterns are only worth their silence if they match the real thing.
    found = {p for _, text in source() for p in PREFIX.findall(text)}
    assert {"SESSION#", "PHOTO#", "CAT#", "ADMIN#", "STATUS#", "ENTITY#"} <= found
    keys = {k for _, text in source() for k in SORT_KEY.findall(text)}
    assert {"META", "PICK", "PROFILE", "ACTIVE_SESSION"} <= keys
