"""Where the recognition model runs in the member app, and when it starts
(web/recognition.js, web/social/scan.js).

The owner's iPhone froze the moment the capture flow opened, from "+" and
from "Scan a cat" alike (2026-11-13 and again on the 14th, after the first
fix, which was for another cause). The flow started the model inside the
tap, and starting a 30 MB model on the page's own thread stops every touch
for seconds: about five, measured in this browser slowed four times. The
model now lives in the runtime's worker and starts after the screen has
arrived.

The real model is 40 MB and is not served here, so a stand-in for the
runtime's script records how it was started. The worker mode itself was
checked by hand with the published model (same scores either way)."""

import hashlib
import json

from .localapp import ADMIN, COLLABORATOR
from .test_screens import go

MODEL = b"not a model"
VERSION = "stand-in"
MANIFEST = {
    "version": VERSION,
    "inputSize": 224,
    "file": f"/model/{VERSION}/model.onnx",
    "bytes": len(MODEL),
    "sha256": hashlib.sha256(MODEL).hexdigest(),
    "runtime": {
        "name": "onnxruntime-web",
        "version": "0",
        "script": f"/model/{VERSION}/ort.wasm.min.js",
        "wasmPath": f"/model/{VERSION}/",
    },
    "thresholds": None,
}
# The runtime, as far as recognition.js meets it. `refuse`: starting in a
# worker fails, as on a browser that cannot make one.
RUNTIME = """
window.ortStarts = [];
window.ort = {
  env: { wasm: {} },
  Tensor: class { constructor(type, data) { this.data = data; } },
  InferenceSession: { create: async (bytes) => {
    const how = { at: performance.now(), worker: window.ort.env.wasm.proxy === true, files: window.ort.env.wasm.wasmPaths, bytes: bytes.byteLength };
    window.ortStarts.push(how);
    if (how.worker && REFUSE) throw new Error("no worker here");
    return { run: async () => ({ embedding: { data: new Float32Array(8).fill(0.5) } }) };
  } },
};
"""


def with_a_model(page, refuse=False):
    files = {
        "manifest.json": ("application/json", json.dumps(MANIFEST).encode()),
        "model.onnx": ("application/octet-stream", MODEL),
        "ort.wasm.min.js": (
            "text/javascript",
            RUNTIME.replace("REFUSE", "true" if refuse else "false").encode(),
        ),
    }

    def serve(route):
        kind, body = files[route.request.url.split("/")[-1].split("?")[0]]
        route.fulfill(status=200, content_type=kind, body=body)

    page.context.route("**/model/**", serve)
    page.reload()


def started(page):
    page.wait_for_function("window.ortStarts && window.ortStarts.length > 0")
    return page.evaluate("window.ortStarts[0]")


def test_the_flow_opens_first_and_the_model_starts_in_a_worker_after(open_member_app):
    page = open_member_app(COLLABORATOR, wait=None)
    with_a_model(page)
    page.wait_for_selector("[data-screen=frame]")
    page.wait_for_selector("article.post")
    tapped = page.evaluate("performance.now()")
    page.get_by_role("button", name="Scan a cat").click()
    page.wait_for_selector(".scan[data-step=camera]")
    # The screen is there, and nothing of the model has been touched yet.
    assert page.evaluate("!window.ort && ![...document.scripts].some((s) => s.src.includes('/model/'))")
    start = started(page)
    assert start["worker"] is True
    # Well after the tap: the opening animation is over.
    assert start["at"] - tapped >= 900
    # A whole address, which the runtime's worker (made from a blob) needs.
    assert start["files"] == page.evaluate("location.origin") + f"/model/{VERSION}/"
    assert start["bytes"] == len(MODEL)


def test_the_plus_button_opens_the_post_page_before_the_model_too(open_member_app):
    page = open_member_app(COLLABORATOR, wait=None)
    with_a_model(page)
    page.wait_for_selector("article.post")
    page.get_by_role("button", name="New post").click()
    page.get_by_role("heading", name="New post").wait_for()
    assert page.evaluate("!window.ort")
    assert started(page)["worker"] is True


def test_a_phone_that_cannot_start_the_worker_stops_trying(open_member_app):
    page = open_member_app(COLLABORATOR, wait=None)
    with_a_model(page, refuse=True)
    page.wait_for_selector("article.post")
    page.get_by_role("button", name="Scan a cat").click()
    assert started(page)["worker"] is True
    page.wait_for_function("() => localStorage.getItem('bgucats.modelWorker.failed') !== null")
    # The flow is whole without the model: the camera page is there.
    page.wait_for_selector(".scan[data-step=camera]")
    # From the next launch the model runs on the page's thread, as the
    # desk's does, still only after the screen has arrived.
    page.locator(".camera-bar").get_by_role("button", name="Close").click()
    page.wait_for_selector(".scan", state="detached")
    page.reload()
    page.wait_for_selector("[data-screen=frame]")
    page.get_by_role("button", name="Scan a cat").click()
    page.wait_for_selector(".scan")
    assert started(page)["worker"] is False


def test_the_desk_keeps_its_model_on_the_page(open_app):
    page = open_app(ADMIN)
    with_a_model(page)
    go(page, "queue", "")
    assert started(page)["worker"] is False
