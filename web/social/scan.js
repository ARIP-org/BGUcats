// The capture flow (E3; docs/app-plan/01-product.md, "Scan a cat" and "After
// the photo"): the camera, then four pages that slide sideways: which cat,
// "You met X" or the new-cat form, and the post. Every ending is written
// through the outbox, so a dead spot on campus or a closed app loses
// nothing: the encounter and its photos exactly as today's Capture sends
// them (web/outbox.js), the pick, and after the photos the proposal and the
// post (`setAfter`). What each ending writes is 01-product.md's table.
//
// The flow's state is kept on the phone (localStorage), so a reload lands
// back on the page it was on. The photos' bytes live in the outbox until
// they are uploaded, and in memory for the previews and the model.

import { api, post } from "../lib/api.js";
import { getConfig } from "../lib/auth.js";
import { isNative } from "../install.js";
import { createOutbox, ulid } from "../outbox.js";
import { createRecognition } from "../recognition.js";
import { html, useEffect, useRef, useState } from "../vendor/preact-htm.js";
import { askAgain, asking, painted, quiet } from "./asking.js";
import { cats as loadCats, names as loadNames, places as loadPlaces } from "./data.js";
import { t, tRich } from "./i18n.js";
import { glass } from "./motion.js";
import { NamePoll } from "./poll.js";
import { get, set, useStore } from "./store.js";
import { termsFirst } from "./terms.js";
import { Icon, toast } from "./ui.js";

const KEY = "bgucats.scan";
const MAX_PHOTOS = 4;
const SHOWN = 3; // candidates on "Which cat?"
const COATS = ["ginger", "black", "white", "gray", "tabby", "calico", "tuxedo"];
const TRAITS = ["friendly", "shy", "ear-tipped", "kitten", "collar"];
const NO_MODEL = "none"; // the pick's modelVersion when no model ranked

const blobs = new Map(); // photoId -> Blob, this visit only
let outbox = null;
let recognition = null;

export function startOutbox() {
  outbox ??= createOutbox({ post, onChange: () => set({ outboxTick: Date.now() }) });
  // In the iPhone app the model comes from the site, another origin there
  // (N1; CORS on /model/ in infra/main/web.tf).
  recognition ??= createRecognition({ api, post, base: isNative() ? getConfig().apiBase || "" : "" });
  outbox.kick();
  const saved = load();
  if (saved) set({ scan: saved });
  return outbox;
}

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY));
  } catch {
    return null;
  }
}

function save(scan) {
  try {
    if (scan) localStorage.setItem(KEY, JSON.stringify(scan));
    else localStorage.removeItem(KEY);
  } catch {
    /* the flow goes on; only a reload would lose the page */
  }
}

function update(patch) {
  const scan = { ...get().scan, ...patch };
  save(scan);
  set({ scan });
}

// Where the phone is, once per flow: the encounter's location (rounded on
// the server to about 100 m), never the phone's word for an area.
function locate() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude, accuracyM: p.coords.accuracy }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 },
    );
  });
}

// Asked once the flow's screen is drawn, and after the camera has answered,
// so the phone puts one question at a time and never inside the tap that
// opened the flow (asking.js: that tap froze an iPhone). Not asked at all
// if the app was last closed with this question unanswered, until the
// person turns "Add location" on themselves (`again`).
let located = null; // the flow whose place has been asked for
function findPlace({ again = false } = {}) {
  const scan = get().scan;
  if (!scan || scan.fix) return;
  if (again) askAgain("location");
  else if (located === scan.sessionId || quiet("location")) return;
  located = scan.sessionId;
  asking("location", locate).then((fix) => {
    if (fix && get().scan?.sessionId === scan.sessionId) update({ fix });
  });
}

