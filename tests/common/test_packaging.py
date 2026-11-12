"""src/common reaches exactly the Lambdas that import it.

A function that imports `common` and is built without it fails on its first
call in AWS, not in a test: pytest finds src/common on its path either way.
A function built with it that does not use it is redeployed by every change
to src/common for nothing.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MAKEFILE = (REPO / "Makefile").read_text()


def build_recipe(function):
    match = re.search(
        rf"^build-{function}:\n((?:\t.*\n)+)", MAKEFILE, flags=re.MULTILINE
    )
    assert match, f"no build-{function} target in the Makefile"
    return match.group(1)


def imports_common(function):
    pattern = re.compile(r"^\s*(from common[ .]|import common\b)", re.MULTILINE)
    return any(
        pattern.search(path.read_text())
        for path in (REPO / "src" / function).glob("*.py")
    )


def functions():
    return sorted(
        path.name
        for path in (REPO / "src").iterdir()
        if path.is_dir() and path.name != "common" and (path / "__init__.py").exists()
    )


def test_every_function_has_a_build_target():
    for function in functions():
        build_recipe(function)


def test_common_is_copied_into_exactly_the_functions_that_import_it():
    for function in functions():
        copies = f"$(call copy-common,{function})" in build_recipe(function)
        assert copies == imports_common(function), function


def test_the_admin_api_uses_it():
    # The first user, since 2026-11-12. If this ever fails, the test above
    # has nothing left to check.
    assert imports_common("admin")


def test_common_imports_nothing_from_a_function():
    for path in (REPO / "src" / "common").glob("*.py"):
        for function in functions():
            assert not re.search(
                rf"^\s*(from|import) {function}\b", path.read_text(), re.MULTILINE
            ), f"{path.name} imports {function}"


def test_the_campus_places_go_with_the_shared_code():
    # common.regions reads regions.json from beside itself in a Lambda.
    recipe = re.search(r"^copy-common = (.*)$", MAKEFILE, flags=re.MULTILINE).group(1)
    assert "web/regions.json" in recipe
