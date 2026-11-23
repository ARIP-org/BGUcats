"""The upload queue never sends a photo ahead of its encounter.

On 2026-11-23 a post "did not arrive" once in CI and once in three runs
here. The app's own account (App info, printed since that day when a
screen test fails) had the answer: `404 POST /api/encounters/{id}/media`.
The place had arrived a moment before the first photo, which starts a pass
of the queue; that pass read the encounters, then the photo and its
encounter were stored, then it read the photos, found one whose encounter
it had not seen, and sent it as a photo with no encounter to wait for. The
server said "no such encounter", the photo was given up for good and the
post waited for ever.

This drives the queue itself (web/outbox.js) in a page with no app in it,
with a stand-in for the API that only notes the order of the calls. The
first photo is stored at a chosen moment of the pass the place started:
right after its first read of the store, after its second, and so on,
each moment in turn, many times over. Whatever order the pass reads in,
one of those moments is the bad one.
"""

from .localapp import COLLABORATOR

# A pass reads the store seven times today; a few more, for a pass that
# grows.
MOMENTS = 10
TIMES_EACH = 4

RACE = """
async ([moments, times]) => {
  const { createOutbox, ulid } = await import('/outbox.js');
  const calls = [];
  const post = async (path, body) => {
    calls.push([path, body?.sessionId || null]);
    await new Promise((done) => setTimeout(done, 1));
    return path.endsWith('/media') ? { done: true } : {};
  };
  const outbox = createOutbox({ post, onChange: () => {} });

  // Every read of the store is counted, and one of them is the cue.
  let reads = 0;
  let cue = null;
  const getAll = IDBObjectStore.prototype.getAll;
  IDBObjectStore.prototype.getAll = function (...args) {
    const request = getAll.apply(this, args);
    const count = ++reads;
    request.addEventListener('success', () => cue?.(count));
    return request;
  };

  const sessions = [];
  for (let round = 0; round < moments * times; round++) {
    const moment = (round % moments) + 1;
    const sessionId = ulid();
    sessions.push(sessionId);
    let stored = null;
    const firstPhoto = () =>
      (stored ??= (async () => {
        // As the capture flow does: the encounter, then its photo.
        await outbox.addEncounter({ sessionId, open: true });
        await outbox.addItem({
          photoId: ulid(),
          sessionId,
          blob: new Blob(['x'], { type: 'image/jpeg' }),
          contentType: 'image/jpeg',
          capturedAt: new Date().toISOString(),
        });
      })());
    reads = 0;
    cue = (count) => count === moment && firstPhoto();
    // The place arrives: a pass of the queue starts, with nothing in it.
    outbox.placeEncounter(sessionId, { lat: 31.262, lon: 34.801, accuracyM: 12 });
    // A pass shorter than this moment: the photo comes after it.
    await new Promise((done) => setTimeout(done, 60));
    cue = null;
    await firstPhoto();
    const sent = () => calls.some(([path]) => path === `/encounters/${sessionId}/media`);
    for (let waited = 0; !sent() && waited < 400; waited++) {
      await new Promise((done) => setTimeout(done, 10));
    }
  }
  return { calls, sessions };
}
"""


def test_a_photo_never_goes_before_its_encounter(open_member_app):
    # A page of the app's own origin with no app running in it: the queue
    # under test is the only one reading this browser's store.
    page = open_member_app(COLLABORATOR, path="/i18n/en.json", wait=None)
    seen = page.evaluate(RACE, [MOMENTS, TIMES_EACH])
    calls = seen["calls"]
    early = []
    for session in seen["sessions"]:
        created = next(
            (i for i, (path, body) in enumerate(calls) if path == "/encounters" and body == session), None
        )
        media = next((i for i, (path, _) in enumerate(calls) if path == f"/encounters/{session}/media"), None)
        assert media is not None, f"the photo of {session} was never sent"
        if created is None or media < created:
            early.append(session)
    rounds = MOMENTS * TIMES_EACH
    assert not early, f"{len(early)} of {rounds} photos went to the server before their encounter"