// entry: "scan" (the centre tab) or "post" (the feed's +).
export async function openScan(entry) {
  if (get().scan) {
    set({ scanOpen: true });
    return;
  }
  const scan = {
    sessionId: ulid(),
    entry,
    step: entry === "scan" ? "camera" : "post",
    shots: [],
    catId: null,
    isNew: false,
    proposal: { nameIdea: "", coat: null, regionId: null, traits: [] },
    text: "",
    shareRegion: true,
    ranked: null,
    modelVersion: NO_MODEL,
    fix: null,
  };
  save(scan);
  set({ scan, scanOpen: true });
  await painted();
  // The camera page asks for the camera first and for the place after it
  // (Camera, below); a post started with "+" has no camera yet.
  if (scan.step !== "camera") findPlace();
  recognition?.prepareForCapture().catch(() => {});
}

async function keep(blob) {
  const scan = get().scan;
  if (!scan || scan.shots.length >= MAX_PHOTOS) return;
  const photoId = ulid();
  blobs.set(photoId, blob);
  if (!scan.shots.length) {
    await outbox.addEncounter({
      sessionId: scan.sessionId,
      open: true,
      lat: scan.fix?.lat,
      lon: scan.fix?.lon,
      accuracyM: scan.fix?.accuracyM,
    });
  }
  await outbox.addItem({
    photoId,
    sessionId: scan.sessionId,
    blob,
    contentType: blob.type || "image/jpeg",
    capturedAt: new Date().toISOString(),
    lat: scan.fix?.lat,
    lon: scan.fix?.lon,
    accuracyM: scan.fix?.accuracyM,
  });
  const shots = [...scan.shots, { photoId, thumb: await thumbOf(blob) }];
  // One press, one photo, and on: from the camera to "Which cat?", or back
  // to the page that asked for another photo.
  const next = scan.returnTo || (scan.entry === "scan" ? "which" : "post");
  update({ shots, step: next, returnTo: null });
  guess(shots);
}

async function guess(shots) {
  if (!recognition) return;
  try {
    if (!(await recognition.prepareForCapture())) return;
    const result = await recognition.guessShots(
      shots.filter((s) => blobs.has(s.photoId)).map((s) => ({ photoId: s.photoId, blob: blobs.get(s.photoId) })),
    );
    if (result?.ranked?.length) update({ ranked: result.ranked, modelVersion: recognition.state.version || NO_MODEL });
  } catch {
    /* no guess: the grid of every cat is the answer */
  }
}

