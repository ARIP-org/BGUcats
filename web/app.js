// Admin labeling tool, and the installable app collaborators photograph cats
// with. No framework and no build step on purpose: the whole client is a few
// files served straight from S3, which keeps the deploy path to "upload the
// file" and keeps this readable without a toolchain.
//
// Two roles (src/admin/handler.py): admins see everything; collaborators see
// Capture and the cats. The API enforces this on every call — hiding a button
// here is only so nobody is offered an action that would be refused.
//
// It runs only as an installed app. Opened in a browser tab, it shows the
// install page instead (install.js) — before any sign-in, so a collaborator
// never ends up half-using it in a tab that loses its outbox when closed.

import { createCapture } from "./capture.js";
import { barList, columnChart, formatNumber, funnel, meter } from "./charts.js";
import { isInstalled, showInstallPage } from "./install.js";
import { createRecognition, scoreRow, summarize } from "./recognition.js";

const $ = (sel) => document.querySelector(sel);
const el = (tag, props = {}, kids = []) => {
  const { attrs, ...rest } = props;
  const node = Object.assign(document.createElement(tag), rest);
  for (const [name, value] of Object.entries(attrs || {})) node.setAttribute(name, value);
  for (const kid of [].concat(kids)) {
    if (kid != null && kid !== false) node.append(kid);
  }
  return node;
};

const SVG_NS = "http://www.w3.org/2000/svg";
function doodle(symbol, className = "doodle") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#${symbol}`);
  svg.append(use);
  return svg;
}

function button(label, className, onClick) {
  const node = el("button", { type: "button", className, textContent: label });
  if (onClick) node.onclick = guard(onClick);
  return node;
}

let config = null;
let state = { view: "queue", cats: [], email: null, role: null };
let capture = null;
// The recognition model (recognition.js). Admins: blind guesses for the
// queue, and the measurements on Stats. Everyone: opt-in guesses in Capture.
let recognition = null;

const isAdmin = () => state.role === "admin";

// --------------------------------------------------------------------------
// Auth — Cognito hosted UI, authorization code + PKCE
// --------------------------------------------------------------------------

const TOKENS_KEY = "bgucats.tokens";
const VERIFIER_KEY = "bgucats.pkce";
// A message for the sign-in screen that has to survive a page load: why the
// last sign-in was turned away, or that the person signed out.
const LOGIN_NOTE_KEY = "bgucats.loginNote";
// Remembered so the app opens without a connection — under a bush with no
// signal is exactly where Capture gets used. The API still checks the real
// role on every call.
const ROLE_KEY = "bgucats.role";
const API_TIMEOUT_MS = 35_000;

const b64url = (bytes) =>
  btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

async function pkce() {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)));
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(verifier),
  );
  return { verifier, challenge: b64url(new Uint8Array(digest)) };
}

async function login() {
  const { verifier, challenge } = await pkce();
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.userPoolClientId,
    redirect_uri: config.redirectUri,
    scope: "openid email profile",
    code_challenge: challenge,
    code_challenge_method: "S256",
    // Straight to Google rather than via Cognito's provider chooser — it is
    // the only provider, so the extra page is pure friction.
    identity_provider: "Google",
    // Google's account chooser, every time. Without it Google silently
    // reuses whichever account the phone is signed in to, so someone turned
    // away, or signed out, could never pick a different one. Cognito passes
    // this on to Google only with managed login (infra/main/cognito.tf).
    prompt: "select_account",
  });
  location.assign(`https://${config.cognitoDomain}/oauth2/authorize?${params}`);
}

// Signing out forgets this app's tokens and stays inside the app. There is no
// trip to Cognito's /logout page: leaving the app's own address is what makes
// an installed iPhone app show Safari's address bar and toolbar, and nothing
// is gained by it — the next sign-in asks Google which account to use anyway.
function logout() {
  forgetSignIn("Signed out. Choose an account to sign in again.");
  location.replace("/");
}

function forgetSignIn(note) {
  localStorage.removeItem(TOKENS_KEY);
  localStorage.removeItem(ROLE_KEY);
  try {
    if (note) sessionStorage.setItem(LOGIN_NOTE_KEY, note);
  } catch {
    /* the note is a courtesy */
  }
}

