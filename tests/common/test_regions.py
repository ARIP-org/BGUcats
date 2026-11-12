"""web/regions.json and common.regions: the one list of campus places."""

import json
from pathlib import Path

from common import regions

FILE = Path(__file__).resolve().parents[2] / "web" / "regions.json"


def test_every_region_has_an_id_a_name_and_a_circle():
    seen = set()
    for r in regions.regions():
        assert r["id"] not in seen
        seen.add(r["id"])
        assert r["names"]["en"] and r["near"]["en"]
        assert 31 < r["lat"] < 32 and 34 < r["lon"] < 35  # Be'er Sheva
        assert 0 < r["radiusM"] <= 500
    assert regions.ids() == seen


def test_the_file_says_it_is_a_placeholder_until_the_owner_replaces_it():
    # docs/app-plan/OWNER_STEPS.md, O12. When the real places arrive, this
    # flag goes and this test with it.
    assert json.loads(FILE.read_text())["placeholder"] is True


def test_a_point_is_in_the_nearest_region_that_holds_it():
    library = next(r for r in regions.regions() if r["id"] == "library")
    assert regions.region_at(library["lat"], library["lon"]) == "library"
    assert regions.region_at(31.0, 34.0) is None


def test_feeding_spots_are_a_list():
    assert isinstance(json.loads(FILE.read_text())["feedingSpots"], list)
