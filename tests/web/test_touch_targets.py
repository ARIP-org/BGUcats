"""Touch targets (E9): everything a finger presses is at least 44 px each
way, Apple's size and WCAG's (2.5.5). A control the design draws smaller
has room around it that still takes the touch (app.css, "room for a
finger"), so this measures what a press does, not what is drawn: each
control is pressed 21 px off its centre, up, down and to both sides.

Not held to it: a name inside a sentence ("collaborator", "met **Mitzi**"
in a post's heading), which WCAG excepts as inline. The photo beside the
name and the photo's menu are the 44 px ways to the same places.
"""

from .test_member_capture import frame, shoot

INLINE = ["post-name", "cat-link"]

SMALL = """(inline) => {
  const controls = [...document.querySelectorAll(
    'button, a[href], [role=button], [role=radio], [role=switch], [role=menuitem], [role=tab], label.file-shot')];
  const out = [];
  for (const e of controls) {
    const s = getComputedStyle(e);
    if (e.disabled || s.visibility === 'hidden' || s.pointerEvents === 'none' || e.tabIndex === -1) continue;
    if (inline.some((c) => e.classList.contains(c))) continue;
    if (!e.getBoundingClientRect().width) continue;
    e.scrollIntoView({ block: 'center', inline: 'center' });
    const r = e.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const hit = (x, y) => { const at = document.elementFromPoint(x, y); return !!at && (at === e || e.contains(at)); };
    if (!hit(cx, cy)) continue;  // under a sheet or another page: not pressable now
    const reach = 21;
    if (hit(cx - reach, cy) && hit(cx + reach, cy) && hit(cx, cy - reach) && hit(cx, cy + reach)) continue;
    out.push(`${Math.round(r.width)}x${Math.round(r.height)} ${e.className || e.tagName} "${(e.getAttribute('aria-label') || e.innerText || '').slice(0, 30)}"`);
  }
  return out;
}"""


def small(page, settle=700):
    page.wait_for_timeout(settle)  # a page or a sheet has finished arriving
    return page.evaluate(SMALL, INLINE)


def fresh(page):
    page.goto(page.url)
    page.wait_for_selector("[data-screen=frame]")


def test_the_feed_the_gallery_and_a_cats_page(app, open_member_app):
    page = frame(open_member_app)
    page.wait_for_selector("article.post")
    assert small(page) == []
    page.locator("article.post .photo").first.click()
    assert small(page, 450) == []
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Open the cat gallery").click()
    assert small(page) == []
    page.get_by_role("button", name="Open Mitzi").click()
    page.wait_for_selector("[data-page=cat] .poll")
    assert small(page) == []
    page.locator(".fed-card button").scroll_into_view_if_needed()
    page.locator(".fed-card button").click()
    page.get_by_role("dialog").locator(".chip").first.wait_for()
    assert small(page) == []


def test_home_the_profile_friends_and_achievements(app, open_member_app):
    page = frame(open_member_app)
    page.get_by_role("button", name="Home").click()
    page.wait_for_selector(".home-top .me-pill")
    assert small(page) == []
    page.locator(".achievements-card").click()
    page.get_by_role("dialog", name="Achievements").locator(".ach-number").wait_for()
    assert small(page) == []
    page.keyboard.press("Escape")
    page.locator(".home-top .me-pill").click()
    assert small(page) == []
    fresh(page)
    page.get_by_role("button", name="Home").click()
    page.get_by_role("button", name="Friends").first.click()
    assert small(page) == []
    page.get_by_role("button", name="Invite friends").first.click()
    assert small(page) == []


def test_the_map(app, open_member_app):
    page = frame(open_member_app)
    page.wait_for_selector("article.post")
    page.locator("article.post .photo").first.click()
    page.get_by_role("menuitem", name="Show on map").click()
    page.wait_for_selector("[data-page=map]")
    assert small(page, 900) == []


def test_every_page_of_the_capture_flow(app, open_member_app):
    page = frame(open_member_app)
    page.get_by_role("button", name="Scan a cat").click()
    page.wait_for_selector(".scan[data-step=camera]")
    assert small(page) == []
    shoot(page)
    page.wait_for_selector(".scan[data-step=which]")
    assert small(page) == []
    page.locator(".cat-grid-pick").get_by_role("button", name="Mitzi", exact=True).click()
    page.wait_for_selector(".scan .poll")
    assert small(page, 900) == []
    page.get_by_role("button", name="Create a post").click()
    assert small(page) == []
    page.get_by_role("button", name="Change").click()
    page.get_by_role("button", name="New cat").click()
    assert small(page) == []


def test_a_post_from_plus_and_its_tag_page(app, open_member_app):
    page = frame(open_member_app)
    page.get_by_role("button", name="New post").click()
    page.get_by_role("heading", name="New post").wait_for()
    assert small(page) == []
    page.get_by_role("button", name="Tag a cat").click()
    assert small(page) == []