async function exchangeToken(body) {
  const res = await fetch(`https://${config.cognitoDomain}/oauth2/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: config.userPoolClientId,
      ...body,
    }),
  });
  if (!res.ok) throw new Error(`token endpoint returned ${res.status}`);
  const data = await res.json();
  const tokens = {
    idToken: data.id_token,
    // A refresh grant does not return a new refresh token; keep the old one.
    refreshToken: data.refresh_token || readTokens()?.refreshToken,
    expiresAt: Date.now() + (data.expires_in - 60) * 1000,
  };
  localStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
  return tokens;
}

function readTokens() {
  try {
    return JSON.parse(localStorage.getItem(TOKENS_KEY));
  } catch {
    return null;
  }
}

async function idToken() {
  const tokens = readTokens();
  if (!tokens) return null;
  if (Date.now() < tokens.expiresAt) return tokens.idToken;
  if (!tokens.refreshToken) return null;
  try {
    const refreshed = await exchangeToken({
      grant_type: "refresh_token",
      refresh_token: tokens.refreshToken,
    });
    return refreshed.idToken;
  } catch (err) {
    // No connection is not a rejected login: keep the refresh token for when
    // the phone is back online. The stale token fails its API call, and the
    // upload outbox simply retries later.
    if (err instanceof TypeError) return tokens.idToken;
    localStorage.removeItem(TOKENS_KEY);
    return null;
  }
}

async function consumeCallback() {
  const params = new URLSearchParams(location.search);
  const code = params.get("code");
  if (params.get("error")) {
    // Cognito rejected the sign-up — almost always the pre-sign-up trigger
    // refusing an email that is not on the allowlist. Cognito prefixes the
    // trigger's message with its own plumbing.
    const reason = (params.get("error_description") || params.get("error"))
      .replace(/^PreSignUp failed with error\s*/i, "")
      .trim();
    forgetSignIn(`${reason} Sign in with a different Google account.`);
    history.replaceState({}, "", location.pathname);
  }
  if (!code) return;
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  sessionStorage.removeItem(VERIFIER_KEY);
  history.replaceState({}, "", location.pathname);
  if (!verifier) return;
  await exchangeToken({
    grant_type: "authorization_code",
    code,
    redirect_uri: config.redirectUri,
    code_verifier: verifier,
  });
}

// --------------------------------------------------------------------------
// API
// --------------------------------------------------------------------------

async function api(path, options = {}) {
  const token = await idToken();
  if (!token) {
    showLogin();
    throw new Error("not signed in");
  }
  const res = await fetch(`/api${path}`, {
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
    localStorage.removeItem(TOKENS_KEY);
    showLogin();
    throw new Error("session expired");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // The status rides along so the upload outbox can tell "try again"
    // from "this will never work".
    throw Object.assign(new Error(data.error || `request failed (${res.status})`), {
      status: res.status,
    });
  }
  if (options.method && options.method !== "GET" && !PASSIVE_WRITES.test(path)) forgetResponses();
  return keepPhotoUrls(data);
}

const post = (path, body) =>
  api(path, { method: "POST", body: JSON.stringify(body || {}) });
const patch = (path, body) =>
  api(path, { method: "PATCH", body: JSON.stringify(body || {}) });

// --------------------------------------------------------------------------
// Caching — so switching screens does not fetch everything again
// --------------------------------------------------------------------------

// Photo URLs are presigned, so every response signs the same photo afresh,
// and a new URL is a cache miss: every screen used to download every photo
// again. The first URL seen for each object is reused until shortly before
// it expires (kept across launches), and S3 serves it with a long
// Cache-Control (handler._presign), so a photo downloads about once an hour.
const URLS_KEY = "bgucats.photoUrls";
const URL_MARGIN_MS = 5 * 60 * 1000;
const photoUrls = loadPhotoUrls(); // object URL without query -> { url, expiresAt }
let savePhotoUrlsTimer = null;

function loadPhotoUrls() {
  try {
    const now = Date.now();
    return new Map(
      Object.entries(JSON.parse(localStorage.getItem(URLS_KEY)) || {}).filter(
        ([, v]) => v.expiresAt - now > URL_MARGIN_MS,
      ),
    );
  } catch {
    return new Map();
  }
}

function savePhotoUrls() {
  clearTimeout(savePhotoUrlsTimer);
  savePhotoUrlsTimer = setTimeout(() => {
    try {
      localStorage.setItem(URLS_KEY, JSON.stringify(Object.fromEntries(photoUrls)));
    } catch {
      /* this launch still has them in memory */
    }
  }, 1000);
}

// When a presigned URL stops working. SigV2 (what boto3 signs with in
// us-east-1) says so outright; SigV4 gives the signing time and lifetime.
function urlExpiry(url) {
  const q = url.searchParams;
  if (q.get("Expires")) return Number(q.get("Expires")) * 1000;
  const date = q.get("X-Amz-Date")?.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/);
  if (!date || !q.get("X-Amz-Expires")) return null;
  const [, y, mo, d, h, mi, se] = date;
  return Date.parse(`${y}-${mo}-${d}T${h}:${mi}:${se}Z`) + Number(q.get("X-Amz-Expires")) * 1000;
}

function stablePhotoUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    return value;
  }
  const expiresAt = urlExpiry(url);
  if (!expiresAt) return value;
  const key = url.origin + url.pathname;
  const known = photoUrls.get(key);
  if (known && known.expiresAt - Date.now() > URL_MARGIN_MS) return known.url;
  photoUrls.set(key, { url: value, expiresAt });
  savePhotoUrls();
  return value;
}

// Every "...Url" field in a response: thumbUrl, mediumUrl, coverUrl, videoUrl.
function keepPhotoUrls(data) {
  if (Array.isArray(data)) {
    for (const item of data) keepPhotoUrls(item);
  } else if (data && typeof data === "object") {
    for (const [key, value] of Object.entries(data)) {
      if (typeof value === "string" && key.endsWith("Url") && value.startsWith("https://")) {
        data[key] = stablePhotoUrl(value);
      } else if (value && typeof value === "object") {
        keepPhotoUrls(value);
      }
    }
  }
  return data;
}

// A kept URL that fails anyway (the signing credentials ran out first) is
// forgotten, so the next screen uses the fresh one.
document.addEventListener(
  "error",
  (event) => {
    const src = event.target?.currentSrc || event.target?.src;
    if (!src || !(event.target instanceof HTMLImageElement || event.target instanceof HTMLVideoElement)) return;
    try {
      const url = new URL(src);
      if (photoUrls.get(url.origin + url.pathname)?.url === src) {
        photoUrls.delete(url.origin + url.pathname);
        savePhotoUrls();
      }
    } catch {
      /* not one of ours */
    }
  },
  true,
);

// Screens: a GET answered in the last few seconds is reused as is; an older
// one is shown at once and refreshed behind it, and the screen redraws only
// if something changed. Anything the person does (label, merge, rename…)
// drops the lot, so an action is never followed by a stale screen.
const FRESH_MS = 15 * 1000;
const responses = new Map(); // path -> { data, text, at }
// Writes that change nothing a screen shows: the model's bookkeeping and
// the upload outbox, which would otherwise empty the cache every second.
const PASSIVE_WRITES = /\/(prediction|vectors|media|complete|pick)$|^\/encounters$/;

function forgetResponses() {
  responses.clear();
}

// Signatures differ on every response; what is shown does not.
const comparable = (data) => JSON.stringify(data).replace(/\?[^"]*Signature=[^"]*/g, "");

// Bumped whenever a different screen is drawn, so a late refresh redraws
// only the screen it was fetched for.
let screen = 0;

async function cachedGet(path, redraw = render) {
  const hit = responses.get(path);
  if (hit && Date.now() - hit.at < FRESH_MS) return hit.data;
  if (hit) {
    const shown = screen;
    api(path)
      .then((data) => {
        const text = comparable(data);
        responses.set(path, { data, text, at: Date.now() });
        if (text !== hit.text && screen === shown) redraw();
      })
      .catch(() => {});
    return hit.data;
  }
  const data = await api(path);
  responses.set(path, { data, text: comparable(data), at: Date.now() });
  return data;
}

// --------------------------------------------------------------------------
// Chrome
// --------------------------------------------------------------------------

function toast(message, isError = false) {
  const node = el("div", {
    className: `toast${isError ? " error" : ""}`,
    textContent: message,
  });
  $("#toasts").append(node);
  setTimeout(() => node.remove(), isError ? 7000 : 3500);
}

const guard = (fn) => (...args) =>
  Promise.resolve()
    .then(() => fn(...args))
    .catch((err) => toast(err.message, true));

function showLogin() {
  let note = null;
  try {
    note = sessionStorage.getItem(LOGIN_NOTE_KEY);
    sessionStorage.removeItem(LOGIN_NOTE_KEY);
  } catch {
    /* no note to show */
  }
  $("#login-alert").textContent = note || "";
  $("#login-alert").hidden = !note;
  $("#login").hidden = false;
  $("#app").hidden = true;
}

async function refreshBadge() {
  const { photos } = await cachedGet("/stats");
  const badge = $("#queue-badge");
  badge.hidden = !photos.unlabeled;
  badge.textContent = photos.unlabeled > 99 ? "99+" : photos.unlabeled;
  badge.title = `${photos.unlabeled} unlabeled`;
}

async function refreshCats() {
  state.cats = (await cachedGet("/cats")).cats;
}

function setView(view) {
  if (!VIEWS[view] || (ADMIN_VIEWS.has(view) && !isAdmin())) view = homeView();
  if (state.view === "capture" && view !== "capture") capture?.leave();
  state.view = view;
  for (const tab of document.querySelectorAll(".tab")) {
    const active = tab.dataset.view === view;
    tab.classList.toggle("active", active);
    if (active) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
  window.scrollTo(0, 0);
  render();
}

const VIEWS = {
  capture: () => capture.render(),
  queue: renderQueue,
  cats: renderCats,
  stats: renderStats,
  admins: renderAdmins,
};
const ADMIN_VIEWS = new Set(["queue", "stats", "admins"]);

// Collaborators open the app to photograph a cat; admins to label.
const homeView = () => (isAdmin() ? "queue" : "capture");

// A re-render after an action keeps the current page on screen, dimmed,
// until the new one is ready — no blank flash, no jump to the top.
const render = guard(async function render() {
  screen += 1;
  const main = $("#main");
  if (main.childElementCount) main.classList.add("loading");
  else main.replaceChildren(el("div", { className: "spinner", textContent: "Loading…" }));
  try {
    await VIEWS[state.view]();
  } finally {
    main.classList.remove("loading");
  }
  if (isAdmin()) refreshBadge().catch(() => {});
});

function sectionHead(title, subtitle, actions = []) {
  return el("div", { className: "section-head" }, [
    el("div", { className: "section-title" }, [
      el("h2", { textContent: title }),
      subtitle ? el("p", { textContent: subtitle }) : null,
    ]),
    actions.length ? el("div", { className: "actions" }, actions) : null,
  ]);
}

function emptyState(cat, title, text) {
  return el("div", { className: "empty" }, [
    doodle(cat, "doodle empty-mark"),
    el("h3", { textContent: title }),
    text ? el("p", { textContent: text }) : null,
  ]);
}

// --------------------------------------------------------------------------
// Dialogs — a themed replacement for prompt()
// --------------------------------------------------------------------------

/**
 * Ask for one or more values. Resolves to {name: value} on OK, null on
 * cancel or Esc. The browser enforces `required`/`pattern` before the form
 * can submit; the API validates again regardless.
 */
function ask({ title, text, fields, ok = "Save" }) {
  const dialog = $("#ask");
  const form = el("form", { method: "dialog", className: "sheet-body" });
  const inputs = fields.map((field) => {
    const input = el("input", {
      name: field.name,
      type: field.type || "text",
      value: field.value ?? "",
      placeholder: field.placeholder || "",
      required: !!field.required,
      autocomplete: "off",
    });
    if (field.pattern) input.pattern = field.pattern;
    if (field.maxLength) input.maxLength = field.maxLength;
    if (field.type === "number") {
      input.min = 0;
      input.step = 1;
      input.inputMode = "numeric";
    }
    return el("label", { className: "field" }, [
      el("span", { textContent: field.label }),
      input,
      field.hint ? el("small", { textContent: field.hint }) : null,
    ]);
  });

  // Cancel is a plain button, not a submit: Enter in a field submits through
  // the form's *first* submit button, and that has to be OK.
  const cancel = el("button", { type: "button", className: "btn btn-ghost", textContent: "Cancel" });
  cancel.onclick = () => dialog.close();
  form.append(
    el("h3", { textContent: title }),
    text ? el("p", { className: "sheet-text", textContent: text }) : null,
    ...inputs,
    el("div", { className: "sheet-actions" }, [
      cancel,
      el("button", { className: "btn btn-primary", value: "ok", textContent: ok }),
    ]),
  );
  dialog.replaceChildren(form);
  dialog.returnValue = "";
  dialog.showModal();

  return new Promise((resolve) => {
    dialog.onclose = () =>
      resolve(
        dialog.returnValue === "ok"
          ? Object.fromEntries(new FormData(form).entries())
          : null,
      );
  });
}

/**
 * The app's own "are you sure?" — a sheet like ask(), never the browser's
 * bare confirm() box. Resolves true only on the confirming button; Cancel,
 * Esc and a tap on the backdrop all resolve false.
 */
function confirmAction({ title, text, ok, danger = true }) {
  const dialog = $("#ask");
  const form = el("form", { method: "dialog", className: "sheet-body confirm" });
  const cancel = el("button", { type: "button", className: "btn btn-ghost", textContent: "Cancel" });
  cancel.onclick = () => dialog.close();
  form.append(
    el("h3", { textContent: title }),
    text ? el("p", { className: "sheet-text", textContent: text }) : null,
    el("div", { className: "sheet-actions" }, [
      cancel,
      el("button", { className: `btn ${danger ? "btn-danger-solid" : "btn-primary"}`, value: "ok", textContent: ok }),
    ]),
  );
  dialog.replaceChildren(form);
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise((resolve) => {
    dialog.onclose = () => resolve(dialog.returnValue === "ok");
  });
}

// A click on the dimmed backdrop lands on the <dialog> itself, since all of
// its content sits inside .sheet-body.
function closeOnBackdrop(dialog) {
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}

// --------------------------------------------------------------------------
// Queue
// --------------------------------------------------------------------------

async function renderQueue() {
  const [{ sessions }] = await Promise.all([cachedGet("/queue"), refreshCats()]);
  const main = $("#main");

  if (!sessions.length) {
    main.replaceChildren(
      sectionHead("Labeling queue"),
      modelStrip(),
      emptyState(
        "cat-fluff",
        "All caught up",
        "Every photo has a cat. New ones land here as the bots receive them.",
      ),
    );
    // Nothing to guess, but the model still learns the labeled cats and
    // shares their vectors — Capture's guesses on every phone depend on it.
    if (recognition) {
      recognition.setNames(state.cats);
      recognition.watchQueue([]);
    }
    return;
  }

  const total = sessions.reduce((n, s) => n + s.photos.length, 0);
  main.replaceChildren(
    sectionHead(
      "Labeling queue",
      `${plural(sessions.length, "session")} · ${plural(total, "photo")} · oldest first`,
    ),
    modelStrip(),
    el(
      "div",
      { className: "session-list" },
      sessions.map((s) => sessionCard(s, sessions)),
    ),
  );
  if (recognition) {
    recognition.setNames(state.cats);
    recognition.watchQueue(sessions);
  }
}

// One line on what the model is doing. Its guesses never show here: they
// are revealed only after a session is labeled (openPicker).
function modelStrip() {
  if (!recognition || !isAdmin()) return null;
  const node = el("div", { className: "model-strip", attrs: { role: "status" } });
  const paint = (s) => {
    node.hidden = s.phase === "idle" || s.phase === "unavailable";
    node.dataset.phase = s.phase;
    node.replaceChildren(
      ...[
        el("span", { className: "model-dot", attrs: { "aria-hidden": "true" } }),
        el("span", { className: "model-text", textContent: `Model: ${s.detail}` }),
        s.progress != null ? el("progress", { max: 1, value: s.progress }) : null,
      ].filter(Boolean),
    );
  };
  paint(recognition.state);
  const stop = recognition.onChange((s) => (node.isConnected ? paint(s) : stop()));
  return node;
}

function sessionCard({ session, photos }, allSessions) {
  const sessionId = session.sessionId;

  const assign = button("Who is this?", "btn btn-primary", () =>
    openPicker({ session, photos }),
  );

  const merge = el("select", { className: "btn btn-select", attrs: { "aria-label": "Merge into another session" } });
  merge.append(el("option", { value: "", textContent: "Merge into…" }));
  for (const other of allSessions) {
    if (other.session.sessionId === sessionId) continue;
    merge.append(
      el("option", {
        value: other.session.sessionId,
        textContent: `${fmtDate(other.session.startedAt)} · ${plural(other.photos.length, "photo")}`,
      }),
    );
  }
  merge.disabled = allSessions.length < 2;
  merge.onchange = guard(async () => {
    if (!merge.value) return;
    const targetSessionId = merge.value;
    merge.value = "";
    const target = allSessions.find((other) => other.session.sessionId === targetSessionId);
    const ok = await confirmAction({
      title: "Merge these sessions?",
      text:
        `All ${plural(photos.length, "photo")} move into the session from ` +
        `${fmtDate(target?.session.startedAt)}. Do this when both are the same cat.`,
      ok: "Merge",
      danger: false,
    });
    if (!ok) return;
    await post("/sessions/merge", { sourceSessionId: sessionId, targetSessionId });
    toast("Sessions merged");
    render();
  });

  const remove = button("Delete", "btn btn-danger", async () => {
    const ok = await confirmAction({
      title: `Delete ${plural(photos.length, "photo")}?`,
      text: "The whole session is removed from storage for good. This cannot be undone.",
      ok: "Delete for good",
    });
    if (!ok) return;
    await post(`/sessions/${sessionId}/reject`);
    toast(`Deleted ${plural(photos.length, "photo")}`);
    render();
  });

  const facts = [
    plural(photos.length, "photo"),
    `via ${channelName(session.channel)}`,
    session.channel === "app" ? null : session.explicit ? "opened with New cat" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return el("article", { className: "card session" }, [
    el("header", { className: "card-head" }, [
      el("div", { className: "card-title", textContent: fmtDate(session.startedAt) || "Unknown date" }),
      el("div", { className: "meta", textContent: facts }),
      locationLink(session),
      el("div", { className: "meta mono session-id", textContent: sessionId }),
    ]),
    el("div", { className: "grid" }, photos.map((p) => thumb(p, photos))),
    el("footer", { className: "card-actions" }, [assign, merge, remove]),
  ]);
}

// The pin the submitter sent from the bot, already rounded to ~100 m. Two
// sessions pinned to the same spot are a hint they're the same cat.
function locationLink(session) {
  if (session.coarseLat == null || session.coarseLon == null) return null;
  const { coarseLat: lat, coarseLon: lon } = session;
  return el("a", {
    className: "meta place",
    href: `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=18/${lat}/${lon}`,
    target: "_blank",
    rel: "noopener",
    textContent: `📍 ${lat}, ${lon}${locationNote(session)}`,
  });
}

const confirmDeletePhoto = () =>
  confirmAction({
    title: "Delete this photo?",
    text: "It is removed from storage for good. This cannot be undone.",
    ok: "Delete for good",
  });

function locationNote(session) {
  if (session.locationSource === "map") return " · picked on map";
  if (session.locationSource === "app-gps") {
    return session.locationAccuracyM != null ? ` · phone GPS ±${session.locationAccuracyM} m` : " · phone GPS";
  }
  return "";
}

function thumb(photo, list) {
  const isVideo = photo.mediaType === "video";
  const media = isVideo
    ? el("video", { src: photo.videoUrl, muted: true, preload: "metadata", playsInline: true })
    : el("img", { src: photo.thumbUrl, alt: "", loading: "lazy" });
  const node = el("div", { className: "thumb" }, [media]);

  const flags = [
    isVideo ? "▶ video" : null,
    photo.nearDuplicateOf ? "near-dup" : null,
    photo.status === "duplicate" ? "duplicate" : null,
  ].filter(Boolean);
  for (const flag of flags) node.append(el("span", { className: "flag", textContent: flag }));

  const kill = el("button", {
    type: "button",
    className: "kill",
    textContent: "✕",
    title: "Delete photo",
    attrs: { "aria-label": "Delete photo" },
  });
  kill.onclick = guard(async (event) => {
    event.stopPropagation();
    if (!(await confirmDeletePhoto())) return;
    await post(`/photos/${photo.photoId}/reject`);
    toast("Photo deleted");
    render();
  });
  if (isAdmin()) node.append(kill);

  node.onclick = () => openLightbox(photo, list);
  return node;
}

// --------------------------------------------------------------------------
// Cat picker — you recognise the cat, not the name
// --------------------------------------------------------------------------

function openPicker({ session, photos }) {
  const dialog = $("#picker");
  const sessionId = session.sessionId;

  // The session's own photos stay in view while choosing, so the comparison
  // is photo-to-photo rather than photo-to-memory.
  const preview = el(
    "div",
    { className: "picker-preview" },
    photos
      .filter((p) => p.thumbUrl)
      .slice(0, 8)
      .map((p) => el("img", { src: p.thumbUrl, alt: "" })),
  );
  const search = el("input", {
    type: "search",
    className: "picker-search",
    placeholder: "Find a cat, or type a new name",
    autocomplete: "off",
    enterKeyHint: "done",
  });
  const grid = el("div", { className: "picker-grid" });

  recognition?.prioritize(sessionId);

  // The model's guess for this session was recorded before the picker
  // opened (or is still being made). It is shown only now, after the
  // person has chosen, so the label is theirs and not the model's.
  const revealGuess = (cat, isNew) => {
    if (!recognition) return;
    const line = recognition.reveal(sessionId, isNew ? null : cat.catId, cat.name);
    if (line) toast(line);
    recognition.learn(sessionId, cat.catId);
  };

  const assignTo = guard(async (cat) => {
    dialog.close();
    await post(`/sessions/${sessionId}/assign`, { catId: cat.catId });
    toast(`${plural(photos.length, "photo")} → ${cat.name}`);
    revealGuess(cat, false);
    render();
  });

  const createAndAssign = guard(async (name) => {
    dialog.close();
    const cat = await post("/cats", { name });
    await post(`/sessions/${sessionId}/assign`, { catId: cat.catId });
    toast(`New cat “${cat.name}” · ${plural(photos.length, "photo")} labeled`);
    revealGuess(cat, true);
    render();
  });

  function draw() {
    const query = search.value.trim();
    const needle = query.toLowerCase();
    const tiles = state.cats
      .filter((cat) => cat.name.toLowerCase().includes(needle))
      .sort(byName)
      .map((cat) => {
        const tile = el("button", { type: "button", className: "pick" }, [
          cat.coverUrl
            ? el("img", { src: cat.coverUrl, alt: "", loading: "lazy" })
            : el("span", { className: "pick-cover-empty" }, [doodle("cat-grump")]),
          el("span", { className: "pick-name", textContent: cat.name }),
          el("span", { className: "pick-count", textContent: plural(cat.photoCount || 0, "photo") }),
        ]);
        tile.onclick = () => assignTo(cat);
        return tile;
      });

    if (query && !state.cats.some((cat) => cat.name.toLowerCase() === needle)) {
      const make = el("button", { type: "button", className: "pick pick-new" }, [
        el("span", { className: "pick-plus", textContent: "+" }),
        el("span", { className: "pick-name", textContent: `“${query}”` }),
        el("span", { className: "pick-count", textContent: "new cat" }),
      ]);
      make.onclick = () => createAndAssign(query);
      tiles.push(make);
    }

    grid.replaceChildren(
      ...(tiles.length
        ? tiles
        : [el("p", { className: "picker-hint", textContent: "No cats yet — type a name to create the first one." })]),
    );
  }

  search.oninput = draw;
  search.onkeydown = (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const choices = grid.querySelectorAll(".pick");
    if (choices.length === 1) choices[0].click();
  };

  const close = el("button", {
    type: "button",
    className: "btn btn-ghost btn-icon",
    textContent: "✕",
    attrs: { "aria-label": "Close" },
  });
  close.onclick = () => dialog.close();

  dialog.replaceChildren(
    el("div", { className: "sheet-body picker" }, [
      el("div", { className: "sheet-head" }, [
        el("div", {}, [
          el("h3", { textContent: "Who is this?" }),
          el("p", {
            className: "sheet-text",
            textContent: `${plural(photos.length, "photo")} from ${fmtDate(session.startedAt)}`,
          }),
        ]),
        close,
      ]),
      preview,
      search,
      grid,
    ]),
  );
  draw();
  dialog.showModal();
  // On a phone, focusing the field would throw the keyboard over the cats.
  if (matchMedia("(hover: hover)").matches) search.focus();
}

// --------------------------------------------------------------------------
// Cats
// --------------------------------------------------------------------------

async function renderCats() {
  await refreshCats();
  const main = $("#main");

  const create = button("+ New cat", "btn btn-primary", async () => {
    const answer = await ask({
      title: "New cat",
      fields: [{ name: "name", label: "Name", required: true, maxLength: 80 }],
      ok: "Create",
    });
    if (!answer) return;
    await post("/cats", { name: answer.name.trim() });
    toast(`Created “${answer.name.trim()}”`);
    render();
  });

  const head = sectionHead("Cats", plural(state.cats.length, "cat") + " known", isAdmin() ? [create] : []);

  if (!state.cats.length) {
    main.replaceChildren(
      head,
      emptyState("cat-grump", "No cats yet", "Label a session in the queue to create the first one."),
    );
    return;
  }

  const filter = el("input", {
    type: "search",
    className: "filter",
    placeholder: "Filter by name",
    autocomplete: "off",
    attrs: { "aria-label": "Filter cats by name" },
  });
  const grid = el("div", { className: "cat-grid" });

  const cards = [...state.cats].sort(byName).map((cat) => {
    // A name alone is unnavigable once there are fifty of them — you
    // recognise the cat, not the string.
    const cover = cat.coverUrl
      ? el("img", { src: cat.coverUrl, alt: "", loading: "lazy" })
      : el("div", { className: "cat-cover-empty" }, [doodle("cat-grump")]);
    const card = el("button", { type: "button", className: "cat-card" }, [
      el("div", { className: "cat-cover" }, [cover]),
      el("span", { className: "cat-name", textContent: cat.name }),
      el("span", { className: "meta", textContent: plural(cat.photoCount || 0, "photo") }),
    ]);
    card.dataset.name = cat.name.toLowerCase();
    card.onclick = guard(() => openCat(cat.catId));
    return card;
  });
  grid.append(...cards);

  filter.oninput = () => {
    const needle = filter.value.trim().toLowerCase();
    for (const card of cards) card.hidden = !card.dataset.name.includes(needle);
  };

  main.replaceChildren(head, filter, grid);
}

async function openCat(catId, { redrawn = false } = {}) {
  screen += 1;
  const { cat, photos } = await cachedGet(`/cats/${catId}`, guard(() => openCat(catId, { redrawn: true })));

  const rename = button("Rename", "btn", async () => {
    const answer = await ask({
      title: "Rename cat",
      fields: [{ name: "name", label: "Name", value: cat.name, required: true, maxLength: 80 }],
    });
    const name = answer?.name.trim();
    if (!name || name === cat.name) return;
    await patch(`/cats/${catId}`, { name });
    toast("Renamed");
    openCat(catId);
  });

  const remove = button("Delete cat", "btn btn-danger", async () => {
    const ok = await confirmAction({
      title: `Delete “${cat.name}”?`,
      text: photos.length
        ? `${plural(photos.length, "photo")} still belong to this cat — the delete will be refused until they are moved or unassigned.`
        : "The cat has no photos left, so only its name goes.",
      ok: "Delete cat",
    });
    if (!ok) return;
    await api(`/cats/${catId}`, { method: "DELETE" });
    toast("Cat deleted");
    setView("cats");
  });

  const back = button("← All cats", "btn btn-ghost back", () => setView("cats"));

  if (!redrawn) window.scrollTo(0, 0);
  $("#main").replaceChildren(
    back,
    sectionHead(cat.name, plural(photos.length, "photo"), isAdmin() ? [rename, remove] : []),
    photos.length
      ? el("div", { className: "card" }, [
          el("div", { className: "grid" }, photos.map((p) => thumb(p, photos))),
        ])
      : emptyState("cat-calico", "No photos left", "Every photo of this cat was deleted or moved."),
  );
}

// --------------------------------------------------------------------------
// Stats
// --------------------------------------------------------------------------

// Sources the landing page can name on its own. A tracked link registered in
// the admin tool always wins over these.
const SOURCE_NAMES = {
  direct: ["Website, no source", "Typed the address, a bookmark, or an app that hides its links"],
  none: ["Bot, no tracked link", "Started the bot by name — or before tracking began"],
  referral: ["Other websites", "Linked from a site we don't know by name"],
  telegram: ["Telegram", "A link shared in a Telegram chat or channel"],
  whatsapp: ["WhatsApp", "A link shared in a WhatsApp chat"],
  instagram: ["Instagram", null],
  facebook: ["Facebook", null],
  google: ["Google", "Search results"],
  poster: ["Poster QR code", "The printed recruitment poster"],
};
// Slugs the page derives from the referrer or that mean "no link" — there is
// no tracked URL to hand out for these.
const UNLINKABLE = new Set(["direct", "none", "referral", "telegram", "whatsapp", "instagram", "facebook", "google"]);

const sourceName = (row) => row.link?.label || SOURCE_NAMES[row.referral]?.[0] || row.referral;

async function renderStats() {
  const [data, guesses] = await Promise.all([
    cachedGet("/insights"),
    cachedGet("/recognition/predictions").catch(() => null),
    refreshCats(),
  ]);
  const s = data.summary;

  const refresh = button("Refresh", "btn btn-sm", () => {
    forgetResponses();
    render();
  });
  $("#main").replaceChildren(
    sectionHead("Stats", `Updated ${fmtTime(data.generatedAt)} · days in Israel time`, [refresh]),
    statTiles(s, data.evalMinSessions),
    guesses ? recognitionPanel(guesses.predictions, guesses.picks) : null,
    sourcesPanel(data.referrals),
    activityPanel(data.daily),
    el("div", { className: "panel-row" }, [
      contributorsPanel(data.contributors, data.channels, s),
      healthPanel(s, data.stalled),
    ]),
    datasetPanel(data.cats, s, data.evalMinSessions),
  );
}

function panel(title, intro, actions, body) {
  return el("section", { className: "card panel" }, [
    el("header", { className: "panel-head" }, [
      el("div", {}, [
        el("h3", { textContent: title }),
        intro ? el("p", { textContent: intro }) : null,
      ]),
      actions?.length ? el("div", { className: "actions" }, actions) : null,
    ]),
    ...[].concat(body),
  ]);
}

function statTile({ label, value, delta, gauge, note }) {
  return el("div", { className: "stat" }, [
    el("div", { className: "stat-label", textContent: label }),
    el("div", { className: "stat-value", textContent: value }),
    delta || null,
    gauge || null,
    note ? el("div", { className: "stat-note", textContent: note }) : null,
  ]);
}

// "▲ 12 this week · 4 the week before" — the arrow and its colour say which
// way it moved, the words say by how much; neither relies on the other.
function weekTrend(thisWeek, lastWeek, noun) {
  const dir = thisWeek > lastWeek ? "up" : thisWeek < lastWeek ? "down" : "flat";
  const arrow = { up: "▲", down: "▼", flat: "■" }[dir];
  return el("div", { className: `stat-delta ${dir}` }, [
    el("span", { className: "arrow", textContent: arrow, attrs: { "aria-hidden": "true" } }),
    `${formatNumber(thisWeek)} ${noun} this week · ${formatNumber(lastWeek)} the week before`,
  ]);
}

function statTiles(s, minSessions) {
  const labeledShare = s.media ? Math.round((s.labeled / s.media) * 100) : 0;
  const waiting = s.people - s.contributors;
  return el("div", { className: "stats-grid" }, [
    statTile({
      label: "Photos & videos",
      value: formatNumber(s.media),
      delta: weekTrend(s.mediaThisWeek, s.mediaLastWeek, "new"),
      note: `${plural(s.videos, "video")} · ${plural(s.duplicates, "duplicate")} skipped`,
    }),
    statTile({
      label: "Contributors",
      value: formatNumber(s.contributors),
      note:
        `${formatNumber(s.newContributorsThisWeek)} new this week · ` +
        `${formatNumber(s.returningContributors)} came back another day` +
        (waiting > 0 ? ` · ${formatNumber(waiting)} started the bot, no photos yet` : ""),
    }),
    statTile({
      label: "Landing page visitors",
      value: formatNumber(s.visitorsThisWeek),
      delta: weekTrend(s.visitorsThisWeek, s.visitorsLastWeek, "visitors"),
      note: `${formatNumber(s.botClicksThisWeek)} pressed “send a photo” this week`,
    }),
    statTile({
      label: "Labeled",
      value: `${labeledShare}%`,
      gauge: meter(s.labeled, s.media),
      note: `${plural(s.unlabeled, "photo")} waiting in the queue`,
    }),
    statTile({
      label: "Cats ready to evaluate",
      value: `${formatNumber(s.catsReady)} of ${formatNumber(s.cats)}`,
      gauge: meter(s.catsReady, s.cats),
      note: `photos from ${minSessions}+ separate encounters`,
    }),
  ]);
}

// ---- where people come from ----

function sourcesPanel(referrals) {
  const add = button("+ Tracked link", "btn btn-sm btn-primary", () => addLink());
  return panel(
    "Where people come from",
    "Each source from first click to first photo, since tracking began. " +
      "A browser counts as one visitor per day; from the bot on, these are people.",
    [add],
    referrals.length
      ? el("div", { className: "sources" }, referrals.map(sourceRow))
      : el("p", {
          className: "muted",
          textContent: "Nothing yet. Visits appear here once the landing page has been opened.",
        }),
  );
}

function sourceRow(row) {
  const description = row.link
    ? `?src=${row.referral}`
    : SOURCE_NAMES[row.referral]?.[1] || `?src=${row.referral}`;

  const figures = [
    ["Visitors", row.referral === "none" ? null : row.visitors],
    ["Started bot", row.people],
    ["Sent photos", row.contributors],
    ["Photos", row.media],
  ];

  const summary = el("summary", { className: "source-summary" }, [
    el("div", { className: "source-name" }, [
      el("b", { textContent: sourceName(row) }),
      el("small", { textContent: description }),
    ]),
    el(
      "dl",
      { className: "source-figures" },
      figures.map(([label, value]) =>
        el("div", {}, [
          el("dt", { textContent: label }),
          el("dd", { textContent: value == null ? "—" : formatNumber(value) }),
        ]),
      ),
    ),
  ]);

  return el("details", { className: "source" }, [
    summary,
    el("div", { className: "source-body" }, [
      funnel(funnelSteps(row)),
      trackedLinks(row),
      sourceActions(row),
    ]),
  ]);
}

function funnelSteps(row) {
  const link = row.link || {};
  const steps = [];
  if (link.partnerViews != null) steps.push({ label: "Saw the ad", value: link.partnerViews, partner: true });
  if (link.partnerPlays != null) steps.push({ label: "Played", value: link.partnerPlays, partner: true });
  if (link.partnerClicks != null)
    steps.push({ label: "Clicked through", value: link.partnerClicks, partner: true });
  if (row.referral !== "none") {
    steps.push({ label: "Landed on the site", value: row.visitors });
    steps.push({ label: "Pressed “send a photo”", value: row.botClicks });
  }
  steps.push({ label: "Started the bot", value: row.people });
  steps.push({ label: "Sent photos", value: row.contributors });
  return steps;
}

function trackedLinks(row) {
  if (UNLINKABLE.has(row.referral)) return null;
  const site = `${config.siteUrl}?src=${row.referral}`;
  const bot = `${config.botUrl}?start=${row.referral}`;
  const copyRow = (label, url, hint) =>
    el("div", { className: "copy-row" }, [
      el("div", {}, [
        el("span", { className: "copy-label", textContent: label }),
        el("code", { textContent: url }),
        el("small", { textContent: hint }),
      ]),
      button("Copy", "btn btn-sm", async () => {
        await navigator.clipboard.writeText(url);
        toast("Link copied");
      }),
    ]);
  return el("div", { className: "copy-list" }, [
    copyRow("Landing page", site, "The one to hand out — counts the visit, then the bot."),
    copyRow("Straight to the bot", bot, "Skips the landing page, so visits and clicks can't be counted."),
  ]);
}

function sourceActions(row) {
  if (row.link) {
    return el("div", { className: "actions" }, [
      button("Partner numbers…", "btn btn-sm", () => editPartnerNumbers(row)),
      button("Rename", "btn btn-sm btn-ghost", () => renameLink(row)),
      button("Remove name", "btn btn-sm btn-ghost", () => removeLink(row)),
    ]);
  }
  if (UNLINKABLE.has(row.referral)) return null;
  // Seen in the data under a slug nobody registered — e.g. ?src=poster.
  return el("div", { className: "actions" }, [
    button("Give this source a name", "btn btn-sm", () => addLink(row.referral)),
  ]);
}

const SLUG_PATTERN = "[a-z0-9][a-z0-9\\-]{0,31}";

async function addLink(slug = "") {
  const answer = await ask({
    title: slug ? "Name this source" : "New tracked link",
    text:
      "Hand the link to whoever is sending people our way. Everyone who arrives " +
      "through it — and every photo they later send — is counted under this name.",
    fields: [
      { name: "label", label: "Name", placeholder: "Dana's game app", required: true, maxLength: 60 },
      {
        name: "slug",
        label: "Link code",
        value: slug,
        placeholder: "dana-app",
        required: true,
        pattern: SLUG_PATTERN,
        maxLength: 32,
        hint: "Lowercase letters, digits and dashes. It goes in the link as ?src=…",
      },
    ],
    ok: slug ? "Save" : "Create link",
  });
  if (!answer) return;
  await post("/links", { label: answer.label.trim(), slug: answer.slug.trim() });
  toast("Tracked link saved");
  render();
}

async function editPartnerNumbers(row) {
  const link = row.link;
  const answer = await ask({
    title: `${link.label}: their numbers`,
    text:
      "Running totals from the partner's own dashboard. They go at the top of " +
      "this source's funnel, above what we measure ourselves.",
    fields: [
      { name: "partnerViews", label: "Saw the ad", type: "number", value: link.partnerViews ?? "" },
      { name: "partnerPlays", label: "Played", type: "number", value: link.partnerPlays ?? "" },
      { name: "partnerClicks", label: "Clicked through to us", type: "number", value: link.partnerClicks ?? "" },
    ],
  });
  if (!answer) return;
  const body = Object.fromEntries(
    Object.entries(answer).map(([key, value]) => [key, value === "" ? null : Number(value)]),
  );
  await patch(`/links/${row.referral}`, body);
  toast("Partner numbers saved");
  render();
}

async function renameLink(row) {
  const answer = await ask({
    title: "Rename source",
    fields: [{ name: "label", label: "Name", value: row.link.label, required: true, maxLength: 60 }],
  });
  if (!answer) return;
  await patch(`/links/${row.referral}`, { label: answer.label.trim() });
  render();
}

async function removeLink(row) {
  const ok = await confirmAction({
    title: `Forget “${row.link.label}”?`,
    text: `Its name and partner numbers go. Visits already counted stay, under ?src=${row.referral}.`,
    ok: "Forget",
  });
  if (!ok) return;
  await api(`/links/${row.referral}`, { method: "DELETE" });
  render();
}

// ---- activity over time ----

function activityPanel(daily) {
  const axis = [fmtDay(daily[0].date), "today"];
  // Three charts on their own scales rather than one chart with two axes:
  // visitors and photos differ by an order of magnitude.
  const series = [
    ["media", "Photos received", "photos"],
    ["visitors", "Landing page visitors", "visitors"],
    ["newPeople", "New people in the bot", "new people"],
  ];
  const charts = series.map(([key, title, unit]) => {
    const total = daily.reduce((n, d) => n + d[key], 0);
    return el("figure", { className: "chart" }, [
      el("figcaption", {}, [el("span", { textContent: title }), el("b", { textContent: formatNumber(total) })]),
      columnChart({
        points: daily.map((d) => ({ label: fmtDayLong(d.date), value: d[key] })),
        unit,
        axis,
      }),
    ]);
  });

  const asTable = el("details", { className: "as-table" }, [
    el("summary", { textContent: "Show as a table" }),
    table(
      ["Day", "Photos", "Visitors", "Pressed button", "New in bot"],
      [...daily]
        .reverse()
        .map((d) => [fmtDayLong(d.date), d.media, d.visitors, d.botClicks, d.newPeople]),
    ),
  ]);

  return panel("Last 30 days", null, [], [el("div", { className: "charts" }, charts), asTable]);
}

// ---- contributors ----

function contributorsPanel(c, channels, s) {
  const callout =
    c.topShare >= 0.5
      ? el("p", {
          className: "callout",
          textContent:
            `One person sent ${Math.round(c.topShare * 100)}% of all photos. ` +
            "The dataset is only as varied as the people behind it — more " +
            "photographers means more angles, light and cats.",
        })
      : null;

  const buckets = barList(
    c.buckets.map((b) => ({
      label: b.label === "1 photo" ? "Sent 1 photo" : `Sent ${b.label}`,
      value: b.count,
      display: people(b.count),
    })),
  );

  const channelLine = el("p", {
    className: "muted",
    textContent: channels.length
      ? channels
          .map((ch) => `${channelName(ch.channel)}: ${people(ch.contributors)}, ${plural(ch.media, "photo")}`)
          .join(" · ")
      : "No photos yet.",
  });

  const top = c.top.length
    ? table(
        ["Contributor", "Photos", "Sessions", "Cats", "Days", "Source", "Last photo"],
        c.top.map((t) => [
          `#${t.id} · ${channelName(t.channel)}`,
          t.media,
          t.sessions,
          t.cats,
          t.activeDays,
          SOURCE_NAMES[t.referral]?.[0] || t.referral,
          fmtShortDate(t.lastSeen),
        ]),
      )
    : null;

  return panel(
    "Contributors",
    `${people(s.contributors)} have sent photos. IDs are the first characters of a salted hash — enough to tell people apart here, and nowhere else.`,
    [],
    [callout, buckets, channelLine, top],
  );
}

