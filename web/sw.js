// Service worker: makes the app installable and lets it open with no signal.
//
// Network first, cache as the fallback — never the other way round. The
// distribution deliberately caches nothing (infra/main/web.tf) so that a
// deploy reaches everyone on their next load; a cache-first worker would
// quietly undo that. Online, every file comes fresh from the network and the
// copy here is refreshed; offline, the last copy is served.
//
// Only the app's own files. Never /api/ (data must be live, and must never
// outlive a sign-out), never photos, never other origins (Cognito, Google,
// S3 uploads).
//
// One exception to network-first: the recognition model under
// /model/{version}/ (about 40 MB, scripts/publish_model.py). The version is
// a hash of the model file, so a path there can never change meaning and
// the cached copy can never be stale — cache-first is safe, and without it
// every launch would download the model again. /model/manifest.json, which
// says which version to load, is not cached: a new model still reaches
// everyone on their next load.
//
// And one job beyond caching: Background Sync (Chrome on Android). When the
// app is left with photos still waiting, outbox.js registers the "outbox"
// tag, and the browser wakes this worker to upload them, after the app is
// closed too, as soon as there is a signal. It does the same three steps as
// outbox.js (record, S3, confirm) on the same IndexedDB queue and the same
// ULIDs, so a photo the app and the worker both send lands once. Safari has
// no Background Sync: on an iPhone, uploads move only while the app is open.

const CACHE = "bgucats-shell-v19";
const MODEL_CACHE = "bgucats-model";
const MODEL_PATH = /^\/model\/([^/]+)\/[^/]+$/;
const SHELL = [
  "/",
  "/index.html",
  "/app.js",
  "/lib/api.js",
  "/lib/auth.js",
  "/lib/photos.js",
  "/app.html",
  "/tokens.css",
  "/social/app.css",
  "/social/main.js",
  "/social/i18n.js",
  "/social/store.js",
  "/social/theme.js",
  "/social/motion.js",
  "/social/ui.js",
  "/social/tabbar.js",
  "/social/stack.js",
  "/social/feed.js",
  "/social/feeding.js",
  "/social/home.js",
  "/social/mascot.js",
  "/social/terms.js",
  "/social/avatar.js",
  "/social/asking.js",
  "/social/gallery.js",
  "/social/friends.js",
  "/social/achievements.js",
  "/social/appinfo.js",
  "/social/trail.js",
  "/social/map.js",
  "/social/report.js",
  "/social/poll.js",
  "/social/data.js",
  "/social/cat.js",
  "/social/scan.js",
  "/i18n/en.json",
  "/i18n/he.json",
  "/i18n/ru.json",
  "/i18n/ar.json",
  "/vendor/preact-htm.js",
  "/vendor/inter-latin-wght-normal.woff2",
  "/capture.js",
  "/install.js",
  "/outbox.js",
  "/charts.js",
  "/recognition.js",
  "/styles.css",
  "/config.json",
  "/regions.json",
  "/manifest.webmanifest",
  "/icon.svg",
  "/icon-192.png",
  "/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((k) => k !== CACHE && k !== MODEL_CACHE).map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  const model = url.pathname.match(MODEL_PATH);
  if (model) {
    event.respondWith(modelFile(event.request, url.pathname, model[1]));
    return;
  }

  // A page: the desk (the sign-in callback arrives as /?code=…; it is the
  // same page) or the member app, each kept under its own name. Until
  // 2026-11-14 both were kept as /index.html, so with no signal the app
  // opened as whichever page had been fetched last.
  if (event.request.mode === "navigate") {
    const key = url.pathname === "/app.html" ? "/app.html" : "/index.html";
    const { answer, refreshed } = page(event.request, key);
    event.respondWith(answer);
    event.waitUntil(refreshed);
    return;
  }

  const key = url.pathname;
  if (!SHELL.includes(key)) return;
  event.respondWith(
    fresh(event.request, key).catch(() => keptCopy(key).then((hit) => hit || Response.error())),
  );
});

// From the network, and the copy kept for a time with no signal refreshed.
function fresh(request, key) {
  return fetch(request).then((response) => {
    if (response.ok) {
      const copy = response.clone();
      caches.open(CACHE).then((cache) => cache.put(key, copy));
    }
    return response;
  });
}

const keptCopy = (key) => caches.open(CACHE).then((cache) => cache.match(key));

// How long a page may wait for the network before the kept copy opens
// instead. A connection that neither answers nor fails (a lift, the edge of
// the campus Wi-Fi) is not "no signal" to the browser: without a limit the
// app opened on an empty screen for as long as the request hung. The page
// that opens can say what it is waiting for (app.html); nothing can.
const PAGE_WAIT_MS = 4000;

// A page, network first: the network's answer if it comes in time or there
// is nothing kept; the kept copy if the network fails or is late. A late
// answer still refreshes the copy (`refreshed`).
function page(request, key) {
  const network = fresh(request, key);
  const orKept = network.catch(() => keptCopy(key).then((hit) => hit || Response.error()));
  const late = new Promise((resolve) => setTimeout(resolve, PAGE_WAIT_MS))
    .then(() => keptCopy(key))
    .then((hit) => hit || orKept);
  return { answer: Promise.race([orKept, late]), refreshed: network.then(() => {}, () => {}) };
}

async function modelFile(request, path, version) {
  const cache = await caches.open(MODEL_CACHE);
  const hit = await cache.match(path);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) {
    await cache.put(path, response.clone());
    // Keep one version: an older model is never loaded again.
    for (const key of await cache.keys()) {
      const old = new URL(key.url).pathname.match(MODEL_PATH);
      if (old && old[1] !== version) await cache.delete(key);
    }
  }
  return response;
}

// --------------------------------------------------------------------------
// Background Sync: the outbox, uploaded while the app is closed
// --------------------------------------------------------------------------

