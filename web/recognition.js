// The recognition model, running in the admin's browser — and the
// measurement of it on real sessions.
//
// What it does, in the order the labeling desk needs it:
//
//   1. Load MegaDescriptor-T (int8 ONNX, ~30 MB) and ONNX Runtime Web
//      (~10 MB). Published by scripts/publish_model.py under a versioned
//      path; sw.js caches that path, so a device downloads it once.
//   2. Learn the cats: embed every labeled photo once per model version and
//      keep the vectors on this device (IndexedDB). Several templates per
//      cat, never an average — a frontal and a profile view sit far apart,
//      and their mean matches neither (CLAUDE.md, "Templates, not centroids").
//   3. Guess, blind: for each session in the queue, rank every known cat and
//      record the ranking on the server *before* anyone labels it. Nobody
//      sees the guess until they have chosen, so the label stays the
//      person's own and the guess can be scored against it honestly.
//   4. Replay: re-run the same ranking over sessions that are already
//      labeled, each one hidden from the templates in turn — a number on
//      real cats without waiting for new sessions.
//
// It only ranks. There is no "this is Mitzi" and no "new cat" verdict: on
// BGU photos the scores of right guesses, wrong guesses and never-seen cats
// still overlap, so any threshold today would be invented (manifest
// "thresholds": null). Measuring is how one gets earned.
//
// Pixels: centre square of the 1024px derivative, scaled to 224×224, RGB in
// [0, 1]. Normalisation and L2-norm are inside the model (research/catreid/
// export.py), so a dot product here is a cosine similarity.

const MANIFEST_URL = "/model/manifest.json";
const DB_NAME = "bgucats-recognition";
// Frames embedded per session. Evenly spaced, never the first N: a burst's
// first frames are the same instant (research/catreid/datasets.py).
const MAX_QUERY_FRAMES = 8;
// Photos fetched ahead of the one being embedded, so the network and the
// model overlap. Inference itself is one at a time (one wasm thread).
const PREFETCH = 4;
// Statuses that are never matched against: `duplicate` is a byte copy of a
// photo already counted, `pending` never finished processing.
const SKIP_STATUSES = new Set(["duplicate", "pending"]);
const GALLERY_REFRESH_MS = 60 * 1000;