function healthPanel(s, stalled = { count: 0, items: [] }) {
  const perSession = s.sessions ? (s.media / s.sessions).toFixed(1) : "0";
  const rows = [
    ["Sessions with a location", `${formatNumber(s.sessionsWithLocation)} of ${formatNumber(s.sessions)}`, meter(s.sessionsWithLocation, s.sessions)],
    ["Photos per session, on average", perSession, null],
    ["Videos", formatNumber(s.videos), null],
    ["Duplicates caught", formatNumber(s.duplicates), null],
    ["Started the bot, sent nothing yet", formatNumber(Math.max(0, s.people - s.contributors)), null],
    ["Uploads that never arrived", formatNumber(stalled.count), null],
  ];
  return panel(
    "Bot health",
    "How the collection side is behaving.",
    [],
    [
      el(
        "dl",
        { className: "facts" },
        rows.map(([label, value, gauge]) =>
          el("div", {}, [el("dt", { textContent: label }), el("dd", {}, [value, gauge])]),
        ),
      ),
      stalled.count ? stalledList(stalled) : null,
    ],
  );
}

// Records written as `pending` whose file was never confirmed, an hour or
// more ago (spec §10 write order). The bots have already asked the sender
// to try again; this is so an admin sees that it happened at all.
function stalledList(stalled) {
  const shown = stalled.items.map(
    (item) => `${fmtDate(item.createdAt)} · ${channelName(item.channel)} · photo ${item.photoId}`,
  );
  const more = stalled.count - stalled.items.length;
  if (more > 0) shown.push(`and ${formatNumber(more)} more`);
  return el("div", { className: "muted small" }, [
    el("p", { textContent: "Written, but the photo or video never reached storage:" }),
    el("ul", {}, shown.map((line) => el("li", { textContent: line }))),
  ]);
}

