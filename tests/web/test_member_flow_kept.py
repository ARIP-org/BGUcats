"""The capture flow the phone keeps between launches (web/social/scan.js).

On 2026-11-15 the owner's home-screen app froze on "Scan a cat" and on
"+", and its App info said why: the phone held a piece of a flow,
`{ step: "which", changing: true }`, written by a tap that landed after a
flow had closed. Every later tap opened that piece, the page that draws
the photo failed on its first line, and the flow stayed "open" with
nothing on screen and the app under it out of reach. The iPhone app keeps
its own storage and never had the piece.
"""

from .localapp import COLLABORATOR

TRAIL = "JSON.parse(localStorage.getItem('bgucats.trail')).map((line) => line[1])"
KEPT = "localStorage.getItem('bgucats.scan')"
# Exactly what the phone held.
THE_PIECE = '{"step":"which","changing":true}'


def test_a_piece_of_a_flow_kept_by_the_phone_is_dropped_and_the_app_works(open_member_app):
    page = open_member_app(COLLABORATOR)
    page.wait_for_selector("article.post")
    page.evaluate(f"localStorage.setItem('bgucats.scan', '{THE_PIECE}')")
    page.reload()
    page.wait_for_selector("article.post")
    # Dropped at the start, and written down.
    assert page.evaluate(KEPT) is None
    said = page.evaluate(TRAIL)
    assert any(line.startswith("a kept capture flow was not whole and was dropped") for line in said)
    # Both ways in open a new flow, and the app answers after each.
    page.get_by_role("button", name="Scan a cat").click()
    page.wait_for_selector(".scan[data-step=camera]")
    page.locator(".camera-bar").get_by_role("button", name="Close").click()
    page.wait_for_selector(".scan", state="detached")
    page.get_by_role("button", name="New post").click()
    page.get_by_role("heading", name="New post").wait_for()
    page.locator(".scan-top").get_by_role("button", name="Close").click()
    page.wait_for_selector(".scan", state="detached")
    page.locator("article.post .like").first.click()


def test_a_tap_that_lands_after_the_flow_closed_keeps_nothing(open_member_app):
    page = open_member_app(COLLABORATOR)
    page.wait_for_selector("article.post")
    page.get_by_role("button", name="New post").click()
    page.get_by_role("heading", name="New post").wait_for()
    # The button that changes the flow, held on to while the flow closes:
    # a second finger, or a tap during the page's way out.
    page.evaluate(
        "window.late = [...document.querySelectorAll('.scan button')]"
        ".find((b) => b.textContent.includes('Tag a cat'))"
    )
    assert page.evaluate("!!window.late")
    page.locator(".scan-top").get_by_role("button", name="Close").click()
    page.wait_for_selector(".scan", state="detached")
    assert page.evaluate(KEPT) is None
    page.evaluate("window.late.click()")
    page.wait_for_timeout(200)
    assert page.evaluate(KEPT) is None
    assert page.locator(".scan").count() == 0
    # And the next launch has nothing to trip over.
    page.reload()
    page.wait_for_selector("article.post")
    assert not any("kept" in line for line in page.evaluate(TRAIL)[-6:])


def test_a_page_that_cannot_be_drawn_closes_the_flow_and_says_so(open_member_app):
    page = open_member_app(COLLABORATOR)
    page.wait_for_selector("article.post")
    # A flow that looks whole and still cannot be drawn: whatever the next
    # mistake is, it must not take the app with it.
    page.evaluate(
        """localStorage.setItem('bgucats.scan', JSON.stringify({
          sessionId: '01JZ0000000000000000000BAD', entry: 'scan', step: 'which',
          shots: [{ photoId: '01JZ0000000000000000000PH1', thumb: null }],
          catId: null, isNew: false, text: '', shareRegion: true, ranked: 5, fix: null,
          proposal: { nameIdea: '', coat: null, regionId: null, traits: [] },
        }))"""
    )
    page.reload()
    page.wait_for_selector("article.post")
    page.get_by_role("button", name="Scan a cat").click()
    page.locator(".toast.on").get_by_text("could not be shown").wait_for()
    assert page.locator(".scan").count() == 0
    assert page.evaluate(KEPT) is None
    assert any(
        line.startswith("the capture flow could not be drawn and was closed")
        for line in page.evaluate(TRAIL)
    )
    # The app is there, and the flow opens new.
    page.get_by_role("button", name="Scan a cat").click()
    page.wait_for_selector(".scan[data-step=camera]")


def test_a_kept_flow_on_a_page_that_needs_a_photo_it_does_not_have_goes_back(open_member_app):
    page = open_member_app(COLLABORATOR)
    page.wait_for_selector("article.post")
    page.evaluate(
        """localStorage.setItem('bgucats.scan', JSON.stringify({
          sessionId: '01JZ0000000000000000000NOP', entry: 'scan', step: 'which', shots: [],
          catId: null, isNew: false, text: '', shareRegion: true, ranked: null, fix: null,
          proposal: { nameIdea: '', coat: null, regionId: null, traits: [] },
        }))"""
    )
    page.reload()
    page.wait_for_selector("article.post")
    page.get_by_role("button", name="Scan a cat").click()
    page.wait_for_selector(".scan[data-step=camera]")
