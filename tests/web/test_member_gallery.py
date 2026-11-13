"""The gallery and a cat's page (E4): every cat in two columns of photos,
searched and sorted on the phone, and the page a photo opens. The seeded
campus has three cats: Mitzi (posted once by the collaborator, liked by the
admin), Shunra and Pilpel."""

from .localapp import ADMIN, COLLABORATOR


def gallery(open_member_app, email=COLLABORATOR):
    page = open_member_app(email)
    page.wait_for_selector("article.post")
    page.get_by_role("button", name="Open the cat gallery").click()
    page.wait_for_selector("[data-page=gallery][data-state=shown]")
    page.wait_for_selector(".gallery-tile")
    return page


def reading_order(page):
    """The cats as the eye reads them: across the two columns, row by row."""
    return page.evaluate(
        """(() => {
          const columns = [...document.querySelectorAll('.gallery-column')]
            .map((c) => [...c.querySelectorAll('.gallery-tile')].map((t) => t.getAttribute('aria-label').replace('Open ', '')));
          const out = [];
          for (let i = 0; i < Math.max(...columns.map((c) => c.length)); i++)
            for (const column of columns) if (column[i]) out.push(column[i]);
          return out;
        })()"""
    )


def test_the_gallery_shows_every_cat_in_two_columns(open_member_app, shot):
    page = gallery(open_member_app)
    assert sorted(reading_order(page)) == ["Mitzi", "Pilpel", "Shunra"]
    assert page.locator(".gallery-column").count() == 2
    # The highest grade first: Mitzi is the only cat anyone met in the app.
    assert reading_order(page)[0] == "Mitzi"
    assert page.locator(".gallery").get_attribute("data-sort") == "gpa"
    page.wait_for_function(
        "[...document.querySelectorAll('.gallery-tile img')].every(i => i.complete && i.naturalWidth)"
    )
    page.wait_for_function(
        "Math.abs(document.querySelector('[data-page=gallery]').getBoundingClientRect().x) < 1"
    )
    shot(page, "member-gallery")


def test_the_search_bar_on_the_feed_opens_the_gallery_ready_to_type(open_member_app):
    page = open_member_app(COLLABORATOR)
    page.wait_for_selector("article.post")
    page.get_by_role("button", name="Search cats").click()
    page.wait_for_selector("[data-page=gallery][data-state=shown]")
    page.wait_for_function("document.activeElement?.type === 'search'")


def test_searching_narrows_the_cats_by_name(open_member_app):
    page = gallery(open_member_app)
    field = page.get_by_role("searchbox", name="Search cats")
    field.fill("SHU")  # whatever the capitals
    page.wait_for_function("document.querySelectorAll('.gallery-tile').length === 1")
    assert reading_order(page) == ["Shunra"]
    field.fill("zebra")
    page.get_by_text("No cat called “zebra”.").wait_for()
    field.fill("")
    page.wait_for_function("document.querySelectorAll('.gallery-tile').length === 3")


def test_the_cats_can_be_sorted(open_member_app, shot):
    page = gallery(open_member_app)
    page.get_by_role("button", name="Sort cats").click()
    menu = page.get_by_role("menu", name="Sort cats by")
    assert [b.inner_text().strip() for b in menu.get_by_role("menuitemradio").all()] == [
        "Highest GPA",
        "Recently seen",
        "Most posts",
        "Newest on campus",
        "Name A–Z",
    ]
    assert menu.get_by_role("menuitemradio", name="Highest GPA").get_attribute("aria-checked") == "true"
    shot(page, "member-gallery-sort")
    menu.get_by_role("menuitemradio", name="Name A–Z").click()
    page.wait_for_selector(".gallery[data-sort=name]")
    assert reading_order(page) == ["Mitzi", "Pilpel", "Shunra"]
    # It is still the choice when the gallery is opened again.
    page.get_by_role("button", name="Back").click()
    page.locator("[data-page=gallery]").wait_for(state="detached")
    page.get_by_role("button", name="Open the cat gallery").click()
    page.wait_for_selector(".gallery[data-sort=name]")


