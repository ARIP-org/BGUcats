"""docs/privacy-data.md: what the app keeps about a person, for App Store
Connect's "App Privacy" answers (N5, O16).

The answers are in scripts/privacy_table.py beside their reasons. They
cannot drift from the code: a key `src/` writes that the script does not
classify fails here, and so does a file that is not the script's output.
"""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "privacy_table", REPO / "scripts" / "privacy_table.py"
)
privacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(privacy)


def test_every_key_the_code_writes_says_what_it_holds_about_a_person():
    missing = sorted(privacy.keys_in_code() - set(privacy.KEYS))
    assert not missing, (
        f"scripts/privacy_table.py does not classify {missing}: say which of "
        "Apple's kinds each holds about a person, or that it holds nothing"
    )


def test_no_key_is_classified_that_the_code_no_longer_writes():
    gone = sorted(set(privacy.KEYS) - privacy.keys_in_code())
    assert not gone, f"scripts/privacy_table.py still lists {gone}"


def test_the_file_is_the_scripts_output():
    assert (REPO / "docs" / "privacy-data.md").read_text() == privacy.render(), (
        "run: python scripts/privacy_table.py > docs/privacy-data.md"
    )


def test_every_kind_is_one_of_apples_and_none_is_both_collected_and_not():
    used = {kind for kinds, _ in privacy.KEYS.values() for kind in kinds}
    used |= {kind for _, kinds, _ in privacy.ELSEWHERE for kind in kinds}
    assert used == set(privacy.KINDS), sorted(used ^ set(privacy.KINDS))
    assert not set(privacy.KINDS) & set(privacy.NOT_COLLECTED)


def test_a_place_stored_to_three_decimals_is_what_apple_calls_precise():
    # Apple: "the same or greater resolution as a latitude and longitude
    # with three or more decimal places". The project rounds to exactly
    # three (CLAUDE.md, "Processing rules"), so the answer is Precise, and
    # stays so until the rounding changes.
    assert "Precise Location" in privacy.KINDS
    assert "Coarse Location" in privacy.NOT_COLLECTED
    claude = (REPO / "CLAUDE.md").read_text()
    assert "rounded to\n  3 decimals" in claude or "rounded to 3 decimals" in claude