export function createRecognition({ api, post }) {
  const listeners = new Set();
  const state = {
    phase: "idle", // idle | unavailable | loading | learning | guessing | ready | error
    detail: "",
    progress: null,
    version: null,
    error: null,
  };
  let manifest = null;
  let session = null;
  let loading = null;
  let templates = []; // { photoId, sessionId, catId, vector }
  let galleryAt = 0;
  let gallerySync = null;
  const guesses = new Map(); // sessionId -> { ranked, recorded, late }
  let pending = []; // queue sessions still to guess, in order
  let guessing = null;

  function set(patch) {
    Object.assign(state, patch);
    for (const fn of listeners) fn({ ...state });
  }

  // ------------------------------------------------------------------
  // Vectors on this device
  // ------------------------------------------------------------------

  const memory = new Map();
  let dbPromise = null;
  function db() {
    dbPromise ??= new Promise((resolve) => {
      try {
        const req = indexedDB.open(DB_NAME, 1);
        req.onupgradeneeded = () => req.result.createObjectStore("vectors");
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => resolve(null);
      } catch {
        resolve(null); // private mode, or storage blocked: keep them in memory
      }
    });
    return dbPromise;
  }

  async function readVector(photoId) {
    const key = `${state.version}:${photoId}`;
    if (memory.has(key)) return memory.get(key);
    const handle = await db();
    if (!handle) return null;
    return new Promise((resolve) => {
      try {
        const req = handle.transaction("vectors").objectStore("vectors").get(key);
        req.onsuccess = () => {
          if (req.result) memory.set(key, req.result);
          resolve(req.result || null);
        };
        req.onerror = () => resolve(null);
      } catch {
        resolve(null);
      }
    });
  }

  async function writeVector(photoId, vector) {
    const key = `${state.version}:${photoId}`;
    memory.set(key, vector);
    const handle = await db();
    if (!handle) return;
    try {
      handle.transaction("vectors", "readwrite").objectStore("vectors").put(vector, key);
    } catch {
      /* memory still has it */
    }
  }

  // Vectors from an older model are meaningless against the new one.
  async function forgetOtherVersions() {
    const handle = await db();
    if (!handle) return;
    try {
      const store = handle.transaction("vectors", "readwrite").objectStore("vectors");
      store.openCursor().onsuccess = (event) => {
        const cursor = event.target.result;
        if (!cursor) return;
        if (!String(cursor.key).startsWith(`${state.version}:`)) cursor.delete();
        cursor.continue();
      };
    } catch {
      /* stale vectors only cost space */
    }
  }

  // ------------------------------------------------------------------
  // The model
  // ------------------------------------------------------------------

  function loadScript(src) {
    if (window.ort) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.onload = resolve;
      script.onerror = () => reject(new Error("could not load ONNX Runtime"));
      document.head.append(script);
    });
  }

  async function download(url, bytes) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`model download failed (${res.status})`);
    const out = new Uint8Array(bytes);
    let offset = 0;
    const reader = res.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (offset + value.length > bytes) throw new Error("model file is larger than its manifest says");
      out.set(value, offset);
      offset += value.length;
      set({ progress: offset / bytes, detail: `downloading the model, ${mb(offset)} of ${mb(bytes)} (once)` });
    }
    if (offset !== bytes) throw new Error("model download was incomplete");
    return out;
  }

  async function sha256(bytes) {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  function load() {
    loading ??= (async () => {
      set({ phase: "loading", detail: "checking for a model", progress: null });
      const res = await fetch(MANIFEST_URL, { cache: "no-store" });
      if (res.status === 403 || res.status === 404) {
        // Not published yet (scripts/publish_model.py). Not an error.
        set({ phase: "unavailable", detail: "no model published" });
        return false;
      }
      if (!res.ok) throw new Error(`model manifest failed (${res.status})`);
      manifest = await res.json();
      set({ version: manifest.version });
      forgetOtherVersions();

      await loadScript(manifest.runtime.script);
      const ort = window.ort;
      ort.env.wasm.wasmPaths = manifest.runtime.wasmPath;
      // One thread: several need cross-origin isolation headers this site
      // does not send, and one is enough for a photo every second or so.
      ort.env.wasm.numThreads = 1;

      const bytes = await download(manifest.file, manifest.bytes);
      // A truncated or stale cached copy would load and silently produce
      // vectors that match nothing.
      if ((await sha256(bytes)) !== manifest.sha256) {
        throw new Error("model file is corrupted (checksum mismatch)");
      }
      set({ detail: "starting the model", progress: null });
      session = await ort.InferenceSession.create(bytes, {
        executionProviders: ["wasm"],
        graphOptimizationLevel: "all",
      });
      return true;
    })().catch((err) => {
      loading = null; // let the next queue visit try again
      set({ phase: "error", error: err.message, detail: err.message });
      throw err;
    });
    return loading;
  }

  // One inference at a time; the runtime is not re-entrant.
  let chain = Promise.resolve();
  function infer(pixels) {
    const size = manifest.inputSize;
    const run = chain.then(async () => {
      const input = new window.ort.Tensor("float32", pixels, [1, 3, size, size]);
      const out = await session.run({ image: input });
      return Float32Array.from(out.embedding.data);
    });
    chain = run.catch(() => {});
    return run;
  }

  // Centre square, bilinear-ish resize, RGB [0,1], channels first — the
  // same pixels research/catreid/export.py checked the model against.
  async function pixelsOf(url) {
    // no-store: the queue already showed this photo without CORS, and a
    // cached copy of that response would be refused here.
    const res = await fetch(url, { mode: "cors", cache: "no-store" });
    if (!res.ok) throw new Error(`photo fetch failed (${res.status})`);
    const bitmap = await createImageBitmap(await res.blob());
    const size = manifest.inputSize;
    const side = Math.min(bitmap.width, bitmap.height);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const g = canvas.getContext("2d", { willReadFrequently: true });
    g.imageSmoothingEnabled = true;
    g.imageSmoothingQuality = "high";
    g.drawImage(
      bitmap,
      (bitmap.width - side) / 2,
      (bitmap.height - side) / 2,
      side,
      side,
      0,
      0,
      size,
      size,
    );
    bitmap.close?.();
    const { data } = g.getImageData(0, 0, size, size);
    const plane = size * size;
    const out = new Float32Array(3 * plane);
    for (let i = 0; i < plane; i++) {
      out[i] = data[i * 4] / 255;
      out[plane + i] = data[i * 4 + 1] / 255;
      out[2 * plane + i] = data[i * 4 + 2] / 255;
    }
    return out;
  }

  // Vectors for many photos: cached ones straight away, the rest fetched a
  // few ahead and embedded one by one. A photo that fails is skipped, not
  // fatal — one missing derivative must not stop the desk.
  async function vectorsFor(photos, onEach) {
    const out = new Map();
    const todo = [];
    for (const p of photos) {
      const cached = await readVector(p.photoId);
      if (cached) out.set(p.photoId, cached);
      else todo.push(p);
    }
    let done = photos.length - todo.length;
    onEach?.(done, photos.length);
    const fetches = todo.map(() => null);
    const start = (i) => {
      if (i < todo.length && !fetches[i]) {
        fetches[i] = pixelsOf(todo[i].mediumUrl).catch((err) => err);
      }
    };
    for (let i = 0; i < PREFETCH; i++) start(i);
    for (let i = 0; i < todo.length; i++) {
      start(i + PREFETCH);
      const pixels = await fetches[i];
      fetches[i] = null;
      if (!(pixels instanceof Error)) {
        const vector = await infer(pixels);
        await writeVector(todo[i].photoId, vector);
        out.set(todo[i].photoId, vector);
      }
      onEach?.(++done, photos.length);
    }
    return out;
  }

  // ------------------------------------------------------------------
  // Learning the cats, and ranking them
  // ------------------------------------------------------------------

  function syncGallery({ force = false } = {}) {
    if (!force && galleryAt && Date.now() - galleryAt < GALLERY_REFRESH_MS) {
      return Promise.resolve();
    }
    gallerySync ??= (async () => {
      const { photos } = await api("/recognition/gallery");
      set({ phase: "learning", progress: 0, detail: "learning the cats" });
      const vectors = await vectorsFor(photos, (done, total) =>
        set({ progress: total ? done / total : 1, detail: `learning the cats, ${done} of ${total} photos` }),
      );
      templates = photos
        .filter((p) => vectors.has(p.photoId))
        .map((p) => ({ ...p, vector: vectors.get(p.photoId) }));
      galleryAt = Date.now();
    })().finally(() => {
      gallerySync = null;
    });
    return gallerySync;
  }

  // Each cat scores the mean, over the session's frames, of its best
  // template for that frame. Max over templates so one good view is
  // enough; mean over frames so one odd frame is not.
  function rank(queryVectors, excludeSessionId = null) {
    const best = new Map(); // catId -> per-frame best
    for (const t of templates) {
      if (excludeSessionId && t.sessionId === excludeSessionId) continue;
      let row = best.get(t.catId);
      if (!row) best.set(t.catId, (row = new Float32Array(queryVectors.length).fill(-1)));
      for (let q = 0; q < queryVectors.length; q++) {
        const s = dot(queryVectors[q], t.vector);
        if (s > row[q]) row[q] = s;
      }
    }
    return [...best]
      .map(([catId, row]) => ({ catId, score: row.reduce((a, b) => a + b, 0) / row.length }))
      .sort((a, b) => b.score - a.score);
  }

  // ------------------------------------------------------------------
  // Blind guesses for the queue
  // ------------------------------------------------------------------

  function queryPhotos(photos) {
    return spaced(
      photos.filter((p) => p.mediaType !== "video" && p.mediumUrl && !SKIP_STATUSES.has(p.status)),
      MAX_QUERY_FRAMES,
    );
  }

  async function guessOne({ session: s, photos }) {
    const sessionId = s.sessionId;
    if (guesses.has(sessionId)) return;
    const frames = queryPhotos(photos);
    if (!frames.length) {
      guesses.set(sessionId, { ranked: [], skipped: "no photos to look at (video only)" });
      return;
    }
    const vectors = await vectorsFor(frames);
    const query = frames.map((p) => vectors.get(p.photoId)).filter(Boolean);
    if (!query.length) return;
    const ranked = rank(query);
    const guess = { ranked, frames: frames.map((p) => p.photoId), recorded: false };
    guesses.set(sessionId, guess);
    try {
      await post(`/sessions/${sessionId}/prediction`, {
        modelVersion: state.version,
        ranked: ranked.slice(0, 200).map((r) => ({ catId: r.catId, score: round4(r.score) })),
        photoCount: query.length,
      });
      guess.recorded = true;
    } catch (err) {
      // 409: someone labeled it first. The guess still shows after the
      // fact, but it is not a measurement.
      if (err.status === 409) guess.late = true;
      else throw err;
    }
  }

  async function drain() {
    while (pending.length) {
      const next = pending.shift();
      set({
        phase: "guessing",
        progress: null,
        detail: `guessing, ${pending.length + 1} session${pending.length ? "s" : ""} to go`,
      });
      await guessOne(next).catch((err) => console.warn("guess failed", err));
    }
    set({ phase: "ready", progress: null, detail: readyText() });
  }

  function readyText() {
    const cats = new Set(templates.map((t) => t.catId)).size;
    return `knows ${cats} cats from ${templates.length} photos · guesses stay hidden until you label`;
  }

  // Called on every queue visit: catch up on the gallery, then guess
  // whatever in the queue has no guess yet.
  function watchQueue(sessions) {
    pending = sessions.filter((s) => !guesses.has(s.session.sessionId));
    guessing ??= (async () => {
      if (!(await load())) return;
      await syncGallery();
      if (!templates.length) {
        set({ phase: "ready", detail: "no labeled cats to learn from yet" });
        return;
      }
      await drain();
    })()
      .catch((err) => set({ phase: "error", error: err.message, detail: err.message }))
      .finally(() => {
        guessing = null;
      });
    return guessing;
  }

  // The session someone just opened goes to the front of the line.
  function prioritize(sessionId) {
    const i = pending.findIndex((s) => s.session.sessionId === sessionId);
    if (i > 0) pending.unshift(...pending.splice(i, 1));
  }

  // After a label: what the model had said. `catId` null means a new cat.
  function reveal(sessionId, catId, catName) {
    const guess = guesses.get(sessionId);
    if (!guess || !guess.ranked?.length) {
      return guess?.skipped ? null : "The model had not finished with this session.";
    }
    const first = guess.ranked[0];
    const suffix = guess.late ? " (not counted: it was labeled first)" : "";
    if (!catId || !guess.ranked.some((r) => r.catId === catId)) {
      return `New to the model. Its closest was ${nameOf(first.catId)}${suffix}.`;
    }
    const position = guess.ranked.findIndex((r) => r.catId === catId) + 1;
    if (position === 1) return `The model's first guess was ${catName} too ✓${suffix}`;
    return `The model had ${catName} at #${position}; its first guess was ${nameOf(first.catId)}${suffix}.`;
  }

  // A labeled session's photos become templates straight away — their
  // vectors were made for the guess.
  function learn(sessionId, catId) {
    const guess = guesses.get(sessionId);
    if (!guess?.frames) return;
    for (const photoId of guess.frames) {
      const vector = memory.get(`${state.version}:${photoId}`);
      if (vector && !templates.some((t) => t.photoId === photoId)) {
        templates.push({ photoId, sessionId, catId, vector });
      }
    }
    guesses.delete(sessionId);
  }

  let names = new Map();
  const nameOf = (catId) => names.get(catId) || "an unnamed cat";

  // ------------------------------------------------------------------
  // Replay: the same ranking over sessions already labeled
  // ------------------------------------------------------------------

  async function replay(onProgress) {
    if (!(await load())) throw new Error("no model published yet");
    await syncGallery({ force: true });
    const bySession = new Map();
    for (const t of templates) {
      if (!bySession.has(t.sessionId)) bySession.set(t.sessionId, []);
      bySession.get(t.sessionId).push(t);
    }
    const rows = [];
    let i = 0;
    for (const [sessionId, own] of bySession) {
      const catId = own[0].catId;
      const query = spaced(own, MAX_QUERY_FRAMES).map((t) => t.vector);
      const ranked = rank(query, sessionId);
      rows.push(scoreRow({ sessionId, catId, ranked }));
      onProgress?.(++i, bySession.size);
      if (i % 5 === 0) await new Promise((r) => setTimeout(r)); // let the page paint
    }
    set({ phase: "ready", progress: null, detail: readyText() });
    return rows;
  }

  return {
    get state() {
      return { ...state };
    },
    onChange(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    setNames(cats) {
      names = new Map(cats.map((c) => [c.catId, c.name]));
    },
    watchQueue,
    prioritize,
    reveal,
    learn,
    replay,
  };
}

// --------------------------------------------------------------------------
// Scoring — shared by the live record and the replay, so both are read the
// same way.
// --------------------------------------------------------------------------

// One measured session. `known` means the true cat was among the cats the
// model could have named; a cat it had never seen can only be "new".
export function scoreRow({ sessionId, catId, ranked }) {
  const position = ranked.findIndex((r) => r.catId === catId);
  return {
    sessionId,
    catId,
    known: position >= 0,
    rank: position >= 0 ? position + 1 : null,
    topCatId: ranked[0]?.catId ?? null,
    topScore: ranked[0]?.score ?? null,
    candidates: ranked.length,
  };
}

// Recall at 1/3/5 over known cats, kept apart from never-seen cats (an
// aggregate hides which half fails), plus the per-cat breakdown that shows
// where the errors concentrate.
export function summarize(rows) {
  const known = rows.filter((r) => r.known);
  const fresh = rows.filter((r) => !r.known);
  const hit = (k) => known.filter((r) => r.rank <= k).length;
  const perCat = new Map();
  for (const r of known) {
    const c = perCat.get(r.catId) || { catId: r.catId, sessions: 0, top1: 0, top3: 0 };
    c.sessions += 1;
    if (r.rank <= 1) c.top1 += 1;
    if (r.rank <= 3) c.top3 += 1;
    perCat.set(r.catId, c);
  }
  const median = (xs) => {
    if (!xs.length) return null;
    const s = [...xs].sort((a, b) => a - b);
    const m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  };
  // Mean candidates per known query, for the "chance" line: picking at
  // random from n cats gets k of them right k/n of the time.
  const candidates = known.length ? known.reduce((a, r) => a + r.candidates, 0) / known.length : 0;
  return {
    total: rows.length,
    known: known.length,
    fresh: fresh.length,
    top1: hit(1),
    top3: hit(3),
    top5: hit(5),
    candidates,
    perCat: [...perCat.values()].sort((a, b) => b.sessions - a.sessions || a.top1 - b.top1),
    // Where a threshold would have to sit, if one ever can.
    medianTop: {
      right: median(known.filter((r) => r.rank === 1).map((r) => r.topScore)),
      wrong: median(known.filter((r) => r.rank !== 1).map((r) => r.topScore)),
      fresh: median(fresh.map((r) => r.topScore)),
    },
  };
}

// --------------------------------------------------------------------------

function dot(a, b) {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i] * b[i];
  return s;
}

function spaced(items, n) {
  if (items.length <= n) return items;
  return Array.from({ length: n }, (_, i) => items[Math.floor((i * items.length) / n)]);
}

const round4 = (x) => Math.round(x * 10000) / 10000;
const mb = (bytes) => `${(bytes / 2 ** 20).toFixed(1)} MB`;