def test_a_photo_opens_the_cat_s_page(open_member_app, shot):
    page = gallery(open_member_app)
    page.get_by_role("button", name="Open Mitzi").click()
    page.wait_for_selector("[data-page=cat][data-state=shown]")
    cat = page.locator("[data-page=cat]")
    assert cat.locator("h1").inner_text() == "Mitzi"
    assert cat.locator(".cat-named").inner_text() == "Named by the people who look after the cats"
    numbers = dict(
        zip(
            cat.locator(".cat-number-label").all_inner_texts(),
            cat.locator(".cat-number-value").all_inner_texts(),
            strict=True,
        )
    )
    assert (numbers["Post"], numbers["Like"]) == ("1", "1")
    assert numbers["Last seen"] != "—"
    assert cat.locator(".cat-met").inner_text() == "You met this cat once."
    # Who posted it lately.
    recent = cat.get_by_role("region", name="Recent posts")
    recent.locator(".cat-post-who").first.wait_for()
    assert recent.locator(".cat-post-who").all_inner_texts() == ["collaborator"]
    # Its photos, one at a time, counted on the glass.
    page.wait_for_function(
        "[...document.querySelectorAll('[data-page=cat] .cat-photos img')].some(i => i.complete && i.naturalWidth)"
    )
    assert cat.locator(".cat-photos .photo-count").inner_text().startswith("1/")
    page.wait_for_function(
        "Math.abs(document.querySelector('[data-page=cat]').getBoundingClientRect().x) < 1"
    )
    shot(page, "member-cat")
    # Back to the gallery it came from, then to the feed.
    page.locator("[data-page=cat]").get_by_role("button", name="Back").click()
    page.locator("[data-page=cat]").wait_for(state="detached")
    assert page.locator("[data-page=gallery]").count() == 1


def test_a_cat_nobody_has_met_or_posted_says_so(open_member_app):
    page = gallery(open_member_app, ADMIN)
    page.get_by_role("button", name="Open Pilpel").click()
    cat = page.locator("[data-page=cat]")
    cat.locator("h1").wait_for()
    assert cat.locator(".cat-met").inner_text() == "You haven't met this cat yet."
    assert cat.locator(".cat-number-value").all_inner_texts()[:2] == ["0", "0"]
    assert cat.get_by_role("region", name="Recent posts").count() == 0


def test_a_cats_grade_is_on_its_page_and_a_cat_nobody_met_has_a_dash(open_member_app):
    """The grade is worked out from how many people met the cat lately
    (B7b): the seeded collaborator met and posted Mitzi, so she is the most
    popular cat and reads 4.0; nobody met Shunra in the app."""
    page = gallery(open_member_app)
    page.get_by_role("button", name="Open Mitzi").click()
    page.wait_for_selector("[data-page=cat][data-state=shown]")
    chip = page.locator("[data-page=cat] .cat-gpa")
    assert chip.inner_text().split() == ["GPA", "4.0", "/", "4"]
    assert chip.get_attribute("aria-label") == "GPA 4.0 out of 4"

    # Going back, the page slides away as the element it was: until
    # 2026-11-13 it was removed and made again for the slide, and asked the
    # server for the cat a second time.
    page.evaluate("document.querySelector('[data-page=cat]').dataset.mark = 'mitzi'")
    asked = []
    page.on("request", lambda r: "/api/v1/cats/" in r.url and asked.append(r.url))
    page.locator("[data-page=cat]").get_by_role("button", name="Back").click()
    assert page.evaluate(
        "[...document.querySelectorAll('[data-page=cat]')].map(e => e.dataset.mark + ':' + e.dataset.state)"
    ) == ["mitzi:leaving"]
    page.wait_for_function("document.querySelectorAll('[data-page=cat]').length === 0")
    assert asked == []
    page.get_by_role("button", name="Open Shunra").click()
    page.locator("[data-page=cat] h1", has_text="Shunra").wait_for()
    chip = page.locator("[data-page=cat] .cat-gpa")
    assert chip.locator(".cat-gpa-value").inner_text() == "\u2014"
    assert chip.get_attribute("aria-label") == "No GPA yet: nobody met this cat lately"

