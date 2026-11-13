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
import { cats as loadCats, places as loadPlaces } from "./data.js";
import { t } from "./i18n.js";
import { glass } from "./motion.js";
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

// Where the phone is, once, when the flow opens: the encounter's location
// (rounded on the server to about 100 m), never the phone's word for an area.
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
  const fix = await locate();
  if (get().scan?.sessionId === scan.sessionId) update({ fix });
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

const catName = (catId) => (get().cats || []).find((c) => c.catId === catId)?.name || t("cat.noName");

// ------------------------------------------------------------------ pages

function Camera({ scan }) {
  const video = useRef(null);
  const file = useRef(null);
  const [live, setLive] = useState(false);
  useEffect(() => {
    let stream = null;
    let gone = false;
    navigator.mediaDevices
      ?.getUserMedia({ video: { facingMode: "environment", width: { ideal: 2048 } }, audio: false })
      .then((s) => {
        if (gone) return s.getTracks().forEach((track) => track.stop());
        stream = s;
        video.current.srcObject = s;
        setLive(true);
      })
      .catch(() => setLive(false));
    return () => {
      gone = true;
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, []);

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
    ${!live && html`<p class="camera-note">${t("scan.noCamera")}</p>`}
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

function CatTile({ cat, big, onPick }) {
  return html`<button type="button" class=${big ? "cat-tile big" : "cat-tile"} onClick=${() => onPick(cat)} aria-label=${cat.name || t("cat.noName")}>
    ${cat.cover ? html`<img src=${cat.cover.thumb} alt="" />` : html`<span class="cat-tile-empty" aria-hidden="true"></span>`}
    ${!big && html`<span class="cat-tile-name">${cat.name || t("cat.noName")}</span>`}
  </button>`;
}

function Which({ scan, cats }) {
  const ranked = (scan.ranked || []).map((r) => cats.find((c) => c.catId === r.catId)).filter(Boolean);
  const top = ranked.slice(0, SHOWN);
  const rest = [...ranked.slice(SHOWN), ...cats.filter((c) => !ranked.includes(c))];
  const pick = (cat) => update({ catId: cat.catId, isNew: false, step: "met" });
  return html`<div class="scan-page" data-step="which">
    <h1 class="title">${t("scan.which")}</h1>
    ${scan.shots[0]?.thumb && html`<img class="your-photo" src=${scan.shots[0].thumb} alt=${t("scan.yourPhoto")} />`}
    ${top.length > 0 && html`<div class="candidates">${top.map((cat) => html`<${CatTile} cat=${cat} big onPick=${pick} />`)}</div>`}
    <h2 class="subtitle">${top.length ? t("scan.notThese") : t("scan.everyCat")}</h2>
    <div class="cat-grid-pick">
      <button type="button" class="cat-tile new" onClick=${() => update({ isNew: true, catId: null, step: "new" })}>
        <span class="cat-tile-empty plus" aria-hidden="true">+</span>
        <span class="cat-tile-name">${t("scan.newCat")}</span>
      </button>
      ${rest.map((cat) => html`<${CatTile} cat=${cat} onPick=${pick} />`)}
    </div>
    <button type="button" class="link-button" onClick=${() => update({ step: "camera", returnTo: "which" })}>${t("scan.retake")}</button>
  </div>`;
}

function Met({ scan, cats }) {
  const cat = cats.find((c) => c.catId === scan.catId);
  const met = recognition?.encountersOf?.(scan.catId) || 0;
  return html`<div class="scan-page" data-step="met">
    <div class="met-photos">
      ${cat?.cover && html`<img class="met-cat" src=${cat.cover.medium} alt="" />`}
      ${scan.shots[0]?.thumb && html`<img class="met-yours" src=${scan.shots[0].thumb} alt=${t("scan.yourPhoto")} />`}
    </div>
    <h1 class="title">${t("scan.youMet", { name: cat?.name || t("cat.noName") })}</h1>
    ${met > 0 && html`<p class="lead">${t("scan.metBefore", { count: met + 1 })}</p>`}
    <div class="scan-actions">
      <button type="button" class="primary-button" onClick=${() => update({ step: "post" })}>${t("scan.createPost")}</button>
      <button type="button" class="glass-button" onClick=${() => finish({ posting: false })}>${t("scan.saveOnly")}</button>
    </div>
    <button type="button" class="link-button" onClick=${() => update({ step: "which" })}>${t("scan.notThisCat")}</button>
  </div>`;
}

function Chips({ options, chosen, multi, label, labelOf, onChange }) {
  const has = (v) => (multi ? chosen.includes(v) : chosen === v);
  const toggle = (v) => onChange(multi ? (has(v) ? chosen.filter((x) => x !== v) : [...chosen, v]) : has(v) ? null : v);
  return html`<fieldset class="chips">
    <legend>${label}</legend>
    ${options.map(
      (v) => html`<button type="button" class="chip" aria-pressed=${String(has(v))} onClick=${() => toggle(v)}>${labelOf(v)}</button>`,
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
      <span>${t("scan.nameIdea")}</span>
      <input maxlength="24" placeholder=${t("scan.nameIdeaHint")} value=${p.nameIdea} onInput=${(e) => change({ nameIdea: e.currentTarget.value })} />
    </label>
    <${Chips} label=${t("scan.coat")} options=${COATS} chosen=${p.coat} labelOf=${(v) => t(`coat.${v}`)} onChange=${(coat) => change({ coat })} />
    <${Chips}
      label=${t("scan.where")}
      options=${[...places.map((r) => r.id), "elsewhere"]}
      chosen=${p.regionId}
      labelOf=${(v) => (v === "elsewhere" ? t("scan.elsewhere") : places.find((r) => r.id === v)?.names?.en || v)}
      onChange=${(regionId) => change({ regionId })}
    />
    <${Chips} label=${t("scan.traits")} options=${TRAITS} chosen=${p.traits} multi labelOf=${(v) => t(`trait.${v}`)} onChange=${(traits) => change({ traits })} />
    <p class="lead small">${t("scan.newCatNote")}</p>
    <div class="scan-actions">
      <button type="button" class="primary-button" onClick=${() => update({ step: "post" })}>${t("scan.addAndPost")}</button>
      <button type="button" class="glass-button" onClick=${() => finish({ posting: false })}>${t("scan.addOnly")}</button>
    </div>
  </div>`;
}

function Shots({ scan }) {
  return html`<div class="shots">
    ${scan.shots.map(
      (s, i) => html`<span class="shot">${s.thumb ? html`<img src=${s.thumb} alt=${t("scan.photoN", { n: i + 1 })} />` : null}<b>${i + 1}</b></span>`,
    )}
    ${scan.shots.length < MAX_PHOTOS &&
    html`<button type="button" class="shot add" aria-label=${scan.shots.length ? t("scan.another") : t("scan.takePhoto")} onClick=${() => update({ step: "camera", returnTo: scan.step })}>
      <${Icon} name="camera" size=${22} />
      <span>${scan.shots.length ? t("scan.another") : t("scan.takePhoto")}</span>
    </button>`}
  </div>`;
}

function PostPage({ scan, cats }) {
  const cat = cats.find((c) => c.catId === scan.catId);
  const tag = scan.isNew
    ? html`${scan.proposal.nameIdea || t("scan.newCat")} <span class="badge">${t("scan.newBadge")}</span>`
    : cat
      ? cat.name || t("cat.noName")
      : t("scan.noTag");
  return html`<div class="scan-page" data-step="post">
    <h1 class="title">${t("scan.newPost")}</h1>
    <div class="row tag-row">
      <span class="row-label">${tag}</span>
      <span class="row-value"></span>
      <button type="button" class="link-button" onClick=${() => update({ step: "which" })}>${scan.catId || scan.isNew ? t("scan.change") : t("scan.tag")}</button>
    </div>
    <${Shots} scan=${scan} />
    <label class="field">
      <span>${t("scan.description")}</span>
      <textarea maxlength="280" rows="3" placeholder=${t("scan.descriptionHint")} value=${scan.text} onInput=${(e) => update({ text: e.currentTarget.value })}></textarea>
    </label>
    <button type="button" role="switch" class="row switch-row" aria-checked=${String(scan.shareRegion)} onClick=${() => update({ shareRegion: !scan.shareRegion })}>
      <span class="row-label">${t("scan.location")}</span>
      <span class="row-value">${scan.shareRegion ? t("scan.locationOn") : t("scan.locationOff")}</span>
      <span class="switch" aria-hidden="true"><span></span></span>
    </button>
    <div class="scan-actions">
      <button type="button" class="primary-button" disabled=${!scan.shots.length} onClick=${() => finish({ posting: true })}>${t("scan.post")}</button>
      ${scan.shots.length > 0 && html`<button type="button" class="glass-button" onClick=${() => finish({ posting: false })}>${t("scan.saveOnly")}</button>`}
    </div>
  </div>`;
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
  const Page = { camera: Camera, which: Which, met: Met, new: NewCat, post: PostPage }[scan.step] || Which;
  return html`<section class="scan" role="dialog" aria-label=${t("scan.label")} data-step=${scan.step}>
    ${scan.step !== "camera" &&
    html`<header class="page-top scan-top">
      <button type="button" class="glass-icon" ref=${glass} aria-label=${t("ui.close")} onClick=${() => close()}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
      </button>
    </header>`}
    <div class="scroller" key=${scan.step}><${Page} scan=${scan} cats=${cats} places=${places} /></div>
  </section>`;
}