// ---- dataset readiness ----

const CATS_SHOWN = 12;

function datasetPanel(cats, s, minSessions) {
  const rows = cats.map((cat) => ({
    label: cat.name,
    value: cat.media,
    display: plural(cat.media, "photo"),
    note: `${plural(cat.sessions, "session")} · ${plural(cat.contributors, "photographer")}`,
    tag: cat.ready ? "✓ ready" : "needs another encounter",
    tagTone: cat.ready ? "good" : "",
  }));
  const max = Math.max(1, ...rows.map((r) => r.value));
  const list = barList(rows.slice(0, CATS_SHOWN), { max });

  const more =
    rows.length > CATS_SHOWN
      ? button(`Show all ${rows.length} cats`, "btn btn-sm btn-ghost", () => {
          list.replaceWith(barList(rows, { max }));
          more.remove();
        })
      : null;

  return panel(
    "Dataset readiness",
    `A cat can be evaluated once it has photos from ${minSessions} or more separate ` +
      "encounters: one goes into training, another into the held-out test. " +
      "Forty frames of one burst are still one encounter.",
    [],
    [
      el("div", { className: "readiness" }, [
        el("b", { textContent: `${formatNumber(s.catsReady)} of ${plural(s.cats, "cat")} ready` }),
        meter(s.catsReady, s.cats),
      ]),
      cats.length ? list : el("p", { className: "muted", textContent: "No cats yet." }),
      more,
    ],
  );
}

