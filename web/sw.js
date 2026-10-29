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

const CACHE = "bgucats-shell-v3";
const MODEL_CACHE = "bgucats-model";
const MODEL_PATH = /^\/model\/([^/]+)\/[^/]+$/;
const SHELL = [
  "/",
  "/index.html",
  "/app.js",
  "/capture.js",
  "/install.js",
  "/outbox.js",
  "/charts.js",
  "/recognition.js",
  "/styles.css",
  "/config.json",
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

  // The sign-in callback arrives as /?code=…; it is the same page.
  const key = event.request.mode === "navigate" ? "/index.html" : url.pathname;
  if (event.request.mode !== "navigate" && !SHELL.includes(key)) return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(key, copy));
        }
        return response;
      })
      .catch(() => caches.match(key).then((hit) => hit || Response.error())),
  );
});

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
