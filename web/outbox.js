// The Capture screen's outbox: everything photographed is written to the
// phone first and uploaded from there, so a dead spot on campus, a closed
// app or a locked screen never loses a photo. Nothing is deleted from the
// phone until the API has confirmed the file is in storage.
//
// Every record is keyed by a ULID minted here. A retry after a lost response
// therefore lands on the same encounter and the same photo record server
// side — the API treats a repeat as a no-op — so the outbox can retry as
// often as it likes without ever creating a duplicate.

const DB_NAME = "bgucats-outbox";
const DB_VERSION = 1;

// Waits between attempts after a network failure, then stays at the last.
const BACKOFF_MS = [2_000, 5_000, 15_000, 60_000];

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
    request.onupgradeneeded = () => {
      const d = request.result;
      d.createObjectStore("encounters", { keyPath: "sessionId" });
      d.createObjectStore("items", { keyPath: "photoId" });
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
  let running = false;
  let again = false;
  let failures = 0;
  let timer = null;

  async function addEncounter(encounter) {
    await put("encounters", { ...encounter, created: false });
    kick();
  }

  async function addItem(item) {
    await put("items", { ...item, state: "queued", error: null });
    onChange();
    kick();
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

  async function drain() {
    if (!navigator.onLine) return;
    try {
      for (const encounter of await all("encounters")) {
        if (encounter.created || encounter.failed) continue;
        try {
          await post("/encounters", {
            sessionId: encounter.sessionId,
            lat: encounter.lat,
            lon: encounter.lon,
            accuracyM: encounter.accuracyM,
          });
        } catch (err) {
          if (!isPermanent(err)) throw err;
          // Refused outright (say, access was removed): its photos cannot
          // go anywhere, so they are shown as failed rather than retried.
          await put("encounters", { ...encounter, failed: true });
          for (const item of await all("items")) {
            if (item.sessionId === encounter.sessionId) await fail(item, err);
          }
          continue;
        }
        await put("encounters", { ...encounter, created: true });
      }
      const items = (await all("items")).sort((a, b) => a.photoId.localeCompare(b.photoId));
      for (const item of items) {
        if (item.state === "failed") continue;
        await send(item);
      }
      failures = 0;
      await forgetFinishedEncounters();
    } catch (err) {
      // A network failure: everything stays queued. Back off and retry.
      failures += 1;
      const wait = BACKOFF_MS[Math.min(failures, BACKOFF_MS.length) - 1];
      timer = setTimeout(kick, wait);
    } finally {
      onChange();
    }
  }

  async function send(item) {
    const encounter = (await all("encounters")).find((e) => e.sessionId === item.sessionId);
    if (encounter && !encounter.created) return; // its encounter goes first
    if (item.state === "failed") return;

    await put("items", { ...item, state: "uploading" });
    onChange();
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
      await put("items", { ...item, state: "queued" });
      throw err;
    }

    if (!start.done) {
      try {
        await uploadToStorage(start.upload, item);
      } catch (err) {
        progress.delete(item.photoId);
        await put("items", { ...item, state: "queued" });
        throw err;
      }
    }

    try {
      await post(`/photos/${item.photoId}/complete`, {});
    } catch (err) {
      if (isPermanent(err) && err.status !== 409) return fail(item, err);
      await put("items", { ...item, state: "queued" });
      throw err;
    }
    progress.delete(item.photoId);
    await remove("items", item.photoId);
  }

  // A presigned POST to S3. XHR rather than fetch, for upload progress.
  function uploadToStorage(upload, item) {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      for (const [name, value] of Object.entries(upload.fields)) form.append(name, value);
      form.append("file", item.blob); // must be the last field
      const xhr = new XMLHttpRequest();
      xhr.open("POST", upload.url);
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
      xhr.send(form);
    });
  }

  async function fail(item, err) {
    progress.delete(item.photoId);
    await put("items", { ...item, state: "failed", error: err.message });
  }

  async function forgetFinishedEncounters() {
    const items = await all("items");
    for (const encounter of await all("encounters")) {
      if (encounter.created && !encounter.open && !items.some((i) => i.sessionId === encounter.sessionId)) {
        await remove("encounters", encounter.sessionId);
      }
    }
  }

  async function closeEncounter(sessionId) {
    const encounter = (await all("encounters")).find((e) => e.sessionId === sessionId);
    if (encounter) await put("encounters", { ...encounter, open: false });
    kick();
  }

  async function retryFailed() {
    for (const item of await all("items")) {
      if (item.state === "failed") await put("items", { ...item, state: "queued", error: null });
    }
    kick();
  }

  async function discard(photoId) {
    progress.delete(photoId);
    await remove("items", photoId);
    onChange();
  }

  async function snapshot() {
    const items = await all("items");
    return {
      items: items.map((i) => ({ ...i, progress: progress.get(i.photoId) ?? null })),
      encounters: await all("encounters"),
    };
  }

  addEventListener("online", kick);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") kick();
  });
  // Ask the browser not to evict the queue under storage pressure. A
  // refusal is fine — it only matters on a nearly full phone.
  navigator.storage?.persist?.().catch(() => {});

  return { addEncounter, addItem, closeEncounter, retryFailed, discard, snapshot, kick };
}

// 400/403/404 will not get better by asking again. 401 is handled by the
// API client (it sends the person to sign in); anything else is retried.
function isPermanent(err) {
  return [400, 403, 404, 409].includes(err.status);
}