// ---- the model, measured ----

// Two measurements of the same ranking, read the same way (recognition.js
// summarize): live guesses recorded before a person labeled the session, and
// a replay over sessions already labeled, each hidden from the model in turn.
function recognitionPanel(predictions, picks = []) {
  const catName = (id) => state.cats.find((c) => c.catId === id)?.name || "(merged or deleted)";

  // The newest model version only — two versions' guesses are not one number.
  const latest = predictions.reduce(
    (a, p) => (!a || p.predictedAt > a.predictedAt ? p : a),
    null,
  )?.modelVersion;
  const current = predictions.filter((p) => p.modelVersion === latest);
  const measured = current
    .filter((p) => p.truthCatId)
    .map((p) => scoreRow({ sessionId: p.sessionId, catId: p.truthCatId, ranked: p.ranked }));
  const waiting = current.length - measured.length;

  const live = el("div", { className: "model-block" }, [
    el("h4", { textContent: "Live: guessed before labeling" }),
    measured.length
      ? modelResults(summarize(measured), catName)
      : el("p", {
          className: "muted",
          textContent: latest
            ? "No guessed session has been labeled yet."
            : "No guesses yet. Open the queue: the model guesses every session there.",
        }),
    el("p", {
      className: "muted small",
      textContent:
        (latest ? `Model ${latest}. ` : "") +
        (waiting ? `${formatNumber(waiting)} ${waiting === 1 ? "guess" : "guesses"} waiting for a label.` : ""),
    }),
  ]);

  const replayOut = el("div");
  const say = (text) => replayOut.replaceChildren(el("p", { className: "muted", textContent: text }));
  const run = button("Replay on labeled sessions", "btn btn-sm", async () => {
    run.disabled = true;
    // Downloading and learning can take minutes the first time; say so.
    const stop = recognition.onChange((st) => say(`Model: ${st.detail}`));
    try {
      say("Loading the model…");
      const rows = await recognition.replay((done, total) => {
        stop();
        say(`Replaying ${done} of ${total} sessions…`);
      });
      replayOut.replaceChildren(modelResults(summarize(rows), catName));
    } catch (err) {
      replayOut.replaceChildren();
      throw err;
    } finally {
      stop();
      run.disabled = false;
    }
  });
  const replay = el("div", { className: "model-block" }, [
    el("h4", { textContent: "Replay: every labeled session, hidden in turn" }),
    el("p", {
      className: "muted small",
      textContent:
        "Each session is matched against the cat's other sessions and every other cat. " +
        "The first run downloads the model (about 40 MB, once) and looks at every labeled photo once.",
    }),
    run,
    replayOut,
  ]);

  const loop = el("div", { className: "model-block" }, [
    el("h4", { textContent: "Contributors: the app's guess, their answer" }),
    picksResults(picks, catName),
  ]);

  return panel(
    "Recognition model",
    "The model ranks the known cats for every session in the queue and records that " +
      "ranking before anyone labels it. Nobody sees it until they have chosen. It only " +
      "ranks: there is no auto-accept and no “new cat” verdict until these numbers earn one.",
    [],
    [live, loop, replay],
  );
}

