"""The map (E5): a drawn campus dragged with a finger, five habitats, and a
sheet that lists who lives in the chosen one. Which cats live where is the
usual place an admin gives a cat; here Mitzi and Shunra live at the
library and Pilpel has no place."""

import json
import re
from pathlib import Path

from .localapp import ADMIN, COLLABORATOR

WEB = Path(__file__).resolve().parents[2] / "web"


def settle_in(app, **where):
    for name, region in where.items():
        status, _ = app.api(
            "PATCH", f"/api/cats/{app.data['cats'][name]}", {"usualRegionId": region}, email=ADMIN
        )
        assert status == 200


def cat_page(open_member_app, name):
    page = open_member_app(COLLABORATOR)
    page.wait_for_selector("article.post")
    page.get_by_role("button", name="Open the cat gallery").click()
    page.get_by_role("button", name=f"Open {name}").click()
    page.locator("[data-page=cat] h1", has_text=name).wait_for()
    return page


def the_map(page):
    page.wait_for_selector("[data-page=map][data-state=shown]")
    page.wait_for_function("document.querySelector('[data-page=map]').getBoundingClientRect().x < 1")
    return page.locator("[data-page=map]")


def where(page):
    """The campus's offset, once it has stopped gliding."""
    read = "getComputedStyle(document.querySelector('.map-campus')).translate"
    last = None
    for _ in range(40):
        now = page.evaluate(read)
        if now == last:
            break
        last = now
        page.wait_for_timeout(120)
    # "12px 0px" is reported as "12px": a missing second value is zero.
    numbers = [float(n) for n in re.findall(r"-?[\d.]+", last)[:2]]
    return (numbers + [0.0, 0.0])[0], (numbers + [0.0, 0.0])[1]


def test_a_cats_map_button_opens_the_map_on_where_it_lives(app, open_member_app, shot):
    settle_in(app, Mitzi="library", Shunra="library")
    page = cat_page(open_member_app, "Mitzi")
    page.locator("[data-page=cat]").get_by_role("button", name="Show on map").click()
    area = the_map(page)

    sheet = area.get_by_role("region", name="Habitat")
    assert sheet.locator(".map-sheet-title").inner_text() == "Aranne Library"
    sheet.get_by_text("2 cats live here").wait_for()
    # The most popular first, with its grade; a cat nobody met has none.
    cats = sheet.locator(".map-cat")
    assert [c.locator(".map-cat-name").inner_text() for c in cats.all()] == ["Mitzi", "Shunra"]
    assert cats.nth(0).locator(".map-cat-gpa").inner_text() == "4.0"
    assert cats.nth(1).locator(".map-cat-gpa").count() == 0

    chip = area.locator(".map-chip[data-region=library]")
    assert chip.inner_text() == "Aranne Library"
    assert chip.get_attribute("aria-pressed") == "true"
    assert area.locator(".map-habitat.chosen").get_attribute("data-region") == "library"
    assert area.locator(".map-pin.chosen").count() == 2
    # The habitat is in view: its chip is on the screen, above the sheet.
    box, sheet_box = chip.bounding_box(), sheet.bounding_box()
    assert 0 < box["x"] and box["x"] + box["width"] < 390
    assert 0 < box["y"] < sheet_box["y"]
    # The map has the whole screen: the tab bar and the page's own back
    # button step aside; the way back is in the sheet.
    assert not page.locator(".tabbar").is_visible()
    page.wait_for_function("[...document.querySelectorAll('.map img')].every(i => i.complete)")
    where(page)
    shot(page, "member-map")

    # A cat in the sheet opens its page, and the map is still under it.
    cats.nth(1).click()
    page.locator("[data-page=cat] h1", has_text="Shunra").wait_for()


