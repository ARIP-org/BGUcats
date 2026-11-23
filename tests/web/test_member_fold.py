"""The bars that fold while the page scrolls (#104): the tab bar, the feed's
search pill, Home's profile pill and its Friends button.

Each of them is glass (a backdrop blur). Until #104 their fold animated
layout properties (inline-size, block-size, inset-*, flex-basis), so every
frame of the 0.46 s spring was a new layout and a new blur, and on the
iPhone the fold stuttered. Now the glass changes shape by clip-path and
what is inside it moves by translate and transform; a layout property
changes, if at all, once, at the start of the fold.

Nobody can feel smoothness in CI: these tests hold the rule that makes it
possible, and leave a picture of each state in both directions."""

import re

import pytest

from .localapp import COLLABORATOR
from .test_member_home import scroll_down

# The parts that move when the bars fold, each with its two layers of
# glass (::before, the blur; ::after, the rim and the shadow).
FOLDING = [
    ".tabbar",
    ".tabbar .lens",
    ".tabbar button",
    ".tabbar .tab-label",
    ".top-buttons",
    ".search",
    ".search-words",
    ".home-top",
    ".me-pill",
    ".me-pill .me-avatar",
    ".me-words",
    ".friends-button",
    ".friends-button .icon",
    ".friends-words",
]

# A transition of any of these is a layout on every frame. "all" names them too.
LAYOUT = re.compile(
    r"^(?:all|width|height|(?:min-|max-)?(?:inline|block)-size|(?:min|max)-(?:width|height)"
    r"|flex|flex-basis|flex-grow|flex-shrink|inset|inset-.*|top|left|right|bottom"
    r"|margin|margin-.*|padding|padding-.*|border-width|border-.*-width|gap|font-size)$"
)

READ = """(selectors) => selectors.flatMap((selector) =>
  [...document.querySelectorAll(selector)].flatMap((el) =>
    [null, "::before", "::after"].map((pseudo) => {
      const s = getComputedStyle(el, pseudo);
      return {
        where: selector + (pseudo || ""),
        properties: s.transitionProperty.split(",").map((p) => p.trim()),
        durations: s.transitionDuration.split(",").map((d) => d.trim()),
        animation: s.animationName,
        animationDuration: s.animationDuration,
        clip: s.clipPath,
      };
    })))"""


def open_both(open_member_app, rtl=False, **options):
    """The feed and Home, both drawn, in one tab."""
    page = open_member_app(COLLABORATOR, **options)
    page.wait_for_selector("[data-screen=frame]")
    if rtl:
        page.evaluate("document.documentElement.dir = 'rtl'")
    page.wait_for_selector("article.post")
    page.get_by_role("button", name="Home").click()
    page.wait_for_selector(".home-top .me-pill")
    page.get_by_role("button", name="Cats", exact=True).click()
    page.locator("[data-tab-page=feed]").wait_for(state="visible")
    return page


def read(page):
    return page.evaluate(READ, FOLDING)


def test_the_bars_fold_without_animating_layout(open_member_app):
    page = open_both(open_member_app)
    seen = set()
    for state in ("open", "folded"):
        if state == "folded":
            scroll_down(page, "feed")
            page.wait_for_selector(".tabbar.collapsed")
        found = read(page)
        seen |= {f["where"] for f in found}
        # Every element has "all 0s" until it says otherwise: only a
        # transition that takes time is one.
        bad = [
            (state, f["where"], p)
            for f in found
            for p, d in zip(f["properties"], f["durations"] * len(f["properties"]))
            if LAYOUT.match(p) and d != "0s"
        ]
        assert not bad, bad
    # Every part above was on the page to be read.
    assert {s for s in FOLDING} <= seen, set(FOLDING) - seen
    # And the glass still moves: by its shape, not by its size.
    found = {f["where"]: f for f in read(page)}
    for glass in (".tabbar::before", ".search::before", ".me-pill::before", ".friends-button::before"):
        assert "clip-path" in found[glass]["properties"], found[glass]
        assert found[glass]["clip"].startswith("inset("), found[glass]
    for moving in (".tabbar .lens", ".tabbar button", ".friends-button .icon"):
        assert "translate" in found[moving]["properties"], found[moving]


def test_the_rule_catches_what_it_should():
    for bad in ("inline-size", "block-size", "inset-block-end", "inset-inline-start",
                "flex-basis", "width", "margin-inline", "padding-block-start", "all"):
        assert LAYOUT.match(bad), bad
    for good in ("clip-path", "translate", "transform", "scale", "opacity", "color",
                 "background", "box-shadow", "border-radius", "visibility"):
        assert not LAYOUT.match(good), good


def test_reduce_motion_folds_at_once(open_member_app):
    page = open_both(open_member_app, reduced_motion="reduce")
    scroll_down(page, "feed")
    page.wait_for_selector(".tabbar.collapsed")
    for f in read(page):
        for p, d in zip(f["properties"], f["durations"] * len(f["properties"])):
            if p in ("clip-path", "translate", "transform"):
                assert d == "0s", f
        if f["animation"] != "none":
            assert f["animationDuration"] == "0s", f


def test_a_folded_tab_bar_is_touched_only_where_it_is_seen(open_member_app):
    """The tab bar keeps its open size and folds to a circle at its start:
    the rest of it lets touches through to the page, and the circle opens it."""
    page = open_both(open_member_app)
    scroll_down(page, "feed")
    page.wait_for_selector(".tabbar.collapsed")
    page.wait_for_timeout(600)
    bar = page.locator(".tabbar").bounding_box()
    middle = (bar["x"] + bar["width"] / 2, bar["y"] + bar["height"] / 2)
    circle = (bar["x"] + 30, bar["y"] + bar["height"] / 2)
    hit = "([x, y]) => !!document.elementFromPoint(x, y)?.closest('.tabbar')"
    assert not page.evaluate(hit, list(middle))
    assert page.evaluate(hit, list(circle))
    page.mouse.click(*circle)
    page.wait_for_selector(".tabbar:not(.collapsed)")


@pytest.mark.parametrize("direction", ["ltr", "rtl"])
def test_the_folded_and_open_bars_look_as_they_did(open_member_app, shot, direction):
    page = open_both(open_member_app, rtl=direction == "rtl")
    page.wait_for_timeout(700)
    shot(page, f"member-fold-{direction}-feed-open")
    page.get_by_role("button", name="Home").click()
    page.locator("[data-tab-page=home]").wait_for(state="visible")
    page.wait_for_timeout(700)
    shot(page, f"member-fold-{direction}-home-open")
    scroll_down(page, "home")
    page.wait_for_selector(".home-top.collapsed")
    page.wait_for_timeout(700)
    shot(page, f"member-fold-{direction}-home-folded")
    # A tap on the folded bar opens it; then back to the feed and down.
    bar = page.locator(".tabbar").bounding_box()
    x = bar["x"] + bar["width"] - 30 if direction == "rtl" else bar["x"] + 30
    page.mouse.click(x, bar["y"] + bar["height"] / 2)
    page.wait_for_selector(".tabbar:not(.collapsed)")
    page.get_by_role("button", name="Cats", exact=True).click()
    page.locator("[data-tab-page=feed]").wait_for(state="visible")
    scroll_down(page, "feed")
    page.wait_for_selector(".tabbar.collapsed")
    page.wait_for_timeout(700)
    shot(page, f"member-fold-{direction}-feed-folded")