// The product loop: the phone showed its top three, a contributor answered,
// and an admin later labeled the encounter without seeing either. Scored
// against that label — the "pick from 3" the public app will run.
function picksResults(picks, catName) {
  const scored = picks.filter((p) => p.truthCatId);
  if (!scored.length) {
    return el("p", {
      className: "muted",
      textContent: picks.length
        ? `${plural(picks.length, "answer")} waiting for a label.`
        : "No answers yet. Contributors who turn on cat guesses in Capture answer here.",
    });
  }
  const knownBefore = (p) => p.ranked.some((r) => r.catId === p.truthCatId);
  const cat = scored.filter((p) => p.choice === "cat");
  const right = cat.filter((p) => p.catId === p.truthCatId).length;
  const none = scored.filter((p) => p.choice === "none");
  const noneRight = none.filter((p) => !p.shown.includes(p.truthCatId)).length;
  const unsure = scored.filter((p) => p.choice === "unsure").length;
  const offered = scored.filter((p) => p.shown.includes(p.truthCatId)).length;
  const pct = (n, d) => (d ? `${Math.round((n / d) * 100)}%` : "—");

  const perCat = new Map();
  for (const p of cat) {
    const row = perCat.get(p.truthCatId) || { answers: 0, right: 0 };
    row.answers += 1;
    if (p.catId === p.truthCatId) row.right += 1;
    perCat.set(p.truthCatId, row);
  }
  return el("div", {}, [
    el("div", { className: "stats-grid model-grid" }, [
      statTile({ label: "Picked a cat, and right", value: pct(right, cat.length), note: `${right} of ${cat.length}` }),
      statTile({
        label: "Right cat was offered",
        value: pct(offered, scored.length),
        note: `in the three shown, ${offered} of ${scored.length} encounters`,
      }),
      statTile({
        label: "“None of these”",
        value: formatNumber(none.length),
        note: `${noneRight} rightly: the cat was not among the three`,
      }),
      statTile({ label: "“Not sure”", value: formatNumber(unsure), note: `of ${scored.length} answered encounters` }),
    ]),
    el("p", {
      className: "muted small",
      textContent:
        `${scored.filter(knownBefore).length} of ${scored.length} were cats the app already knew. ` +
        (picks.length > scored.length ? `${picks.length - scored.length} more waiting for a label.` : ""),
    }),
    perCat.size
      ? table(
          ["Cat", "Answers", "Right"],
          [...perCat].map(([id, r]) => [catName(id), r.answers, r.right]),
        )
      : null,
  ]);
}