const SYNC_TAG = "outbox"; // outbox.js SYNC_TAG

self.addEventListener("sync", (event) => {
  if (event.tag === SYNC_TAG) event.waitUntil(uploadOutbox());
});

// Rejecting tells the browser to try again later (it backs off by itself).
async function uploadOutbox() {
  // The app on screen uploads by itself; two senders only waste the signal.
  const windows = await self.clients.matchAll({ type: "window" });
  if (windows.some((w) => w.visibilityState === "visible")) return;

  const db = await openExisting("bgucats-outbox");
  if (!db || !db.objectStoreNames.contains("states")) return; // nothing queued, or an older app
  try {
    const token = await workerToken();
    if (!token) return; // signed out: nothing can be sent
    const api = (path, body) => apiPost(token, path, body);

    let left = 0;
    const states = new Map((await getAll(db, "states")).map((r) => [r.photoId, r]));
    const items = (await getAll(db, "items")).filter((i) => {
      const row = states.get(i.photoId);
      return row ? row.state !== "failed" : i.state !== "failed";
    });
    const encounters = new Map((await getAll(db, "encounters")).map((e) => [e.sessionId, e]));

    for (const item of items.sort((a, b) => a.photoId.localeCompare(b.photoId))) {
      const encounter = encounters.get(item.sessionId);
      if (encounter?.failed) continue;
      if (encounter && !encounter.created) {
        const res = await api("/encounters", {
          sessionId: encounter.sessionId,
          lat: encounter.lat,
          lon: encounter.lon,
          accuracyM: encounter.accuracyM,
        });
        if (!res.ok) {
          left += 1;
          continue;
        }
        encounter.created = true;
        await patchRecord(db, "encounters", encounter.sessionId, { created: true });
      }
      if (!(await sendItem(db, api, item))) left += 1;
    }
    if (left) throw new Error(`${left} still waiting`);
  } finally {
    db.close();
  }
}

// One photo: true when it is done with (uploaded, or refused for good).
async function sendItem(db, api, item) {
  const start = await api(`/encounters/${item.sessionId}/media`, {
    photoId: item.photoId,
    contentType: item.contentType,
    capturedAt: item.capturedAt,
    lat: item.lat,
    lon: item.lon,
    accuracyM: item.accuracyM,
    durationSeconds: item.durationSeconds,
  });
  if (permanent(start.status)) return failItem(db, item, start.error);
  if (!start.ok) return false;
  if (!start.data.done) {
    const form = new FormData();
    for (const [name, value] of Object.entries(start.data.upload.fields)) form.append(name, value);
    form.append("file", item.blob); // must be the last field
    const res = await fetch(start.data.upload.url, { method: "POST", body: form }).catch(() => null);
    if (!res) return false;
    if (res.status >= 400 && res.status < 500) return failItem(db, item, `storage refused the upload (${res.status})`);
    if (!res.ok) return false;
  }
  const done = await api(`/photos/${item.photoId}/complete`, {});
  if (permanent(done.status) && done.status !== 409) return failItem(db, item, done.error);
  if (!done.ok && done.status !== 409) return false;
  await deleteRecord(db, "items", item.photoId);
  await deleteRecord(db, "states", item.photoId);
  return true;
}

async function failItem(db, item, error) {
  await putRecord(db, "states", { photoId: item.photoId, state: "failed", error: error || "refused" });
  return true;
}

const permanent = (status) => [400, 403, 404, 409].includes(status);

async function apiPost(token, path, body) {
  try {
    const res = await fetch(`/api${path}`, {
      method: "POST",
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data, error: data.error };
  } catch {
    return { ok: false, status: 0, data: {} }; // no connection: try later
  }
}

// The app's sign-in, copied to IndexedDB by app.js (saveTokens). Refreshed
// here with the refresh token when it has expired.
async function workerToken() {
  const auth = await openExisting("bgucats-auth");
  if (!auth) return null;
  try {
    const tokens = (await getAll(auth, "tokens"))[0];
    if (!tokens) return null;
    if (Date.now() < tokens.expiresAt) return tokens.idToken;
    if (!tokens.refreshToken) return null;
    const config = await (await fetch("/config.json")).json();
    const res = await fetch(`https://${config.cognitoDomain}/oauth2/token`, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: config.userPoolClientId,
        grant_type: "refresh_token",
        refresh_token: tokens.refreshToken,
      }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    const fresh = {
      idToken: data.id_token,
      refreshToken: data.refresh_token || tokens.refreshToken,
      expiresAt: Date.now() + (data.expires_in - 60) * 1000,
    };
    await putRecord(auth, "tokens", fresh, "current");
    return fresh.idToken;
  } finally {
    auth.close();
  }
}

// Opens a database only if the app already made it: creating one here would
// leave it at a version the app's own upgrade then skips.
function openExisting(name) {
  return new Promise((resolve) => {
    const open = indexedDB.open(name);
    open.onupgradeneeded = () => open.transaction.abort();
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => resolve(null);
  });
}

function request(db, store, mode, fn) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, mode);
    const req = fn(tx.objectStore(store));
    tx.oncomplete = () => resolve(req.result);
    tx.onerror = tx.onabort = () => reject(tx.error);
  });
}

const getAll = (db, store) => request(db, store, "readonly", (s) => s.getAll());
const putRecord = (db, store, value, key) => request(db, store, "readwrite", (s) => (key ? s.put(value, key) : s.put(value)));
const deleteRecord = (db, store, key) => request(db, store, "readwrite", (s) => s.delete(key));

async function patchRecord(db, store, key, patch) {
  const latest = await request(db, store, "readonly", (s) => s.get(key));
  if (latest) await putRecord(db, store, { ...latest, ...patch });
}
