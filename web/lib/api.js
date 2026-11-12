// The API client, shared by both shells. Moved out of app.js unchanged in
// milestone E0, apart from what happens when the sign-in is gone: the shell
// that runs says, through onSignedOut (the desk shows its sign-in screen).

import { dropTokens, getConfig, idToken } from "./auth.js";
import { keepPhotoUrls } from "./photos.js";

const API_TIMEOUT_MS = 35_000;

let signedOut = () => {};

export function onSignedOut(fn) {
  signedOut = fn;
}

export async function api(path, options = {}) {
  const token = await idToken();
  if (!token) {
    signedOut();
    throw new Error("not signed in");
  }
  // The PWA and its API share an address. The iPhone app's files are packed
  // inside it, so its config says where the API is (scripts/native_bundle.py).
  const res = await fetch(`${getConfig().apiBase || ""}/api${path}`, {
    // A request that hangs on a weak signal would hold up whatever waits on
    // it — the upload outbox included — until the app is closed. API Gateway
    // gives up at 30 s anyway.
    signal: AbortSignal.timeout?.(API_TIMEOUT_MS),
    ...options,
    headers: {
      authorization: `Bearer ${token}`,
      ...(options.body ? { "content-type": "application/json" } : {}),
      ...options.headers,
    },
  });
  if (res.status === 401) {
    dropTokens();
    signedOut();
    throw new Error("session expired");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // The status rides along so the upload outbox can tell "try again"
    // from "this will never work".
    throw Object.assign(new Error(data.error || `request failed (${res.status})`), {
      status: res.status,
      code: data.code, // the member API's machine word (docs/app-plan/04-api.md)
    });
  }
  if (options.method && options.method !== "GET" && !PASSIVE_WRITES.test(path)) forgetResponses();
  return keepPhotoUrls(data);
}

export const post = (path, body) =>
  api(path, { method: "POST", body: JSON.stringify(body || {}) });
export const patch = (path, body) =>
  api(path, { method: "PATCH", body: JSON.stringify(body || {}) });

export const put = (path, body) =>
  api(path, { method: "PUT", body: JSON.stringify(body || {}) });
export const del = (path) => api(path, { method: "DELETE" });

// Screens: a GET answered in the last few seconds is reused as is; an older
// one is shown at once and refreshed behind it, and the screen redraws only
// if something changed. Anything the person does (label, merge, rename…)
// drops the lot, so an action is never followed by a stale screen.
const FRESH_MS = 15 * 1000;
const responses = new Map(); // path -> { data, text, at }
// Writes that change nothing a screen shows: the model's bookkeeping and
// the upload outbox, which would otherwise empty the cache every second.
export const PASSIVE_WRITES = /\/(prediction|vectors|media|complete|pick)$|^\/encounters$/;

export function forgetResponses() {
  responses.clear();
}

// Signatures differ on every response; what is shown does not.
const comparable = (data) => JSON.stringify(data).replace(/\?[^"]*Signature=[^"]*/g, "");

// `isCurrent` says whether the screen that asked is still the one shown, so
// a late refresh never redraws over another screen (the desk passes its
// screen counter, app.js `cachedGet`).
export async function cachedGet(path, redraw, isCurrent = () => true) {
  const hit = responses.get(path);
  if (hit && Date.now() - hit.at < FRESH_MS) return hit.data;
  if (hit) {
    api(path)
      .then((data) => {
        const text = comparable(data);
        responses.set(path, { data, text, at: Date.now() });
        if (text !== hit.text && isCurrent()) redraw();
      })
      .catch(() => {});
    return hit.data;
  }
  const data = await api(path);
  responses.set(path, { data, text: comparable(data), at: Date.now() });
  return data;
}
