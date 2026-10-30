// The Capture screen's outbox: everything photographed is written to the
// phone first and uploaded from there, so a dead spot on campus, a closed
// app or a locked screen never loses a photo. Nothing is deleted from the
// phone until the API has confirmed the file is in storage.
//
// Every record is keyed by a ULID minted here. A retry after a lost response
// therefore lands on the same encounter and the same photo record server
// side — the API treats a repeat as a no-op — so the outbox can retry as
// often as it likes without ever creating a duplicate.
//
// A photo's bytes are written to the phone exactly once and never again:
// its progress (failed, and why) lives in a store of its own. Safari can
// refuse to store a Blob it has just read back out of IndexedDB, and an
// outbox that re-saved each item to mark it "uploading" stalled there,
// silently, before ever reaching the API (2026-10-29: 48 photos).

const DB_NAME = "bgucats-outbox";
const DB_VERSION = 2;

// Waits between attempts after a network failure, then stays at the last.
const BACKOFF_MS = [2_000, 5_000, 15_000, 60_000];
// A stalled upload on a weak campus signal fails instead of hanging the
// queue forever. Generous: 20 MB on a slow 3G link is about two minutes.
const UPLOAD_TIMEOUT_MS = 180_000;
// Photos in flight at once. Each is three round trips (record, S3,
// confirm), so on a phone's high-latency link waiting is most of the time;
// three overlaps it without starving any single upload of bandwidth.
const PARALLEL_UPLOADS = 3;
// The service worker's Background Sync tag (sw.js). Chrome on Android
// wakes the worker with it after the app is closed; Safari has no such API.
export const SYNC_TAG = "outbox";

// --------------------------------------------------------------------------
// ULID — 48-bit millisecond time, 80 random bits, Crockford base32
// --------------------------------------------------------------------------

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

export function ulid(now = Date.now()) {
  let time = "";
  for (let i = 0; i < 10; i++) {
    time = CROCKFORD[now % 32] + time;
    now = Math.floor(now / 32);
  }
  const random = crypto.getRandomValues(new Uint8Array(16));
  let rest = "";
  for (let i = 0; i < 16; i++) rest += CROCKFORD[random[i] % 32];
  return time + rest;
}

// --------------------------------------------------------------------------
// IndexedDB
// --------------------------------------------------------------------------

let dbPromise = null;

function db() {
  dbPromise ??= new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = (event) => {
      const d = request.result;
      if (event.oldVersion < 1) {
        d.createObjectStore("encounters", { keyPath: "sessionId" });
        d.createObjectStore("items", { keyPath: "photoId" });
      }
      // v2: per-item state, kept apart from the bytes. Items saved by v1
      // stay exactly as they are.
      if (event.oldVersion < 2) d.createObjectStore("states", { keyPath: "photoId" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return dbPromise;
}

async function tx(store, mode, fn) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const t = d.transaction(store, mode);
    const result = fn(t.objectStore(store));
    t.oncomplete = () => resolve(result?.result ?? result);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error);
  });
}

const put = (store, value) => tx(store, "readwrite", (s) => s.put(value));
const remove = (store, key) => tx(store, "readwrite", (s) => s.delete(key));
const all = (store) => tx(store, "readonly", (s) => s.getAll());
const get = (store, key) => tx(store, "readonly", (s) => s.get(key));

// Items with their state: "failed" if a states row says so (or a v1 item
// was saved as failed), otherwise "queued". "uploading" is memory only.
async function itemsWithState() {
  const states = new Map((await all("states")).map((s) => [s.photoId, s]));
  return (await all("items")).map((item) => {
    const row = states.get(item.photoId);
    const failed = row ? row.state === "failed" : item.state === "failed";
    return { item, state: failed ? "failed" : "queued", error: failed ? row?.error ?? item.error : null };
  });
}

// --------------------------------------------------------------------------
// The queue
// --------------------------------------------------------------------------

/**
 * @param {object} deps
 * @param {(path: string, body: object) => Promise<object>} deps.post  the app's API client
 * @param {() => void} deps.onChange  called whenever anything in the queue moves
 */
