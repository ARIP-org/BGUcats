// Admin labeling tool. No framework and no build step on purpose: the whole
// client is three files served straight from S3, which keeps the deploy path
// to "upload the file" and keeps this readable without a toolchain.

const $ = (sel) => document.querySelector(sel);
const el = (tag, props = {}, kids = []) => {
  const node = Object.assign(document.createElement(tag), props);
  for (const kid of [].concat(kids)) {
    if (kid) node.append(kid);
  }
  return node;
};

let config = null;
let state = { view: "queue", cats: [], email: null };

// --------------------------------------------------------------------------
// Auth — Cognito hosted UI, authorization code + PKCE
// --------------------------------------------------------------------------

const TOKENS_KEY = "bgucats.tokens";
const VERIFIER_KEY = "bgucats.pkce";

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
  });
  location.assign(`https://${config.cognitoDomain}/oauth2/authorize?${params}`);
}

function logout() {
  localStorage.removeItem(TOKENS_KEY);
  const params = new URLSearchParams({
    client_id: config.userPoolClientId,
    logout_uri: config.redirectUri,
  });
  location.assign(`https://${config.cognitoDomain}/logout?${params}`);
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
  } catch {
    localStorage.removeItem(TOKENS_KEY);
    return null;
  }
}

async function consumeCallback() {
  const params = new URLSearchParams(location.search);
  const code = params.get("code");
  if (params.get("error")) {
    // Cognito rejected the sign-up — almost always the pre-sign-up trigger
    // refusing an email that is not on the allowlist.
    toast(params.get("error_description") || params.get("error"), true);
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
  if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
  return data;
}

const post = (path, body) =>
  api(path, { method: "POST", body: JSON.stringify(body || {}) });

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
  fn(...args).catch((err) => toast(err.message, true));

function showLogin() {
  $("#login").hidden = false;
  $("#app").hidden = true;
}

async function refreshStats() {
  const { photos, cats } = await api("/stats");
  $("#stats").replaceChildren(
    el("span", {}, [`unlabeled `, el("b", { textContent: photos.unlabeled })]),
    el("span", {}, [`labeled `, el("b", { textContent: photos.labeled })]),
    el("span", {}, [`duplicates `, el("b", { textContent: photos.duplicate })]),
    el("span", {}, [`cats `, el("b", { textContent: cats })]),
  );
}

async function refreshCats() {
  state.cats = (await api("/cats")).cats;
}

function setView(view) {
  state.view = view;
  for (const tab of document.querySelectorAll(".tab")) {
    tab.classList.toggle("active", tab.dataset.view === view);
  }
  render();
}

const VIEWS = { queue: renderQueue, cats: renderCats, admins: renderAdmins };

const render = guard(async function render() {
  $("#main").replaceChildren(el("div", { className: "spinner", textContent: "Loading…" }));
  await VIEWS[state.view]();
  refreshStats().catch(() => {});
});

// --------------------------------------------------------------------------
// Queue
// --------------------------------------------------------------------------

async function renderQueue() {
  const [{ sessions }] = await Promise.all([api("/queue"), refreshCats()]);
  const main = $("#main");

  if (!sessions.length) {
    main.replaceChildren(
      el("div", { className: "empty" }, [
        el("span", { className: "empty-mark", textContent: "🎉" }),
        el("div", { textContent: "Queue is empty — every photo is labeled." }),
      ]),
    );
    return;
  }

  const total = sessions.reduce((n, s) => n + s.photos.length, 0);
  main.replaceChildren(
    el("div", { className: "section-head" }, [
      el("h2", { textContent: "Labeling queue" }),
      el("span", {
        textContent: `${sessions.length} sessions · ${total} photos · oldest first`,
      }),
    ]),
    ...sessions.map((s) => sessionCard(s, sessions)),
  );
}

function sessionCard({ session, photos }, allSessions) {
  const sessionId = session.sessionId;
  const started = session.startedAt ? fmtDate(session.startedAt) : "unknown date";

  const catSelect = el("select");
  catSelect.append(el("option", { value: "", textContent: "Assign to cat…" }));
  for (const cat of state.cats) {
    catSelect.append(
      el("option", {
        value: cat.catId,
        textContent: `${cat.name} (${cat.photoCount || 0})`,
      }),
    );
  }
  catSelect.onchange = guard(async () => {
    if (!catSelect.value) return;
    const catId = catSelect.value;
    catSelect.value = "";
    await post(`/sessions/${sessionId}/assign`, { catId });
    toast(`Session assigned · ${photos.length} photos labeled`);
    render();
  });

  const newCat = el("button", {
    className: "btn btn-primary",
    textContent: "+ New cat",
  });
  newCat.onclick = guard(async () => {
    const name = prompt("Name for this cat:");
    if (!name?.trim()) return;
    const cat = await post("/cats", { name: name.trim() });
    await post(`/sessions/${sessionId}/assign`, { catId: cat.catId });
    toast(`Created “${cat.name}” and assigned ${photos.length} photos`);
    render();
  });

  const mergeSelect = el("select");
  mergeSelect.append(el("option", { value: "", textContent: "Merge into…" }));
  for (const other of allSessions) {
    if (other.session.sessionId === sessionId) continue;
    mergeSelect.append(
      el("option", {
        value: other.session.sessionId,
        textContent: `${fmtDate(other.session.startedAt)} · ${other.photos.length} photos`,
      }),
    );
  }
  mergeSelect.onchange = guard(async () => {
    if (!mergeSelect.value) return;
    const targetSessionId = mergeSelect.value;
    mergeSelect.value = "";
    if (!confirm("Move every photo from this session into the other one?")) return;
    await post("/sessions/merge", { sourceSessionId: sessionId, targetSessionId });
    toast("Sessions merged");
    render();
  });

  const rejectAll = el("button", {
    className: "btn btn-danger",
    textContent: "Delete session",
  });
  rejectAll.onclick = guard(async () => {
    if (
      !confirm(
        `Permanently delete all ${photos.length} photos in this session?\n\n` +
          "Files are removed from S3 and cannot be recovered.",
      )
    )
      return;
    await post(`/sessions/${sessionId}/reject`);
    toast(`Deleted ${photos.length} photos`);
    render();
  });

  return el("div", { className: "card" }, [
    el("div", { className: "card-head" }, [
      el("div", {}, [
        el("div", { className: "card-title", textContent: started }),
        el("div", {
          className: "meta mono",
          textContent: `${sessionId} · ${photos.length} photos${
            session.explicit ? " · explicit session" : ""
          }`,
        }),
      ]),
      el("div", { className: "actions" }, [
        catSelect,
        newCat,
        mergeSelect,
        rejectAll,
      ]),
    ]),
    el("div", { className: "grid" }, photos.map((p) => thumb(p))),
  ]);
}

function thumb(photo) {
  const img = el("img", { src: photo.thumbUrl, alt: "", loading: "lazy" });
  const node = el("div", { className: "thumb" }, [img]);

  if (photo.nearDuplicateOf) {
    node.append(el("span", { className: "flag", textContent: "near-dup" }));
  }
  if (photo.status === "duplicate") {
    node.append(el("span", { className: "flag", textContent: "duplicate" }));
  }

  const kill = el("button", { className: "kill", textContent: "✕", title: "Delete photo" });
  kill.onclick = guard(async (event) => {
    event.stopPropagation();
    if (!confirm("Permanently delete this photo from S3?")) return;
    await post(`/photos/${photo.photoId}/reject`);
    toast("Photo deleted");
    render();
  });
  node.append(kill);

  node.onclick = () => openLightbox(photo);
  return node;
}

// --------------------------------------------------------------------------
// Cats
// --------------------------------------------------------------------------

async function renderCats() {
  await refreshCats();
  const main = $("#main");

  const create = el("button", { className: "btn btn-primary", textContent: "+ New cat" });
  create.onclick = guard(async () => {
    const name = prompt("Name for this cat:");
    if (!name?.trim()) return;
    await post("/cats", { name: name.trim() });
    toast("Cat created");
    render();
  });

  const head = el("div", { className: "section-head" }, [
    el("h2", { textContent: "Cats" }),
    el("span", { textContent: `${state.cats.length} known` }),
    el("div", { className: "actions" }, [create]),
  ]);

  if (!state.cats.length) {
    main.replaceChildren(
      head,
      el("div", { className: "empty" }, [
        el("span", { className: "empty-mark", textContent: "🐾" }),
        el("div", { textContent: "No cats yet. Label a session to create one." }),
      ]),
    );
    return;
  }

  main.replaceChildren(
    head,
    el(
      "div",
      { className: "cat-grid" },
      state.cats.map((cat) => {
        const card = el("div", { className: "cat-card" }, [
          el("h3", { textContent: cat.name }),
          el("div", {
            className: "meta",
            textContent: `${cat.photoCount || 0} photos`,
          }),
        ]);
        card.onclick = guard(() => openCat(cat.catId));
        return card;
      }),
    ),
  );
}

async function openCat(catId) {
  const { cat, photos } = await api(`/cats/${catId}`);

  const rename = el("button", { className: "btn", textContent: "Rename" });
  rename.onclick = guard(async () => {
    const name = prompt("New name:", cat.name);
    if (!name?.trim() || name === cat.name) return;
    await api(`/cats/${catId}`, {
      method: "PATCH",
      body: JSON.stringify({ name: name.trim() }),
    });
    toast("Renamed");
    openCat(catId);
  });

  const remove = el("button", { className: "btn btn-danger", textContent: "Delete cat" });
  remove.onclick = guard(async () => {
    if (!confirm(`Delete “${cat.name}”? Its photos must be unassigned first.`)) return;
    await api(`/cats/${catId}`, { method: "DELETE" });
    toast("Cat deleted");
    setView("cats");
  });

  const back = el("button", { className: "btn btn-ghost", textContent: "← All cats" });
  back.onclick = () => setView("cats");

  $("#main").replaceChildren(
    el("div", { className: "section-head" }, [
      back,
      el("h2", { textContent: cat.name }),
      el("span", { textContent: `${photos.length} photos` }),
      el("div", { className: "actions" }, [rename, remove]),
    ]),
    el("div", { className: "card" }, [
      el("div", { className: "grid" }, photos.map((p) => thumb(p))),
    ]),
  );
}

// --------------------------------------------------------------------------
// Admins
// --------------------------------------------------------------------------

async function renderAdmins() {
  const { admins } = await api("/admins");

  const input = el("input", {
    type: "text",
    placeholder: "google account email",
    size: 32,
  });
  const add = el("button", { className: "btn btn-primary", textContent: "Add admin" });
  add.onclick = guard(async () => {
    if (!input.value.trim()) return;
    await post("/admins", { email: input.value.trim() });
    toast(`${input.value.trim()} can now sign in`);
    input.value = "";
    render();
  });

  $("#main").replaceChildren(
    el("div", { className: "section-head" }, [
      el("h2", { textContent: "Admins" }),
      el("span", {
        textContent: "only these accounts can sign in with Google",
      }),
      el("div", { className: "actions" }, [input, add]),
    ]),
    el(
      "div",
      { className: "card" },
      admins.map((admin) => {
        const remove = el("button", {
          className: "btn btn-danger",
          textContent: "Remove",
          disabled: admin.email === state.email,
        });
        remove.onclick = guard(async () => {
          if (!confirm(`Remove ${admin.email}?`)) return;
          await api(`/admins/${encodeURIComponent(admin.email)}`, { method: "DELETE" });
          toast("Admin removed");
          render();
        });
        return el("div", { className: "row" }, [
          el("span", { textContent: admin.email }),
          el("span", {
            className: "pill",
            textContent: admin.addedAt === "bootstrap" ? "bootstrap" : "added",
          }),
          el("div", { className: "actions" }, [remove]),
        ]);
      }),
    ),
  );
}

// --------------------------------------------------------------------------
// Lightbox
// --------------------------------------------------------------------------

let lightboxPhoto = null;

function openLightbox(photo) {
  lightboxPhoto = photo;
  $("#lightbox-img").src = photo.mediumUrl;
  $("#lightbox-caption").textContent = [
    photo.photoId,
    `${photo.width}×${photo.height}`,
    photo.capturedAt ? fmtDate(photo.capturedAt) : null,
    photo.catId ? `cat ${photo.catId}` : photo.status,
  ]
    .filter(Boolean)
    .join("  ·  ");
  $("#lightbox").hidden = false;
}

function closeLightbox() {
  $("#lightbox").hidden = true;
  $("#lightbox-img").src = "";
  lightboxPhoto = null;
}

// --------------------------------------------------------------------------
// Boot
// --------------------------------------------------------------------------

function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function claims(token) {
  try {
    return JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return {};
  }
}

async function boot() {
  config = await (await fetch("/config.json")).json();

  $("#login-button").onclick = guard(login);
  $("#logout").onclick = () => logout();
  $(".lightbox-close").onclick = closeLightbox;
  $("#lightbox").onclick = (event) => {
    if (event.target.id === "lightbox") closeLightbox();
  };
  $("#lightbox-reject").onclick = guard(async () => {
    if (!lightboxPhoto) return;
    if (!confirm("Permanently delete this photo from S3?")) return;
    await post(`/photos/${lightboxPhoto.photoId}/reject`);
    closeLightbox();
    toast("Photo deleted");
    render();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeLightbox();
  });
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
  $("#who-email").textContent = state.email;
  $("#login").hidden = true;
  $("#app").hidden = false;
  setView("queue");
}

boot().catch((err) => {
  showLogin();
  toast(err.message, true);
});