function modelResults(sum, catName) {
  const pct = (n) => (sum.known ? `${Math.round((n / sum.known) * 100)}%` : "—");
  const chance = (k) =>
    sum.candidates ? `chance ≈ ${Math.round(Math.min(1, k / sum.candidates) * 100)}%` : "";
  const score = (x) => (x == null ? "—" : x.toFixed(2));
  return el("div", {}, [
    el("div", { className: "stats-grid model-grid" }, [
      statTile({ label: "Right cat first", value: pct(sum.top1), note: `${sum.top1} of ${sum.known} · ${chance(1)}` }),
      statTile({ label: "In the top 3", value: pct(sum.top3), note: `${sum.top3} of ${sum.known} · ${chance(3)}` }),
      statTile({ label: "In the top 5", value: pct(sum.top5), note: `${sum.top5} of ${sum.known} · ${chance(5)}` }),
      statTile({
        label: "Cats it had never seen",
        value: formatNumber(sum.fresh),
        note: "sessions of a cat with no other photos; only a threshold could catch these",
      }),
    ]),
    el("p", {
      className: "muted small",
      textContent:
        `Median top score: right ${score(sum.medianTop.right)} · wrong ${score(sum.medianTop.wrong)} · ` +
        `never-seen ${score(sum.medianTop.fresh)}. While these overlap, no threshold can say ` +
        "“this is her” or “new cat”.",
    }),
    sum.perCat.length
      ? table(
          ["Cat", "Sessions", "Right first", "In top 3"],
          sum.perCat.map((c) => [catName(c.catId), c.sessions, c.top1, c.top3]),
        )
      : null,
  ]);
}

// A table that turns into labelled stacks on a phone (styles.css): each cell
// carries its column name for the narrow layout to show.
function table(columns, rows) {
  return el("div", { className: "table-wrap" }, [
    el("table", { className: "table" }, [
      el("thead", {}, [el("tr", {}, columns.map((c) => el("th", { textContent: c })))]),
      el(
        "tbody",
        {},
        rows.map((cells) =>
          el(
            "tr",
            {},
            cells.map((cell, i) =>
              el("td", {
                textContent: typeof cell === "number" ? formatNumber(cell) : cell ?? "—",
                attrs: { "data-label": columns[i] },
              }),
            ),
          ),
        ),
      ),
    ]),
  ]);
}

// --------------------------------------------------------------------------
// Admins
// --------------------------------------------------------------------------

const ROLE_HELP = {
  admin: "Everything: labeling, new cats, merging, deleting, stats and people.",
  collaborator: "Photographs cats in the app and browses the cats. No labeling, no deleting.",
};

async function renderAdmins() {
  const { admins } = await cachedGet("/admins");

  const input = el("input", {
    type: "email",
    required: true,
    placeholder: "someone@gmail.com",
    autocomplete: "off",
    attrs: { "aria-label": "Google account email" },
  });
  const role = roleSelect("collaborator", "Role for the new person");
  const form = el("form", { className: "inline-form" }, [
    input,
    role,
    el("button", { className: "btn btn-primary", textContent: "Add" }),
  ]);
  form.onsubmit = guard(async (event) => {
    event.preventDefault();
    const email = input.value.trim();
    await post("/admins", { email, role: role.value });
    toast(`${email} can now sign in as ${role.value === "admin" ? "an admin" : "a collaborator"}`);
    render();
  });

  const byRole = (a, b) => (a.role === b.role ? a.email.localeCompare(b.email) : a.role === "admin" ? -1 : 1);

  $("#main").replaceChildren(
    sectionHead("People", "Only these Google accounts can sign in."),
    el("div", { className: "card" }, [
      form,
      el("dl", { className: "role-help" }, [
        ...["admin", "collaborator"].flatMap((r) => [
          el("dt", { textContent: r === "admin" ? "Admin" : "Collaborator" }),
          el("dd", { textContent: ROLE_HELP[r] }),
        ]),
      ]),
      ...[...admins].sort(byRole).map((admin) => {
        const you = admin.email === state.email;
        const remove = button("Remove", "btn btn-sm btn-danger", async () => {
          const ok = await confirmAction({
            title: "Remove this person?",
            text: `${admin.email} will no longer be able to sign in. Photos they sent stay.`,
            ok: "Remove",
          });
          if (!ok) return;
          await api(`/admins/${encodeURIComponent(admin.email)}`, { method: "DELETE" });
          toast("Removed");
          render();
        });
        remove.disabled = you;

        const select = roleSelect(admin.role, `Role of ${admin.email}`);
        select.disabled = you;
        select.title = you ? "Nobody can change their own role" : "";
        select.onchange = guard(async () => {
          if (select.value === "admin") {
            const ok = await confirmAction({
              title: "Make this person an admin?",
              text: `${admin.email} will be able to label, merge and delete photos, and manage people.`,
              ok: "Make admin",
              danger: false,
            });
            if (!ok) {
              select.value = admin.role;
              return;
            }
          }
          await patch(`/admins/${encodeURIComponent(admin.email)}`, { role: select.value });
          toast(`${admin.email} is now ${select.value === "admin" ? "an admin" : "a collaborator"}`);
          render();
        });

        return el("div", { className: "row person" }, [
          el("span", { className: "row-main", textContent: admin.email }),
          you
            ? el("span", { className: "tag", textContent: "you" })
            : admin.addedAt === "bootstrap"
              ? el("span", { className: "tag", textContent: "bootstrap" })
              : null,
          select,
          remove,
        ]);
      }),
    ]),
  );
}