export function createOutbox({ post, onChange }) {
  // Progress lives in memory only: it means nothing after a restart.
  const progress = new Map();
  const uploading = new Set();
  let running = false;
  let again = false;
  let failures = 0;
  let timer = null;
  // Why the last pass stopped, for the screen: "uploading…" for an hour
  // with no reason given is how the 2026-10-29 stall went unnoticed.
  let lastError = null;

  async function addEncounter(encounter) {
    await put("encounters", { ...encounter, created: false });
    kick();
  }

  async function addItem(item) {
    await put("items", { ...item, state: "queued", error: null });
    onChange();
    kick();
    // Registered with every photo, so a phone that is offline now, and
    // closed before it is back, still gets them uploaded (Background Sync
    // waits for a signal). While the app is on screen the worker leaves
    // the work to it.
    handOver();
  }

  // Coalesces calls while a pass is running into exactly one more pass.
  function kick() {
    clearTimeout(timer);
    if (running) {
      again = true;
      return;
    }
    running = true;
    drain()
      .catch(() => {})
      .finally(() => {
        running = false;
        if (again) {
          again = false;
          kick();
        }
      });
  }

  // Rewrites one encounter from its latest saved copy, so a change made
  // while a request was in flight (Done, a new answer) is never undone.
  async function updateEncounter(sessionId, patch) {
    const latest = await get("encounters", sessionId);
    if (latest) await put("encounters", { ...latest, ...patch });
  }

  async function drain() {
    if (!navigator.onLine) return;
    let retryLater = false;
    try {
      const queued = await itemsWithState();
      const withItems = new Set(queued.map((q) => q.item.sessionId));
      for (const encounter of await all("encounters")) {
        if (encounter.created || encounter.failed) continue;
        // Created server side with its first photo, never before: an
        // encounter closed with nothing in it is no one's business.
        if (!withItems.has(encounter.sessionId) && !encounter.pick) continue;
        try {
          await post("/encounters", {
            sessionId: encounter.sessionId,
            lat: encounter.lat,
            lon: encounter.lon,
            accuracyM: encounter.accuracyM,
          });
        } catch (err) {
          if (isOffline(err)) throw err;
          if (!isPermanent(err)) {
            lastError = err.message;
            retryLater = true;
            continue;
          }
          // Refused outright (say, access was removed): its photos cannot
          // go anywhere, so they are shown as failed rather than retried.
          await updateEncounter(encounter.sessionId, { failed: true });
          for (const { item } of queued) {
            if (item.sessionId === encounter.sessionId) await fail(item, err);
          }
          continue;
        }
        await updateEncounter(encounter.sessionId, { created: true });
      }
      // A contributor's answer to "Is it one of these?" (capture.js). It
      // follows its encounter, and a re-send simply overwrites the same
      // answer server side.
      for (const encounter of await all("encounters")) {
        if (!encounter.created || !encounter.pick || encounter.pickSent) continue;
        try {
          await post(`/encounters/${encounter.sessionId}/pick`, encounter.pick);
        } catch (err) {
          if (isOffline(err)) throw err;
          if (!isPermanent(err)) {
            lastError = err.message;
            retryLater = true;
            continue;
          }
          // Refused (say, the cat was merged away meanwhile): the photos
          // matter, the answer does not — drop it rather than block them.
        }
        const latest = await get("encounters", encounter.sessionId);
        // Only if it was not changed again while this one was in flight.
        if (latest && JSON.stringify(latest.pick) === JSON.stringify(encounter.pick)) {
          await put("encounters", { ...latest, pickSent: true });
        }
      }
      const encounters = new Map((await all("encounters")).map((e) => [e.sessionId, e]));
      const todo = (await itemsWithState())
        .filter(({ item, state }) => {
          if (state === "failed") return false;
          const encounter = encounters.get(item.sessionId);
          return !encounter || encounter.created; // its encounter goes first
        })
        .sort((a, b) => a.item.photoId.localeCompare(b.item.photoId));
      keepAwake(todo.length > 0);
      let next = 0;
      let offline = null;
      const worker = async () => {
        while (next < todo.length && !offline) {
          const { item } = todo[next++];
          try {
            await send(item);
          } catch (err) {
            // No connection at all: the rest would fail the same way.
            if (isOffline(err)) offline = err;
            // Anything else is this photo's problem (a 500, a refused
            // upload): note it and carry on, so one photo never holds up
            // the others.
            lastError = err.message;
            retryLater = true;
          }
        }
      };
      await Promise.all(Array.from({ length: PARALLEL_UPLOADS }, worker));
      if (offline) throw offline;
      await forgetFinishedEncounters();
      if (!retryLater) {
        failures = 0;
        lastError = null;
        keepAwake(false);
        return;
      }
    } catch (err) {
      lastError = err.message;
    } finally {
      onChange();
    }
    // Something is still waiting: back off and try again.
    failures += 1;
    const wait = BACKOFF_MS[Math.min(failures, BACKOFF_MS.length) - 1];
    timer = setTimeout(kick, wait);
  }

  async function send(item) {
    uploading.add(item.photoId);
    onChange();
    try {
      let start;
      try {
        start = await post(`/encounters/${item.sessionId}/media`, {
          photoId: item.photoId,
          contentType: item.contentType,
          capturedAt: item.capturedAt,
          lat: item.lat,
          lon: item.lon,
          accuracyM: item.accuracyM,
          durationSeconds: item.durationSeconds,
        });
      } catch (err) {
        if (isPermanent(err)) return fail(item, err);
        throw err;
      }

      if (!start.done) {
        try {
          await uploadToStorage(start.upload, item);
        } catch (err) {
          // Storage said no (too large, a policy it would not accept): a
          // fresh attempt is a person's call — "Try again" — not a loop.
          if (err.status >= 400 && err.status < 500) return fail(item, err);
          throw err;
        }
      }

      try {
        await post(`/photos/${item.photoId}/complete`, {});
      } catch (err) {
        if (isPermanent(err) && err.status !== 409) return fail(item, err);
        throw err;
      }
      await remove("items", item.photoId);
      await remove("states", item.photoId);
    } finally {
      uploading.delete(item.photoId);
      progress.delete(item.photoId);
    }
  }

  // A presigned POST to S3. XHR rather than fetch, for upload progress.
  function uploadToStorage(upload, item) {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      for (const [name, value] of Object.entries(upload.fields)) form.append(name, value);
      form.append("file", item.blob); // must be the last field
      const xhr = new XMLHttpRequest();
      xhr.open("POST", upload.url);
      xhr.timeout = UPLOAD_TIMEOUT_MS;
      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable) return;
        progress.set(item.photoId, event.loaded / event.total);
        onChange();
      };
      xhr.onload = () =>
        xhr.status >= 200 && xhr.status < 300
          ? resolve()
          : reject(Object.assign(new Error(`storage refused the upload (${xhr.status})`), { status: xhr.status }));
      xhr.onerror = () => reject(new Error("network error during upload"));
      xhr.ontimeout = () => reject(new Error("the upload timed out"));
      xhr.send(form);
    });
  }

  async function fail(item, err) {
    progress.delete(item.photoId);
    await put("states", { photoId: item.photoId, state: "failed", error: err.message });
  }

  async function forgetFinishedEncounters() {
    const items = await all("items");
    for (const encounter of await all("encounters")) {
      const pickPending = encounter.pick && !encounter.pickSent;
      const empty = !items.some((i) => i.sessionId === encounter.sessionId);
      // Closed and sent — or closed with nothing ever captured, so never sent.
      if (!encounter.open && !pickPending && empty && (encounter.created || !encounter.pick)) {
        await remove("encounters", encounter.sessionId);
      }
    }
  }

  // The latest answer replaces any earlier one, sent or not.
  async function setPick(sessionId, pick) {
    await updateEncounter(sessionId, { pick, pickSent: false });
    kick();
  }

  async function closeEncounter(sessionId) {
    await updateEncounter(sessionId, { open: false });
    kick();
  }

  async function retryFailed() {
    for (const { item, state } of await itemsWithState()) {
      if (state === "failed") await put("states", { photoId: item.photoId, state: "queued", error: null });
    }
    failures = 0;
    kick();
  }

  async function discard(photoId) {
    progress.delete(photoId);
    await remove("items", photoId);
    await remove("states", photoId);
    onChange();
  }

  async function snapshot() {
    const items = await itemsWithState();
    return {
      items: items.map(({ item, state, error }) => ({
        ...item,
        state: uploading.has(item.photoId) ? "uploading" : state,
        error,
        progress: progress.get(item.photoId) ?? null,
      })),
      encounters: await all("encounters"),
      lastError,
    };
  }

  // While photos are waiting and the app is on screen, keep the screen from
  // locking: on an iPhone a locked screen or another app stops uploads cold
  // (Safari suspends the page and has no background upload API). The lock
  // is released by the browser whenever the app is hidden.
  let wakeLock = null;
  let wantAwake = false;
  async function keepAwake(on) {
    wantAwake = on;
    try {
      if (on && !wakeLock && document.visibilityState === "visible" && navigator.wakeLock) {
        wakeLock = await navigator.wakeLock.request("screen");
        wakeLock.addEventListener("release", () => (wakeLock = null));
      } else if (!on && wakeLock) {
        await wakeLock.release();
      }
    } catch {
      /* not supported, or refused (low battery): uploads go on regardless */
    }
  }

  // Leaving the app with photos still waiting: ask the service worker to
  // finish them (Background Sync, where the browser has it — Chrome on
  // Android). It runs once the app is in the background, or as soon as
  // there is a signal again, even with the app closed.
  async function handOver() {
    try {
      if (!(await all("items")).length) return;
      const registration = await navigator.serviceWorker?.ready;
      await registration?.sync?.register(SYNC_TAG);
    } catch {
      /* no Background Sync here: uploads resume when the app is opened */
    }
  }

  addEventListener("online", kick);
  addEventListener("offline", handOver);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      kick();
      if (wantAwake) keepAwake(true);
    } else {
      handOver();
    }
  });
  // Ask the browser not to evict the queue under storage pressure. A
  // refusal is fine — it only matters on a nearly full phone.
  navigator.storage?.persist?.().catch(() => {});

  return {
    addEncounter,
    addItem,
    setPick,
    closeEncounter,
    retryFailed,
    discard,
    snapshot,
    kick,
    backgroundSync: () => "SyncManager" in window,
  };
}

// 400/403/404 will not get better by asking again. 401 is handled by the
// API client (it sends the person to sign in); anything else is retried.
function isPermanent(err) {
  return [400, 403, 404, 409].includes(err.status);
}

// fetch rejects with a TypeError when there is no connection at all.
function isOffline(err) {
  return err instanceof TypeError || err.message === "network error during upload";
}
