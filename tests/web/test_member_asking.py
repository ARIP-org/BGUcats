"""Asking the phone for the camera and for where it is (web/social/asking.js).

On the owner's iPhone, in the app installed on the home screen, the capture
flow froze every touch the moment it opened (2026-11-13): it asked for the
phone's location inside the tap that opened it, and an unanswered question
there stops the app until it is closed. A test browser never freezes, so
the phone here is one whose questions are simply never answered, and the
tests hold what the app does about it: when it asks, and that one unanswered
question is not asked again at every launch.
"""

from .localapp import COLLABORATOR
from .test_member_capture import PHOTO

# A phone that records what it was asked, and when. `location` and `camera`
# say how each question ends: "never" (unanswered), "no" (refused), or, for
# the camera, "later" (answered when the test says so).
PHONE = """
window.asked = [];
const note = (what) => window.asked.push({ what, screen: document.querySelector(".scan")?.dataset.step || null });
const mode = (key, otherwise) => localStorage.getItem("test." + key) || otherwise;
Object.defineProperty(navigator, "geolocation", { configurable: true, value: {
  getCurrentPosition: (ok, fail) => {
    note("location");
    if (mode("location", "no") === "never") return;
    setTimeout(() => fail({ code: 1 }), 0);
  },
}});
Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: {
  getUserMedia: () => {
    note("camera");
    const how = mode("camera", "no");
    if (how === "never") return new Promise(() => {});
    if (how === "later") return new Promise((_, refuse) => { window.answerCamera = () => refuse(new Error("no camera")); });
    return Promise.reject(new Error("no camera"));
  },
}});
"""


def phone(open_member_app, **modes):
    page = open_member_app(COLLABORATOR, wait=None)
    for key, value in modes.items():
        page.evaluate(f"localStorage.setItem('test.{key}', '{value}')")
    page.context.add_init_script(PHONE)
    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    return page


def asked(page):
    return page.evaluate("window.asked")


def test_the_place_is_asked_for_after_the_screen_is_drawn_and_after_the_camera(open_member_app):
    """One question at a time, and none inside the tap that opens the flow:
    the camera first, on its own page, and where the phone is only once the
    camera has answered."""
    page = phone(open_member_app, camera="later")
    page.get_by_role("button", name="Scan a cat").click()
    page.wait_for_selector(".scan[data-step=camera]")
    page.wait_for_function("window.asked.length > 0")
    page.wait_for_timeout(400)
    assert asked(page) == [{"what": "camera", "screen": "camera"}]
    page.evaluate("window.answerCamera()")
    page.wait_for_function("window.asked.length === 2")
    assert asked(page)[1] == {"what": "location", "screen": "camera"}


def test_a_post_started_with_plus_asks_for_the_place_once_its_page_is_there(open_member_app):
    page = phone(open_member_app)
    page.get_by_role("button", name="New post").click()
    page.wait_for_selector(".scan[data-step=post]")
    page.wait_for_function("window.asked.length > 0")
    # Asked with the page already drawn, never before it existed.
    assert asked(page) == [{"what": "location", "screen": "post"}]


def test_a_place_never_answered_is_not_asked_for_again_until_the_person_says_so(
    open_member_app, shot
):
    page = phone(open_member_app, location="never")
    page.get_by_role("button", name="New post").click()
    page.wait_for_function("window.asked.length > 0")
    assert page.evaluate("localStorage.getItem('bgucats.asking')") == '["location"]'

    # The app is closed with the question unanswered, and opened again.
    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    page.locator(".toast.on").get_by_text("stopped last time while asking for your location").wait_for()
    shot(page, "member-asking-location-held")
    assert page.evaluate("localStorage.getItem('bgucats.asking')") is None
    assert page.evaluate("localStorage.getItem('bgucats.notAsking')") == '["location"]'

    # The flow it was in comes back, and a new one too, without the question.
    page.get_by_role("button", name="New post").click()
    page.wait_for_selector(".scan[data-step=post]")
    page.get_by_role("button", name="Close").click()
    page.evaluate("localStorage.removeItem('bgucats.scan'); sessionStorage.removeItem('bgucats.scan')")
    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    page.get_by_role("button", name="New post").click()
    page.wait_for_selector(".scan[data-step=post]")
    page.wait_for_timeout(500)
    assert asked(page) == []

    # "Add location", turned off and on by hand, asks; an answer of any
    # kind and the app asks by itself again.
    page.evaluate("localStorage.setItem('test.location', 'no')")
    switch = page.get_by_role("switch", name="Add location")
    switch.click()
    switch.click()
    page.wait_for_function("window.asked.length === 1")
    assert asked(page)[0]["what"] == "location"
    assert page.evaluate("localStorage.getItem('bgucats.notAsking')") is None


def test_a_camera_never_answered_leaves_the_phones_own_camera_and_a_way_back(
    open_member_app, shot
):
    page = phone(open_member_app, camera="never")
    page.get_by_role("button", name="Scan a cat").click()
    page.wait_for_function("window.asked.length > 0")
    assert asked(page) == [{"what": "camera", "screen": "camera"}]

    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    page.locator(".toast.on").get_by_text("stopped last time while asking for the camera").wait_for()
    page.get_by_role("button", name="Scan a cat").click()
    page.wait_for_selector(".scan[data-step=camera]")
    page.locator(".camera-note").get_by_text("The live camera is off").wait_for()
    shot(page, "member-asking-camera-held")
    # Not asked again by itself, and the place is still asked for.
    page.wait_for_function("window.asked.length === 1")
    assert asked(page) == [{"what": "location", "screen": "camera"}]
    # The phone's own camera still takes the photo.
    page.set_input_files(".file-shot input", PHOTO)
    page.wait_for_selector(".scan[data-step=which]")


def test_the_live_camera_can_be_tried_again(open_member_app):
    page = phone(open_member_app, camera="never")
    page.get_by_role("button", name="Scan a cat").click()
    page.wait_for_function("window.asked.length > 0")
    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    page.evaluate("localStorage.setItem('test.camera', 'no')")
    page.get_by_role("button", name="Scan a cat").click()
    page.get_by_role("button", name="Try the live camera").click()
    page.wait_for_function("window.asked.some((a) => a.what === 'camera')")
    assert page.evaluate("localStorage.getItem('bgucats.notAsking')") is None
    page.get_by_text("No camera here.").wait_for()