async function thumbOf(blob) {
  try {
    const bitmap = await createImageBitmap(blob);
    const side = 240;
    const scale = side / Math.max(bitmap.width, bitmap.height);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.7);
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------ endings

// What one ending writes (01-product.md, "What each ending writes"). The
// encounter and its photos are already in the outbox.
export function endingWrites(scan, { posting }) {
  const shown = (scan.ranked || []).slice(0, SHOWN).map((r) => r.catId);
  const pickOf = (choice, catId) => ({
    modelVersion: scan.modelVersion || NO_MODEL,
    choice,
    catId,
    shown: shown.length ? shown : [catId || scan.catId].filter(Boolean).slice(0, 1),
    ranked: (scan.ranked || []).map((r) => ({ catId: r.catId, score: r.score })),
    photoCount: Math.max(1, scan.shots.length),
  });
  const writes = { pick: null, after: [] };
  let claim = null;
  if (scan.isNew) {
    const proposalId = scan.proposalId || ulid();
    scan.proposalId = proposalId;
    writes.pick = pickOf("new", null);
    if (!writes.pick.shown.length) writes.pick = null; // nothing was shown: no pick to score
    writes.after.push({
      key: "proposal",
      path: "/v1/proposals",
      body: { proposalId, sessionId: scan.sessionId, ...scan.proposal },
    });
    claim = { proposalId };
  } else if (scan.catId) {
    writes.pick = pickOf("cat", scan.catId);
    claim = { catId: scan.catId };
  }
  if (posting) {
    writes.after.push({
      key: "post",
      path: "/v1/posts",
      body: {
        postId: scan.postId || ulid(),
        sessionId: scan.sessionId,
        photoIds: scan.shots.map((s) => s.photoId),
        claim,
        text: scan.text.trim() || undefined,
        shareRegion: !!scan.shareRegion,
      },
    });
  }
  return writes;
}

async function finish({ posting }) {
  const scan = { ...get().scan };
  if (!scan.shots.length) return close();
  const writes = endingWrites(scan, { posting });
  if (writes.after.length && !(await termsFirst())) return;
  await outbox.finishEncounter(scan.sessionId, writes);

  const posted = writes.after.find((w) => w.key === "post");
  if (posted) {
    // Shown at once in the author's feed, marked as sending (05-client.md).
    const me = get().me;
    const cat = scan.catId ? (get().cats || []).find((c) => c.catId === scan.catId) : null;
    set({
      sending: [
        {
          postId: posted.body.postId,
          author: { userId: me?.userId, username: me?.username, displayName: me?.displayName, avatar: me?.avatar },
          cat: cat ? { catId: cat.catId, name: cat.name } : null,
          photos: scan.shots.map((s) => ({ photoId: s.photoId, medium: s.thumb, thumb: s.thumb })),
          text: posted.body.text || "",
          likes: 0,
          liked: false,
          createdAt: new Date().toISOString(),
          mine: true,
          state: "sending",
          proposal: scan.isNew ? { status: "open", nameIdea: scan.proposal.nameIdea } : undefined,
        },
        ...(get().sending || []),
      ],
    });
  }
  toast(
    scan.isNew
      ? t("scan.doneNew")
      : posted
        ? t("scan.donePost")
        : scan.catId
          ? t("scan.doneSaved", { name: catName(scan.catId) })
          : t("scan.doneSaved", { name: t("scan.theEncounter") }),
  );
  for (const shot of scan.shots) blobs.delete(shot.photoId);
  save(null);
  set({ scan: null, scanOpen: false, tab: "feed", stack: [] });
}

async function close() {
  const scan = get().scan;
  if (scan?.shots.length) {
    // Photos already taken stay with the cats' records; only the post and
    // the answer are left out.
    await outbox.closeEncounter(scan.sessionId);
  }
  save(null);
  set({ scan: null, scanOpen: false });
}

// How far a post made on this phone has got (feed.js, the sending card):
// `done` is the part of its photos that have arrived, `sent` whether the
// post itself has gone, `error` the outbox's reason if the last try failed.
export async function sendingState(card) {
  if (!outbox) return { done: 0, sent: false, error: null };
  const { items, encounters, lastError } = await outbox.snapshot();
  const mine = items.filter((item) => card.photos.some((p) => p.photoId === item.photoId));
  const part = mine.reduce((sum, item) => sum + (1 - (item.progress ?? 0)), 0);
  const count = Math.max(1, card.photos.length);
  const waiting = encounters.some((e) => (e.after || []).some((w) => w.body?.postId === card.postId));
  return {
    done: Math.max(0, Math.min(1, 1 - part / count)),
    sent: !waiting && !mine.length,
    error: mine.find((item) => item.error)?.error || lastError || null,
  };
}

const catName = (catId) => (get().cats || []).find((c) => c.catId === catId)?.name || t("cat.noName");

// ------------------------------------------------------------------ pages

function Camera({ scan }) {
  const video = useRef(null);
  const file = useRef(null);
  const [live, setLive] = useState(false);
  // Off by itself if the app was last closed while the phone was being
  // asked for the camera (asking.js); the phone's own camera still works.
  const [held, setHeld] = useState(() => quiet("camera"));
  useEffect(() => {
    if (held || !navigator.mediaDevices?.getUserMedia) {
      findPlace();
      return undefined;
    }
    let stream = null;
    let gone = false;
    asking("camera", () =>
      navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 2048 } }, audio: false }),
    )
      .then((s) => {
        if (gone) return s.getTracks().forEach((track) => track.stop());
        stream = s;
        video.current.srcObject = s;
        setLive(true);
      })
      .catch(() => setLive(false))
      .then(() => findPlace()); // one question at a time: the place after the camera
    return () => {
      gone = true;
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, [held]);
  const tryLive = () => {
    askAgain("camera");
    setHeld(false);
  };

  async function shoot() {
    const v = video.current;
    if (!live || !v.videoWidth) return file.current.click();
    const scale = Math.min(1, 2048 / Math.max(v.videoWidth, v.videoHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(v.videoWidth * scale);
    canvas.height = Math.round(v.videoHeight * scale);
    canvas.getContext("2d").drawImage(v, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
    if (blob) keep(blob);
  }

  return html`<div class="camera" data-step="camera">
    <video ref=${video} autoplay playsinline muted aria-hidden="true"></video>
    ${!live && !held && html`<p class="camera-note">${t("scan.noCamera")}</p>`}
    ${held &&
    html`<p class="camera-note">
      ${t("scan.cameraHeld")}
      <button type="button" class="link-button" onClick=${tryLive}>${t("scan.cameraTry")}</button>
    </p>`}
    <span class="bracket tl" aria-hidden="true"></span><span class="bracket tr" aria-hidden="true"></span>
    <span class="bracket bl" aria-hidden="true"></span><span class="bracket br" aria-hidden="true"></span>
    <div class="camera-bar">
      <button type="button" class="glass-icon" ref=${glass} aria-label=${t("ui.close")} onClick=${scan.returnTo ? () => update({ step: scan.returnTo, returnTo: null }) : close}>
        <${Icon} name="back" size=${22} />
      </button>
      <button type="button" class="shutter" ref=${glass} aria-label=${t("scan.shutter")} onClick=${shoot}>
        <svg width="34" height="34" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <ellipse cx="12" cy="16" rx="4.6" ry="3.8" /><circle cx="6" cy="10.5" r="2" /><circle cx="9.6" cy="6.8" r="2" /><circle cx="14.4" cy="6.8" r="2" /><circle cx="18" cy="10.5" r="2" />
        </svg>
      </button>
      <label class="glass-icon file-shot" aria-label=${t("scan.phoneCamera")}>
        <${Icon} name="camera" size=${22} />
        <input ref=${file} type="file" accept="image/*" capture="environment" onChange=${(e) => e.currentTarget.files[0] && keep(e.currentTarget.files[0])} />
      </label>
    </div>
  </div>`;
}

// A cat to choose, as its photo: the prototype's tiles carry no words. A
// cat with no photo yet shows its name, or there would be nothing to know
// it by. The big ones are the model's closest matches.
function CatTile({ cat, big, onPick }) {
  const name = cat.name || t("cat.noName");
  return html`<button type="button" class=${big ? "cat-tile big" : "cat-tile"} data-cat=${cat.catId} onClick=${() => onPick(cat)} aria-label=${name}>
    ${cat.cover
      ? html`<img src=${big ? cat.cover.medium : cat.cover.thumb} alt="" loading="lazy" />`
      : html`<span class="cat-tile-empty"><span class="cat-tile-name">${name}</span></span>`}
  </button>`;
}

function Which({ scan, cats }) {
  const ranked = (scan.ranked || []).map((r) => cats.find((c) => c.catId === r.catId)).filter(Boolean);
  const top = ranked.slice(0, SHOWN);
  const rest = [...ranked.slice(SHOWN), ...cats.filter((c) => !ranked.includes(c))];
  // Tagging a post goes back to the post; a scan goes on to "You met".
  const pick = (cat) => update({ catId: cat.catId, isNew: false, step: tagging(scan) ? "post" : "met", changing: false });
  // The photo just taken and "retake" are in the bar at the top (Scan).
  return html`<div class="scan-page" data-step="which">
    <h1 class="title">${t("scan.which")}</h1>
    ${top.length > 0 &&
    html`<div class="candidates" role="group" aria-label=${t("scan.closest")}>
      ${top.map((cat) => html`<${CatTile} key=${cat.catId} cat=${cat} big onPick=${pick} />`)}
    </div>`}
    <h2 class="subtitle">${top.length ? t("scan.notThese") : t("scan.everyCat")}</h2>
    <div class="cat-grid-pick">
      <button type="button" class="cat-tile new" onClick=${() => update({ isNew: true, catId: null, step: "new" })}>
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
        <span class="cat-tile-name">${t("scan.newCat")}</span>
      </button>
      ${rest.map((cat) => html`<${CatTile} key=${cat.catId} cat=${cat} onPick=${pick} />`)}
    </div>
  </div>`;
}

// The flow's two ways on, side by side at the foot of the page, the
// prototype's: the quiet one saves, the accent one goes to the post.
function TwoWays({ save, saveLabel, post, postLabel }) {
  return html`<div class="scan-bar" role="group" aria-label=${t("scan.postOrSave")}>
    <button type="button" class="scan-way" onClick=${save}>${saveLabel}</button>
    <button type="button" class="scan-way main" onClick=${post}><${Icon} name="pencil" size=${19} />${postLabel}</button>
  </div>`;
}

const toPost = () => update({ step: "post", changing: false });

function Met({ scan, cats, places }) {
  const cat = cats.find((c) => c.catId === scan.catId);
  const met = recognition?.encountersOf?.(scan.catId) || 0;
  // The cat's name poll, the prototype's "Name" card. With no signal the
  // page is whole without it.
  const [poll, setPoll] = useState(null);
  useEffect(() => {
    let live = true;
    setPoll(null);
    loadNames(scan.catId)
      .then((answer) => live && setPoll(answer))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [scan.catId]);
  const place = places.find((r) => r.id === cat?.regionId)?.names?.en;
  return html`<div class="scan-page" data-step="met">
    <div class="met-photos">
      <span class="met-cat">${cat?.cover && html`<img src=${cat.cover.medium} alt="" />`}</span>
      ${scan.shots[0]?.thumb && html`<span class="met-yours"><img src=${scan.shots[0].thumb} alt=${t("scan.yourPhoto")} /></span>`}
    </div>
    <div class="met-words">
      <h1 class="title">${t("scan.youMet", { name: cat?.name || t("cat.noName") })}</h1>
      ${place && html`<p class="met-sub">${t("cat.usuallyNear", { place })}</p>`}
      ${met > 0 && html`<p class="met-sub">${t("scan.metBefore", { count: met + 1 })}</p>`}
    </div>
    ${poll && html`<${NamePoll} poll=${poll} change=${setPoll} />`}
    <${TwoWays} save=${() => finish({ posting: false })} saveLabel=${t("scan.justSave")} post=${toPost} postLabel=${t("scan.createPost")} />
  </div>`;
}

// `swatch`: a dot of colour before each word (the coats, tokens.css).
function Chips({ options, chosen, multi, label, labelOf, swatch, onChange }) {
  const has = (v) => (multi ? chosen.includes(v) : chosen === v);
  const toggle = (v) => onChange(multi ? (has(v) ? chosen.filter((x) => x !== v) : [...chosen, v]) : has(v) ? null : v);
  return html`<fieldset class="chips">
    <legend>${label}</legend>
    ${options.map(
      (v) => html`<button type="button" class=${swatch ? "chip with-swatch" : "chip"} aria-pressed=${String(has(v))} onClick=${() => toggle(v)}>
        ${swatch && html`<span class="chip-swatch" aria-hidden="true" style=${{ background: `var(--${swatch}-${v})` }}></span>`}${labelOf(v)}
      </button>`,
    )}
  </fieldset>`;
}

function NewCat({ scan, places }) {
  const p = scan.proposal;
  const change = (patch) => update({ proposal: { ...p, ...patch } });
  return html`<div class="scan-page" data-step="new">
    <h1 class="title">${t("scan.newCatTitle")}</h1>
    <${Shots} scan=${scan} />
    <label class="field">
      <span>${t("scan.nameIdea")} <span class="optional">${t("scan.optional")}</span></span>
      <input maxlength="24" autocomplete="off" autocapitalize="words" enterkeyhint="done" placeholder=${t("scan.nameIdeaHint")} value=${p.nameIdea} onInput=${(e) => change({ nameIdea: e.currentTarget.value })} />
    </label>
    <${Chips} label=${t("scan.coat")} options=${COATS} chosen=${p.coat} swatch="coat" labelOf=${(v) => t(`coat.${v}`)} onChange=${(coat) => change({ coat })} />
    <${Chips}
      label=${t("scan.where")}
      options=${[...places.map((r) => r.id), "elsewhere"]}
      chosen=${p.regionId}
      labelOf=${(v) => (v === "elsewhere" ? t("scan.elsewhere") : places.find((r) => r.id === v)?.names?.en || v)}
      onChange=${(regionId) => change({ regionId })}
    />
    <${Chips} label=${t("scan.traits")} options=${TRAITS} chosen=${p.traits} multi labelOf=${(v) => t(`trait.${v}`)} onChange=${(traits) => change({ traits })} />
    <p class="lead small">${t("scan.newCatNote")}</p>
    <${TwoWays} save=${() => finish({ posting: false })} saveLabel=${t("scan.addOnly")} post=${toPost} postLabel=${t("scan.addAndPost")} />
  </div>`;
}

// The encounter's photos and the way to add one. `big`: the post page's,
// one photo nearly the screen's width, numbered "1/2".
function Shots({ scan, big }) {
  const count = scan.shots.length;
  const add = () => update({ step: "camera", returnTo: scan.step });
  if (big && !count) {
    return html`<button type="button" class="first-shot" onClick=${add}>
      <span class="first-shot-icon" aria-hidden="true"><${Icon} name="camera" size=${32} width=${1.9} /></span>
      <span>${t("scan.takePhoto")}</span>
    </button>`;
  }
  return html`<div class=${big ? "shots big" : "shots"} role="group" aria-label=${t("scan.photos")}>
    ${scan.shots.map(
      (s, i) =>
        html`<span class="shot" key=${s.photoId}
          >${s.thumb ? html`<img src=${s.thumb} alt=${t("scan.photoN", { n: i + 1 })} />` : null}<b>${big ? `${i + 1}/${count}` : i + 1}</b></span
        >`,
    )}
    ${count < MAX_PHOTOS &&
    html`<button type="button" class="shot add" onClick=${add}>
      <span class="shot-add-icon" aria-hidden="true"><${Icon} name="camera" size=${22} /></span>
      <span class="shot-add-label">${count ? t("scan.addPhoto") : t("scan.takePhoto")}</span>
      <span class="shot-add-count">${t("scan.photosOf", { count, max: MAX_PHOTOS })}</span>
    </button>`}
  </div>`;
}

const PAW = html`<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
  <ellipse cx="12" cy="16" rx="4.6" ry="3.8" /><circle cx="6" cy="10.5" r="2" /><circle cx="9.6" cy="6.8" r="2" /><circle cx="14.4" cy="6.8" r="2" /><circle cx="18" cy="10.5" r="2" />
</svg>`;
const CROSS = html`<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>`;
const PIN = html`<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z" /><circle cx="12" cy="10" r="2.4" />
</svg>`;

// The campus place a point is in: the nearest whose circle holds it, from
// the point rounded as the server keeps it (common/regions.py does the
// same for the post). Only for the words under "Add location".
export function placeAt(fix, places) {
  if (!fix) return null;
  const rad = Math.PI / 180;
  const lat = Math.round(fix.lat * 1000) / 1000;
  const lon = Math.round(fix.lon * 1000) / 1000;
  let best = null;
  for (const r of places) {
    const x = (r.lon - lon) * rad * Math.cos(((r.lat + lat) / 2) * rad);
    const d = 6371000 * Math.hypot(x, (r.lat - lat) * rad);
    if (d <= r.radiusM && (!best || d < best.d)) best = { d, r };
  }
  return best ? best.r : null;
}

// The prototype's small map under the switch: a drawing, not the place
// itself, with the area's name on it.
function NearMap({ place }) {
  return html`<div class="near-map">
    <svg viewBox="0 0 346 128" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <rect class="nm-ground" x="-10" y="-10" width="370" height="150" />
      <rect class="nm-green" x="18" y="14" width="96" height="58" rx="14" />
      <rect class="nm-green" x="250" y="70" width="84" height="48" rx="14" />
      <path class="nm-road" d="M-10 92 C 80 80, 150 100, 360 84" stroke-width="12" />
      <path class="nm-road" d="M170 -10 C 160 40, 190 80, 176 140" stroke-width="9" />
      <rect class="nm-building" x="196" y="18" width="70" height="40" rx="8" />
      <rect class="nm-building" x="62" y="98" width="64" height="26" rx="7" />
      <circle class="nm-halo" cx="182" cy="64" r="30" />
      <path class="nm-pin" d="M182 70s-11-9.5-11-18.5a11 11 0 0 1 22 0c0 9-11 18.5-11 18.5z" />
      <circle class="nm-dot" cx="182" cy="51.5" r="4" />
    </svg>
    <span class="near-name">${t("scan.near", { place: place.near?.en || place.names.en })}</span>
  </div>`;
}

function PostPage({ scan, cats, places }) {
  const cat = cats.find((c) => c.catId === scan.catId);
  const tagged = scan.isNew || !!cat;
  const name = scan.isNew ? scan.proposal.nameIdea || t("scan.newCat") : cat?.name || t("cat.noName");
  const face = scan.isNew ? scan.shots[0]?.thumb : cat?.cover?.thumb;
  const near = scan.shareRegion ? placeAt(scan.fix, places) : null;
  // From "+", the cat is chosen on the page of every cat by name; after a
  // scan, on "Which cat?" again.
  const choose = () => update({ step: scan.entry === "post" ? "tag" : "which", changing: true });
  return html`<div class="scan-page" data-step="post">
    ${tagged
      ? html`<div class="tag-row tagged">
          <span class="tagged-face" aria-hidden="true">${face && html`<img src=${face} alt="" />`}</span>
          <span class="tagged-words"
            >${scan.entry === "scan" && !scan.isNew ? tRich("scan.youMet", { name }, "name") : html`<b>${name}</b>`}
            ${scan.isNew && html` <span class="badge">${t("scan.newBadge")}</span>`}</span
          >
          <button type="button" class="tagged-button" onClick=${choose}>${t("scan.change")}</button>
          ${scan.entry === "post" &&
          html`<button type="button" class="tagged-button round" aria-label=${t("scan.untag")} onClick=${() => update({ catId: null, isNew: false })}>${CROSS}</button>`}
        </div>`
      : html`<button type="button" class="tag-row tag-ask" onClick=${choose}>
          <span class="tag-ask-icon" aria-hidden="true">${PAW}</span>
          <span class="tag-ask-words">${t("scan.tag")}</span>
          <span class="optional">${t("scan.optionalWord")}</span>
        </button>`}
    <${Shots} scan=${scan} big />
    <label class="describe">
      <span class="describe-label">${t("scan.description")} <span class="optional">${t("scan.optional")}</span></span>
      <textarea
        maxlength="280"
        rows="3"
        autocapitalize="sentences"
        enterkeyhint="done"
        placeholder=${t("scan.descriptionHint")}
        value=${scan.text}
        onInput=${(e) => update({ text: e.currentTarget.value })}
      ></textarea>
      <span class="describe-count" aria-live="polite">${t("scan.textCount", { count: scan.text.length, max: 280 })}</span>
    </label>
    <section class="locate" aria-label=${t("scan.location")}>
      <button
        type="button"
        role="switch"
        class="locate-row"
        aria-checked=${String(scan.shareRegion)}
        onClick=${() => {
          // Turned on by hand with no place yet: ask the phone now, also if
          // it had stopped asking by itself.
          if (!scan.shareRegion && !scan.fix) findPlace({ again: true });
          update({ shareRegion: !scan.shareRegion });
        }}
      >
        <span class="locate-icon" aria-hidden="true">${PIN}</span>
        <span class="locate-words">
          <span class="locate-title">${t("scan.location")}</span>
          <span class="locate-sub">${scan.shareRegion ? t("scan.locationOn") : t("scan.locationOff")}</span>
        </span>
        <span class="switch" aria-hidden="true"><span></span></span>
      </button>
      <div class="near" data-open=${String(!!near)} aria-hidden=${String(!near)}>${near && html`<${NearMap} place=${near} />`}</div>
    </section>
    ${scan.entry === "scan" &&
    scan.shots.length > 0 &&
    html`<button type="button" class="link-button quiet" onClick=${() => finish({ posting: false })}>${t("scan.saveOnly")}</button>`}
  </div>`;
}

// "+" → "Tag a cat": every cat by name, the prototype's page 4. The one
// already chosen is ringed.
function Tag({ scan, cats }) {
  const pick = (cat) => update({ catId: cat.catId, isNew: false, step: "post", changing: false });
  return html`<div class="scan-page" data-step="tag">
    <h1 class="title">${t("scan.which")}</h1>
    <div class="tag-grid" role="radiogroup" aria-label=${t("scan.campusCats")}>
      ${cats.map(
        (cat) => html`<button type="button" role="radio" class="tag-cat" key=${cat.catId} aria-checked=${String(cat.catId === scan.catId)} onClick=${() => pick(cat)}>
          <span class="tag-cat-photo">${cat.cover && html`<img src=${cat.cover.thumb} alt="" loading="lazy" />`}</span>
          <span class="tag-cat-name">${cat.name || t("cat.noName")}</span>
        </button>`,
      )}
    </div>
  </div>`;
}

// Choosing a cat for a post already being written: from the feed's "+", or
// "Change" on the post page.
const tagging = (scan) => !!scan.changing || scan.entry === "post";

// The page the back button leads to; null on the flow's first page, where
// the button closes the flow instead (the prototype's X).
export function pageBefore(scan) {
  if (scan.step === "which") return tagging(scan) ? "post" : null;
  if (scan.step === "tag") return "post";
  if (scan.step === "met" || scan.step === "new") return "which";
  if (scan.step === "post" && scan.entry !== "post") return scan.isNew ? "new" : scan.catId ? "met" : "which";
  return null;
}

export function Scan() {
  const scan = useStore((s) => s.scan);
  const open = useStore((s) => s.scanOpen);
  const [cats, setCats] = useState([]);
  const [places, setPlaces] = useState([]);
  useEffect(() => {
    if (!open) return;
    loadCats()
      .then((answer) => {
        setCats(answer.cats);
        set({ cats: answer.cats });
      })
      .catch(() => {});
    loadPlaces()
      .then(setPlaces)
      .catch(() => {});
  }, [open]);
  if (!scan || !open) return null;
  const Page = { camera: Camera, which: Which, met: Met, new: NewCat, post: PostPage, tag: Tag }[scan.step] || Which;
  const before = pageBefore(scan);
  return html`<section class="scan" role="dialog" aria-label=${t("scan.label")} data-step=${scan.step}>
    ${scan.step !== "camera" &&
    html`<header class="scan-top">
      ${before
        ? html`<button type="button" class="glass-icon" key="back" ref=${glass} aria-label=${t("ui.back")} onClick=${() => update({ step: before })}>
            <${Icon} name="back" size=${22} />
          </button>`
        : html`<button type="button" class="glass-icon" key="close" ref=${glass} aria-label=${t("ui.close")} onClick=${() => close()}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>`}
      ${scan.step === "which" &&
      html`${scan.shots[0]?.thumb && html`<span class="scan-shot"><img src=${scan.shots[0].thumb} alt=${t("scan.yourPhoto")} /></span>`}
        <button type="button" class="glass-icon" ref=${glass} aria-label=${t("scan.retakePhoto")} onClick=${() => update({ step: "camera", returnTo: "which" })}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M4 8h3l1.6-2.4h6.8L17 8h3v11H4z" /><circle cx="12" cy="13" r="3.4" />
          </svg>
        </button>`}
      ${scan.step === "post" &&
      html`<h1 class="scan-title">${t("scan.newPost")}</h1>
        <button type="button" class="scan-post" ref=${glass} disabled=${!scan.shots.length} onClick=${() => finish({ posting: true })}>${t("scan.post")}</button>`}
    </header>`}
    <div class="scroller" key=${scan.step}><${Page} scan=${scan} cats=${cats} places=${places} /></div>
  </section>`;
}