function roleSelect(value, label) {
  const select = el("select", { className: "btn btn-select btn-sm", attrs: { "aria-label": label } }, [
    el("option", { value: "collaborator", textContent: "Collaborator" }),
    el("option", { value: "admin", textContent: "Admin" }),
  ]);
  select.value = value;
  return select;
}

// --------------------------------------------------------------------------
// Lightbox — steps through the session (or cat) a photo was opened from
// --------------------------------------------------------------------------

const lightbox = { list: [], index: 0 };

function openLightbox(photo, list = [photo]) {
  lightbox.list = list;
  lightbox.index = Math.max(0, list.indexOf(photo));
  showLightboxPhoto();
  $("#lightbox").hidden = false;
  document.body.classList.add("no-scroll");
}

function showLightboxPhoto() {
  const photo = lightbox.list[lightbox.index];
  const isVideo = photo.mediaType === "video";

  $("#lightbox-img").hidden = isVideo;
  $("#lightbox-video").hidden = !isVideo;
  if (isVideo) {
    $("#lightbox-img").removeAttribute("src");
    $("#lightbox-video").src = photo.videoUrl;
  } else {
    $("#lightbox-video").pause();
    $("#lightbox-video").removeAttribute("src");
    $("#lightbox-img").src = photo.mediumUrl;
  }

  $("#lightbox-reject").hidden = !isAdmin();
  const many = lightbox.list.length > 1;
  for (const nav of document.querySelectorAll(".lightbox-nav")) nav.hidden = !many;
  $("#lightbox-count").textContent = many ? `${lightbox.index + 1} / ${lightbox.list.length}` : "";

  const catName = state.cats.find((c) => c.catId === photo.catId)?.name;
  $("#lightbox-caption").textContent = [
    photo.capturedAt ? fmtDate(photo.capturedAt) : null,
    photo.width && photo.height ? `${photo.width}×${photo.height}` : null,
    photo.durationSeconds ? `${photo.durationSeconds}s` : null,
    catName || (photo.catId ? "labeled" : photo.status),
  ]
    .filter(Boolean)
    .join(" · ");
}

function stepLightbox(delta) {
  const n = lightbox.list.length;
  if (n < 2) return;
  lightbox.index = (lightbox.index + delta + n) % n;
  showLightboxPhoto();
}

function closeLightbox() {
  if ($("#lightbox").hidden) return;
  $("#lightbox").hidden = true;
  $("#lightbox-img").removeAttribute("src");
  $("#lightbox-video").pause();
  $("#lightbox-video").removeAttribute("src");
  document.body.classList.remove("no-scroll");
}

function wireLightbox() {
  $(".lightbox-close").onclick = closeLightbox;
  $(".lightbox-nav.prev").onclick = () => stepLightbox(-1);
  $(".lightbox-nav.next").onclick = () => stepLightbox(1);
  $("#lightbox").onclick = (event) => {
    if (event.target.id === "lightbox" || event.target.classList.contains("lightbox-stage")) closeLightbox();
  };

  // Swipe left/right on a phone. A mostly-vertical drag is left alone.
  let start = null;
  const stage = $(".lightbox-stage");
  stage.addEventListener("pointerdown", (e) => (start = { x: e.clientX, y: e.clientY }));
  stage.addEventListener("pointerup", (e) => {
    if (!start) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    start = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) stepLightbox(dx < 0 ? 1 : -1);
  });

  $("#lightbox-reject").onclick = guard(async () => {
    const photo = lightbox.list[lightbox.index];
    if (!photo || !(await confirmDeletePhoto())) return;
    await post(`/photos/${photo.photoId}/reject`);
    toast("Photo deleted");
    lightbox.list = lightbox.list.filter((p) => p !== photo);
    if (!lightbox.list.length) closeLightbox();
    else {
      lightbox.index = Math.min(lightbox.index, lightbox.list.length - 1);
      showLightboxPhoto();
    }
    render();
  });

  document.addEventListener("keydown", (event) => {
    if ($("#lightbox").hidden) return;
    if (event.key === "Escape") closeLightbox();
    if (event.key === "ArrowLeft") stepLightbox(-1);
    if (event.key === "ArrowRight") stepLightbox(1);
  });
}

// --------------------------------------------------------------------------
// Formatting
// --------------------------------------------------------------------------

const plural = (n, word) => `${formatNumber(n)} ${word}${n === 1 ? "" : "s"}`;
const people = (n) => (n === 1 ? "1 person" : `${formatNumber(n)} people`);
const byName = (a, b) => a.name.localeCompare(b.name);

function channelName(channel) {
  return { whatsapp: "WhatsApp", telegram: "Telegram", app: "the app" }[channel] || "Telegram";
}

function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function fmtShortDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

// Calendar days from the API are plain YYYY-MM-DD; read them as local noon
// so no timezone can tip them onto the neighbouring day.
const dayDate = (day) => new Date(`${day}T12:00:00`);
const fmtDay = (day) => dayDate(day).toLocaleDateString(undefined, { day: "numeric", month: "short" });
const fmtDayLong = (day) =>
  dayDate(day).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });

// --------------------------------------------------------------------------
// Boot
// --------------------------------------------------------------------------

function claims(token) {
  try {
    return JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return {};
  }
}

async function boot() {
  if (!isInstalled()) {
    showInstallPage();
    return;
  }
  config = await (await fetch("/config.json")).json();

  $("#login-button").onclick = guard(login);
  $("#logout").onclick = () => logout();
  wireLightbox();
  closeOnBackdrop($("#picker"));
  closeOnBackdrop($("#ask"));
  for (const tab of document.querySelectorAll(".tab")) {
    tab.onclick = () => setView(tab.dataset.view);
  }

  await consumeCallback();

  const token = await idToken();
  if (!token) {
    showLogin();
    return;
  }

  state.email = (claims(token).email || "").toLowerCase();
  // The role is not in the token — it lives on the allowlist item, so a
  // change takes effect on the next load rather than at token expiry.
  try {
    state.role = (await api("/me")).role;
    localStorage.setItem(ROLE_KEY, state.role);
  } catch (err) {
    if (err.status === 403) {
      // Signed in fine, but not on the list (or taken off it). Forget the
      // tokens, or every launch would try them again and land here again.
      forgetSignIn(
        `${state.email || "This Google account"} is not an admin or collaborator. ` +
          "Sign in with a different Google account.",
      );
      showLogin();
      return;
    }
    state.role = localStorage.getItem(ROLE_KEY);
    if (err.status || !state.role) throw err; // refused, or never signed in here
  }
  document.body.dataset.role = state.role;
  $("#brand-role").textContent = isAdmin() ? "labeling desk" : "collaborator";
  for (const tab of document.querySelectorAll(".tab")) {
    tab.hidden = ADMIN_VIEWS.has(tab.dataset.view) && !isAdmin();
  }
  recognition = createRecognition({ api, post });
  capture = createCapture({
    el,
    button,
    toast,
    api,
    cachedGet,
    post,
    sectionHead,
    plural,
    fmtDate,
    emptyState,
    recognition,
  });

  $("#who-email").textContent = state.email;
  $("#login").hidden = true;
  $("#app").hidden = false;
  setView(capture.hasOpenEncounter() ? "capture" : homeView());
}

// Installable, and the app shell opens without a connection. sw.js never
// touches /api/ or photos, and fetches code from the network first, so a
// deploy still reaches everyone on their next load (web.tf).
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

boot().catch((err) => {
  if (!isInstalled()) return;
  showLogin();
  toast(err.message, true);
});