def test_tapping_a_habitat_chooses_it_and_brings_it_into_view(app, open_member_app, shot):
    settle_in(app, Mitzi="library")
    page = cat_page(open_member_app, "Mitzi")
    page.locator("[data-page=cat]").get_by_role("button", name="Show on map").click()
    area = the_map(page)
    before = where(page)

    area.locator(".map-chip[data-region=dorms]").click()
    sheet = area.get_by_role("region", name="Habitat")
    assert sheet.locator(".map-sheet-title").inner_text() == "Dorms"
    sheet.get_by_text("No named cats here yet. Spotted one? Scan it.").wait_for()
    assert sheet.locator(".map-cat").count() == 0
    after = where(page)
    assert after != before and after[1] < before[1]  # the dorms are further down
    box = area.locator(".map-chip[data-region=dorms]").bounding_box()
    assert 0 < box["x"] and 0 < box["y"] < sheet.bounding_box()["y"]
    shot(page, "member-map-empty")

    # "Scan it": the capture flow, from where a cat was spotted.
    sheet.get_by_role("button", name="Scan a cat").click()
    page.get_by_role("dialog", name="Scan a cat").wait_for()


def test_the_campus_is_dragged_and_stays_inside_its_edges(app, open_member_app):
    settle_in(app, Mitzi="library")
    page = cat_page(open_member_app, "Mitzi")
    page.locator("[data-page=cat]").get_by_role("button", name="Show on map").click()
    area = the_map(page)
    start = where(page)

    def drag(dx, dy):
        page.mouse.move(200, 300)
        page.mouse.down()
        for step in range(1, 9):
            page.mouse.move(200 + dx * step / 8, 300 + dy * step / 8)
        page.mouse.up()
        return where(page)

    moved = drag(-120, -90)
    assert moved[0] < start[0] and moved[1] < start[1]
    # A drag is not a tap: the library is still the chosen one.
    assert area.locator(".map-sheet-title").inner_text() == "Aranne Library"

    # However far it is pulled, the campus's edge never leaves the screen's.
    for _ in range(6):
        pulled = drag(900, 900)
    assert pulled == (0.0, 0.0)
    for _ in range(8):
        pulled = drag(-900, -900)
    assert pulled == (390 - 900, 844 - 1300)


def test_a_cat_with_no_usual_place_opens_the_whole_campus(app, open_member_app):
    page = cat_page(open_member_app, "Pilpel")
    page.locator("[data-page=cat]").get_by_role("button", name="Show on map").click()
    area = the_map(page)
    assert area.locator(".map-sheet-title").inner_text() == "BGU campus"
    area.get_by_text("Drag the map · tap a habitat to see who lives there").wait_for()
    assert area.locator(".map-habitat.chosen").count() == 0
    assert area.locator(".map-chip").count() == 5

    area.get_by_role("button", name="Close map").click()
    page.wait_for_function("document.querySelectorAll('[data-page=map]').length === 0")
    assert page.locator(".tabbar").is_visible()
    assert page.locator("[data-page=cat] h1").inner_text() == "Pilpel"


def test_show_on_map_in_a_photos_menu_opens_the_cats_habitat(app, open_member_app):
    settle_in(app, Mitzi="union")
    page = open_member_app(COLLABORATOR)
    post = page.locator("article.post").first
    post.wait_for()
    post.locator(".photo").first.click()
    page.get_by_role("menuitem", name="Show on map").click()
    area = the_map(page)
    assert area.locator(".map-sheet-title").inner_text() == "Student Union"
    area.get_by_text("1 cat lives here").wait_for()


def test_every_campus_place_has_its_drawing():
    """A place in the regions file with no area on the map could not be
    chosen, and a drawing for a place that is gone would name nothing."""
    regions = {r["id"] for r in json.loads((WEB / "regions.json").read_text())["regions"]}
    source = (WEB / "social" / "map.js").read_text()
    block = source[source.index("export const HABITATS = {") : source.index("const GREENS")]
    drawn = set(re.findall(r"^  (\w+): \{$", block, flags=re.MULTILINE))
    assert drawn == regions
