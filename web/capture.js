// Capture — the app's own way in, next to the Telegram bot.
//
// One encounter is one cat in one sitting: "Start an encounter", photograph
// or film that cat, "Done". That makes every encounter an identity cluster by
// construction (spec §6.1), where the bots have to guess one from a
// ten-minute idle window.
//
// The phone's GPS is read at the moment of each shot, with its accuracy, so
// the location belongs to the photo rather than to wherever the person is
// when they remember to send a pin.
//
// Everything captured goes into the outbox (outbox.js) first and uploads
// from there; this file never talks to storage itself.
//
// While an encounter is open the camera takes the whole screen, like the
// phone's own camera app. Closing it (✕) only steps back to this screen; the
// encounter stays open until "Done — next cat".
//
// Cat guesses (recognition.js, on unless turned off): while the person
// shoots, the phone runs the model on each photo in the background. "Done"
// then opens the encounter's result: "Who did you meet?", the model's top
// three, and the person's answer. The encounter stays open until they
// answer, so an unsure guess can still turn into a better photo ("Take more
// photos"), and a known cat's encounter count rewards coming back to cats
// already met — the re-encounters research/FINDINGS.md found matter most.
// The answer rides in the outbox and is kept apart from the label. None of
// this waits on, or holds up, an upload.

import { createOutbox, ulid } from "./outbox.js";

const ENCOUNTER_KEY = "bgucats.encounter";
// An encounter left open this long is someone's forgotten one, not a cat
// they are still following. Same ceiling as the bots' "New cat" session.
const ENCOUNTER_MAX_MS = 2 * 60 * 60 * 1000;
// A GPS fix older than this describes where the phone was, not the cat.
const FIX_MAX_AGE_MS = 2 * 60 * 1000;
const VIDEO_MAX_SECONDS = 10;
// Enough for recognition and for the labeling tool's 1024px view, while
// keeping a ten-second clip around 3 MB.
const VIDEO_BITS_PER_SECOND = 2_500_000;
const MAX_FILE_BYTES = { photo: 20 * 1024 * 1024, video: 60 * 1024 * 1024 };
const THUMB_PX = 160;
// "on" or "off"; unset means on — except on a phone asking to save data,
// which is asked first, since the model is ~40 MB (downloaded once).
const GUESSES_KEY = "bgucats.guesses";
const GUESS_SHOWN = 3;
// Kept with the encounter, so a reload on the result screen still has it.
const GUESS_KEPT = 200;

const VIDEO_TYPES = [
  "video/mp4;codecs=avc1",
  "video/mp4",
  "video/webm;codecs=vp9",
  "video/webm;codecs=vp8",
  "video/webm",
];

export function createCapture(ui) {
  const { el, button, toast, cachedGet, post, sectionHead, plural, fmtDate, emptyState, recognition, isAdmin } = ui;
  // A refreshed list redraws the start screen — never the camera or the
  // result screen over it.
  const get = (path) => cachedGet(path, () => !cameraOpen && !inReview() && mounted && render());

  let encounter = loadEncounter();
  let stream = null;
  let recorder = null;
  let watchId = null;
  let fix = null; // {lat, lon, accuracyM, at}
  let locationState = "idle"; // idle | finding | ok | denied | unavailable
  let mounted = null; // the elements of the screen while it is showing
  // Reopening the app mid-encounter goes straight back to where it was:
  // the camera, or the result screen ("review") after Done.
  let cameraOpen = !!encounter && encounter.stage !== "review";
  const inReview = () => encounter?.stage === "review";

  const outbox = createOutbox({ post, onChange: () => mounted && drawStrip() });

  // ---- cat guesses --------------------------------------------------------

  // This page's own photos, kept in memory for guessing: the outbox drops a
  // photo's bytes once it is uploaded.
  const shotBlobs = new Map();
  let cats = null; // catId -> { name, coverUrl }
  let guess = { status: "idle" }; // idle | preparing | waiting | looking | ready | unavailable
  let guessRun = null;
  let guessAgain = false;

  const savingData = () => !!navigator.connection?.saveData;
  const guessesOn = () => {
    if (!recognition) return false;
    const setting = readSetting();
    return setting === "on" || (setting === null && !savingData());
  };
  function readSetting() {
    try {
      return localStorage.getItem(GUESSES_KEY);
    } catch {
      return null;
    }
  }
  function writeSetting(value) {
    try {
      localStorage.setItem(GUESSES_KEY, value);
    } catch {
      /* asked again next time */
    }
  }

  async function prepareGuesses() {
    if (!guessesOn() || guess.status === "preparing") return;
    guess = { status: "preparing" };
    drawGuess();
    const stop = recognition.onChange(() => drawGuess());
    try {
      const [ready] = await Promise.all([recognition.prepareForCapture(), loadCats()]);
      // "empty": the model is here but no cat has been shared with it yet.
      guess = { status: !ready ? "unavailable" : recognition.knowsCats() ? "waiting" : "empty" };
    } catch {
      guess = { status: "unavailable" }; // Capture works exactly as before
    } finally {
      stop();
    }
    drawGuess();
    if (guess.status === "waiting") updateGuess();
  }

  async function loadCats() {
    const list = (await get("/cats")).cats;
    cats = new Map(list.map((c) => [c.catId, c]));
    recognition.setNames(list);
  }

  // Re-guess after every photo, one run at a time.
  function updateGuess() {
    if (!guessesOn() || !encounter || !["waiting", "ready", "looking", "nophotos"].includes(guess.status)) return;
    if (guessRun) {
      guessAgain = true;
      return;
    }
    const forEncounter = encounter;
    guessRun = (async () => {
      await restoreBlobs();
      const shots = forEncounter.shots.filter((s) => s.kind === "photo" && shotBlobs.has(s.photoId));
      if (!shots.length) {
        // Reopened after its photos left the phone: the kept guess stands.
        guess = forEncounter.guess ? { status: "ready", ...forEncounter.guess } : { status: "nophotos" };
        return;
      }
      if (guess.status !== "ready") {
        guess = { status: "looking" };
        drawGuess();
      }
      const result = await recognition.guessShots(
        shots.map((s) => ({ photoId: s.photoId, blob: shotBlobs.get(s.photoId) })),
      );
      if (!result || !result.ranked.length) {
        guess = { status: "unavailable" };
      } else {
        guess = { status: "ready", ...result };
        if (encounter === forEncounter) {
          encounter.guess = {
            ranked: result.ranked.slice(0, GUESS_KEPT).map((r) => ({ catId: r.catId, score: r.score })),
            photoCount: result.photoCount,
          };
          saveEncounter();
        }
      }
    })()
      .catch(() => {
        guess = { status: "unavailable" };
      })
      .finally(() => {
        guessRun = null;
        drawGuess();
        if (guessAgain) {
          guessAgain = false;
          updateGuess();
        }
      });
  }

  // After a reload the photos may only be in the outbox now.
  async function restoreBlobs() {
    if (!encounter) return;
    const missing = encounter.shots.filter((s) => s.kind === "photo" && !shotBlobs.has(s.photoId));
    if (!missing.length) return;
    const { items } = await outbox.snapshot();
    for (const item of items) {
      if (item.blob && missing.some((s) => s.photoId === item.photoId)) shotBlobs.set(item.photoId, item.blob);
    }
  }

  async function answer(choice, catId = null) {
    if (!encounter || guess.status !== "ready") return;
    const shown = guess.ranked.slice(0, GUESS_SHOWN).map((r) => r.catId);
    const pick = {
      modelVersion: recognition.state.version,
      choice,
      catId,
      shown,
      ranked: guess.ranked.slice(0, 200).map((r) => ({ catId: r.catId, score: Math.round(r.score * 1e4) / 1e4 })),
      photoCount: guess.photoCount,
      pickedAt: new Date().toISOString(),
    };
    encounter.pick = { choice, catId };
    saveEncounter();
    await outbox.setPick(encounter.sessionId, pick);
    drawGuess();
  }

  function changeAnswer() {
    if (!encounter) return;
    delete encounter.pick;
    choosingOther = false;
    saveEncounter();
    drawGuess();
  }

  // ---- the result screen ("Who did you meet?") ---------------------------

  let choosingOther = false; // the full list of cats is open
  let otherFilter = "";

  const catName = (id) => cats?.get(id)?.name || "this cat";

  function cover(catId) {
    const url = cats?.get(catId)?.coverUrl;
    return url ? el("img", { src: url, alt: "" }) : el("span", { className: "pick-cover-empty", textContent: "?" });
  }

  function drawGuess() {
    const node = mounted?.guess;
    if (!node || !encounter) return;
    if (encounter.pick) return node.replaceChildren(...answered());
    if (!guessesOn()) {
      return node.replaceChildren(
        ...note("Cat guesses are off, so there is nothing to compare. Your photos upload all the same."),
      );
    }
    if (guess.status === "idle" || guess.status === "preparing") {
      const st = recognition.state;
      return node.replaceChildren(
        ...note(`Getting the cat guesser ready: ${st.detail || "starting"}`, "result-wait"),
        st.progress != null ? el("progress", { max: 1, value: st.progress }) : "",
      );
    }
    if (guess.status === "waiting" || guess.status === "looking") {
      return node.replaceChildren(...note("Looking at your photos…", "result-wait"));
    }
    if (guess.status === "empty") {
      return node.replaceChildren(
        ...note("The app doesn't know any cats yet. Guesses start once an admin opens the Queue."),
      );
    }
    if (guess.status !== "ready") {
      return node.replaceChildren(
        ...note("No guess this time. Your photos upload all the same, and an admin will label them."),
      );
    }
    return node.replaceChildren(...(choosingOther ? otherCats() : guesses()));
  }

  // A message with the two ways on: more photos, or finish without an answer.
  function note(text, className = "muted") {
    return [
      el("p", { className, textContent: text }),
      el("div", { className: "result-actions" }, [
        button("Take more photos", "btn btn-lg", backToCamera),
        button("Finish", "btn btn-ghost", () => finishEncounter()),
      ]),
    ];
  }

  function guesses() {
    const admin = isAdmin?.();
    const tiles = guess.ranked.slice(0, GUESS_SHOWN).map((r, i) => {
      const met = recognition.encountersOf(r.catId);
      const tile = el("button", { type: "button", className: `model-pick${i === 0 ? " first" : ""}` }, [
        el("span", { className: "model-rank", textContent: `#${i + 1}` }),
        cover(r.catId),
        el("span", { className: "pick-name", textContent: catName(r.catId) }),
        el("span", {
          className: "pick-count",
          // Admins see the score. For everyone else it is a number with no
          // meaning yet (there are no thresholds), so say something useful.
          textContent: admin ? `similarity ${r.score.toFixed(2)}` : met ? `met ${met}×` : "new to the app",
        }),
      ]);
      tile.title = catName(r.catId);
      tile.onclick = () => answer("cat", r.catId);
      return tile;
    });
    return [
      el("h3", { className: "result-title", textContent: "Is it one of these?" }),
      el("p", {
        className: "meta",
        textContent: `The model's best guesses from ${plural(guess.photoCount, "photo")}. Tap the right one.`,
      }),
      el("div", { className: "model-guess-picks result-picks" }, tiles),
      el("div", { className: "result-choices" }, [
        button("Another cat…", "btn", () => {
          choosingOther = true;
          otherFilter = "";
          drawGuess();
        }),
        button("A cat that isn't here", "btn", () => answer("none")),
        button("Not sure", "btn", () => answer("unsure")),
      ]),
      el("div", { className: "result-actions" }, [
        button("Take more photos", "btn btn-ghost", backToCamera),
        button("Skip", "btn btn-ghost", () => finishEncounter()),
      ]),
    ];
  }

  // Every cat, the model's order first, with a name filter.
  function otherCats() {
    const order = new Map(guess.ranked.map((r, i) => [r.catId, i]));
    const all = [...(cats?.values() || [])].sort(
      (a, b) => (order.get(a.catId) ?? 1e9) - (order.get(b.catId) ?? 1e9) || a.name.localeCompare(b.name),
    );
    const grid = el("div", { className: "picker-grid" });
    const fill = () => {
      const needle = otherFilter.trim().toLowerCase();
      grid.replaceChildren(
        ...all
          .filter((c) => c.name.toLowerCase().includes(needle))
          .map((c) => {
            const tile = el("button", { type: "button", className: "pick" }, [
              cover(c.catId),
              el("span", { className: "pick-name", textContent: c.name }),
            ]);
            tile.onclick = () => answer("cat", c.catId);
            return tile;
          }),
      );
    };
    const search = el("input", {
      type: "search",
      className: "picker-search",
      placeholder: "Find a cat by name",
      autocomplete: "off",
      value: otherFilter,
    });
    search.oninput = () => {
      otherFilter = search.value;
      fill();
    };
    fill();
    return [
      el("div", { className: "result-head" }, [
        el("h3", { className: "result-title", textContent: "Which cat is it?" }),
        button("← Back", "btn btn-ghost btn-sm", () => {
          choosingOther = false;
          drawGuess();
        }),
      ]),
      search,
      grid,
    ];
  }

  function answered() {
    const picked = encounter.pick;
    const modelFirst = guess.ranked?.[0]?.catId ?? encounter.guess?.ranked?.[0]?.catId;
    let body;
    if (picked.choice === "cat") {
      const n = recognition.encountersOf(picked.catId) + 1;
      const agree = modelFirst === picked.catId;
      body = [
        el("div", { className: "result-cat" }, [
          cover(picked.catId),
          el("div", {}, [
            el("p", { className: "result-label", textContent: "You said" }),
            el("p", { className: "result-name", textContent: catName(picked.catId) }),
            el("p", { className: "meta", textContent: `Encounter #${n} with this cat` }),
          ]),
        ]),
        modelFirst
          ? el("p", {
              className: `result-model${agree ? " agree" : ""}`,
              textContent: agree
                ? "The model thought so too ✓"
                : `The model's first guess was ${catName(modelFirst)}.`,
            })
          : null,
      ];
    } else if (picked.choice === "none") {
      body = [
        el("p", { className: "result-name", textContent: "A cat we haven't met" }),
        el("p", { className: "meta", textContent: "An admin will give it a name. Thank you!" }),
      ];
    } else {
      body = [
        el("p", { className: "result-name", textContent: "Not sure — that's fine" }),
        el("p", { className: "meta", textContent: "An admin will label it. Next time, a photo of the face helps most." }),
      ];
    }
    return [
      el("div", { className: "result-done" }, body.filter(Boolean)),
      el("div", { className: "result-actions" }, [
        button("Next cat", "btn btn-primary btn-lg", () => finishEncounter({ next: true })),
        button("Finish", "btn btn-lg", () => finishEncounter()),
        button("Change my answer", "btn btn-ghost btn-sm", changeAnswer),
      ]),
    ];
  }

  function guessSettingCard() {
    if (!recognition) return null;
    const setting = readSetting();
    const turn = (value) => () => {
      writeSetting(value);
      render();
      if (value === "on") prepareGuesses();
    };
    if (!setting && savingData()) {
      return el("section", { className: "card panel guess-offer" }, [
        el("h3", { textContent: "Let the app guess the cat?" }),
        el("p", {
          textContent:
            "After a photo it suggests which campus cat this might be, and you say if it's right. " +
            "It's still learning, so your answer helps. It downloads about 40 MB once, " +
            "so Wi-Fi is best, and it works without signal after that.",
        }),
        el("div", { className: "capture-open-actions" }, [
          button("Turn on", "btn btn-primary", turn("on")),
          button("Not now", "btn", turn("off")),
        ]),
      ]);
    }
    const on = guessesOn();
    return el("p", { className: "meta guess-setting" }, [
      on
        ? "After each encounter the app guesses which cat it was (a 40 MB download, once). "
        : "Cat guesses are off. ",
      button(on ? "Turn off" : "Turn on", "btn btn-sm btn-ghost", turn(on ? "off" : "on")),
    ]);
  }

  // ---- encounter --------------------------------------------------------

  function loadEncounter() {
    try {
      const saved = JSON.parse(localStorage.getItem(ENCOUNTER_KEY));
      if (saved && Date.now() - Date.parse(saved.startedAt) < ENCOUNTER_MAX_MS) return saved;
    } catch {
      /* nothing saved, or unreadable — start clean */
    }
    localStorage.removeItem(ENCOUNTER_KEY);
    return null;
  }

  function saveEncounter() {
    if (encounter) localStorage.setItem(ENCOUNTER_KEY, JSON.stringify(encounter));
    else localStorage.removeItem(ENCOUNTER_KEY);
  }

  async function startEncounter() {
    const current = freshFix();
    encounter = {
      sessionId: ulid(),
      startedAt: new Date().toISOString(),
      shots: [],
    };
    saveEncounter();
    await outbox.addEncounter({
      sessionId: encounter.sessionId,
      open: true,
      lat: current?.lat,
      lon: current?.lon,
      accuracyM: current?.accuracyM,
    });
    cameraOpen = true;
    render();
  }

  // "Done": with photos and guesses on, the result screen first — the
  // encounter closes when the person answers or finishes there.
  function done() {
    stopRecording();
    if (!encounter.shots.length || !guessesOn()) return finishEncounter();
    encounter.stage = "review";
    choosingOther = false;
    cameraOpen = false;
    saveEncounter();
    render();
    updateGuess(); // picks up a photo taken in the last second
  }

  function backToCamera() {
    if (!encounter) return;
    encounter.stage = "shooting";
    cameraOpen = true;
    saveEncounter();
    render();
  }

  async function finishEncounter({ next = false } = {}) {
    stopRecording();
    const finished = encounter;
    encounter = null;
    cameraOpen = false;
    choosingOther = false;
    for (const shot of finished.shots) shotBlobs.delete(shot.photoId);
    if (guessesOn()) guess = recognition.knowsCats() ? { status: "waiting" } : guess;
    saveEncounter();
    await outbox.closeEncounter(finished.sessionId);
    if (!finished.pick) {
      toast(
        finished.shots.length
          ? `Encounter saved · ${plural(finished.shots.length, "shot")}`
          : "Encounter closed — nothing was captured",
      );
    }
    if (next) return startEncounter();
    render();
  }

  // ---- location ---------------------------------------------------------

  function watchLocation() {
    if (watchId != null) return;
    if (!navigator.geolocation) {
      locationState = "unavailable";
      return;
    }
    locationState = fix ? "ok" : "finding";
    watchId = navigator.geolocation.watchPosition(
      (pos) => {
        fix = {
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          accuracyM: pos.coords.accuracy,
          at: Date.now(),
        };
        locationState = "ok";
        drawLocation();
      },
      (err) => {
        locationState = err.code === err.PERMISSION_DENIED ? "denied" : "unavailable";
        drawLocation();
      },
      { enableHighAccuracy: true, maximumAge: 10_000, timeout: 30_000 },
    );
  }

  function stopLocation() {
    if (watchId != null) navigator.geolocation.clearWatch(watchId);
    watchId = null;
  }

  const freshFix = () => (fix && Date.now() - fix.at < FIX_MAX_AGE_MS ? fix : null);

  // ---- camera -----------------------------------------------------------

  async function startCamera(video) {
    if (!navigator.mediaDevices?.getUserMedia) return false;
    try {
      stream ??= await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
      });
    } catch {
      return false;
    }
    video.srcObject = stream;
    await video.play().catch(() => {});
    return true;
  }

  function stopCamera() {
    stopRecording();
    for (const track of stream?.getTracks() || []) track.stop();
    stream = null;
  }

  async function takePhoto(video) {
    if (!video.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    flash();
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
    await keep({ blob, kind: "photo", contentType: "image/jpeg", thumb: thumbOf(canvas) });
  }

  function toggleRecording(video, recordButton) {
    if (recorder) return stopRecording();
    const mimeType = VIDEO_TYPES.find((t) => window.MediaRecorder?.isTypeSupported?.(t));
    if (!mimeType || !stream) {
      toast("This phone can't record video in the app — use “System camera” below", true);
      return;
    }
    const chunks = [];
    const thumb = thumbOf(video);
    const started = Date.now();
    recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: VIDEO_BITS_PER_SECOND });
    recorder.ondataavailable = (event) => event.data.size && chunks.push(event.data);
    recorder.onstop = () => {
      clearInterval(tick);
      recorder = null;
      recordButton.classList.remove("recording");
      recordButton.querySelector("span").textContent = "Video";
      const contentType = mimeType.split(";")[0];
      const blob = new Blob(chunks, { type: contentType });
      const durationSeconds = Math.round((Date.now() - started) / 100) / 10;
      if (blob.size) keep({ blob, kind: "video", contentType, thumb, durationSeconds });
    };
    recorder.start(1000);
    recordButton.classList.add("recording");
    const label = recordButton.querySelector("span");
    const tick = setInterval(() => {
      const left = VIDEO_MAX_SECONDS - Math.floor((Date.now() - started) / 1000);
      label.textContent = `Stop · ${Math.max(0, left)}s`;
      if (left <= 0) stopRecording();
    }, 250);
    label.textContent = `Stop · ${VIDEO_MAX_SECONDS}s`;
  }

  function stopRecording() {
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }

  // The system camera, for phones (or installed apps) where the in-app one
  // is unavailable or refused. Photos are re-encoded through a canvas, which
  // turns HEIC into JPEG, applies the orientation and drops all EXIF.
  async function fromSystemCamera(file) {
    if (!file) return;
    if (file.type.startsWith("video/")) {
      const contentType = file.type === "video/quicktime" ? "video/quicktime" : file.type;
      if (file.size > MAX_FILE_BYTES.video) {
        toast("That video is too large — keep it under about 10 seconds", true);
        return;
      }
      await keep({ blob: file, kind: "video", contentType, thumb: null });
      return;
    }
    const bitmap = await createImageBitmap(file);
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    canvas.getContext("2d").drawImage(bitmap, 0, 0);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
    await keep({ blob, kind: "photo", contentType: "image/jpeg", thumb: thumbOf(canvas) });
  }

  async function keep({ blob, kind, contentType, thumb, durationSeconds }) {
    if (!encounter) return;
    if (blob.size > MAX_FILE_BYTES[kind]) {
      toast("That file is too large to upload", true);
      return;
    }
    const current = freshFix();
    const photoId = ulid();
    encounter.shots.push({ photoId, kind, thumb });
    saveEncounter();
    if (kind === "photo") shotBlobs.set(photoId, blob);
    await outbox.addItem({
      photoId,
      sessionId: encounter.sessionId,
      blob,
      contentType,
      capturedAt: new Date().toISOString(),
      lat: current?.lat,
      lon: current?.lon,
      accuracyM: current?.accuracyM,
      durationSeconds,
    });
    drawStrip();
    if (kind === "photo") updateGuess();
  }

  function thumbOf(source) {
    const w = source.videoWidth || source.width;
    const h = source.videoHeight || source.height;
    if (!w || !h) return null;
    const side = Math.min(w, h);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = THUMB_PX;
    canvas
      .getContext("2d")
      .drawImage(source, (w - side) / 2, (h - side) / 2, side, side, 0, 0, THUMB_PX, THUMB_PX);
    return canvas.toDataURL("image/jpeg", 0.7);
  }

  function flash() {
    const node = mounted?.viewfinder;
    if (!node) return;
    node.classList.remove("flash");
    void node.offsetWidth; // restart the animation
    node.classList.add("flash");
  }

  // ---- screen -----------------------------------------------------------

  // isCurrent: from the app's render (app.js, stillShown); false once another
  // screen was opened while this one waited for its data.
  async function render(isCurrent = () => true) {
    if (encounter && cameraOpen) return renderCamera();
    if (inReview()) return renderReview();
    leave();
    // The model loads in the background from the first visit, so a guess
    // is ready by the time anyone presses Done.
    if (guessesOn() && ["idle", "unavailable"].includes(guess.status)) prepareGuesses();

    const main = document.querySelector("#main");
    const head = sectionHead("Capture", "Every photo and video goes to the cat catalogue.");
    const strip = el("div", { className: "shot-strip" });
    mounted = { strip };

    const current = encounter
      ? el("section", { className: "card capture-start capture-open" }, [
          el("h3", { textContent: "Encounter in progress" }),
          el("p", {
            textContent: `Since ${fmtTime(encounter.startedAt)} · ${plural(encounter.shots.length, "shot")}`,
          }),
          strip,
          el("div", { className: "capture-open-actions" }, [
            button("Back to the camera", "btn btn-primary btn-lg", () => {
              cameraOpen = true;
              render();
            }),
            button("Done", "btn btn-lg", done),
          ]),
        ])
      : el("section", { className: "card capture-start" }, [
          el("h3", { textContent: "One encounter = one cat" }),
          el("p", {
            textContent:
              "Start one when you meet a cat, photograph or film just that cat, " +
              "then press Done. Next cat, next encounter.",
          }),
          el("ul", { className: "capture-tips" }, [
            el("li", { textContent: "Different angles beat many copies of the same one: face, side, back." }),
            el("li", { textContent: "A slow 5–10 second video around the cat is the best thing you can send." }),
            el("li", { textContent: "Location is saved rounded to about 100 m." }),
          ]),
          button("Start an encounter", "btn btn-primary btn-lg", startEncounter),
        ]);

    const recent = await recentPanel();
    if (!isCurrent()) return;
    main.replaceChildren(head, guessSettingCard() || "", current, outboxPanel(), recent);
    drawStrip();
  }

  // After Done: the encounter's photos (still uploading, or not) and the
  // question. The upload never waits for the answer.
  function renderReview() {
    leave();
    if (guessesOn() && ["idle", "unavailable"].includes(guess.status)) prepareGuesses();
    const strip = el("div", { className: "shot-strip" });
    const status = el("p", { className: "meta outbox-line" });
    const panel = el("section", { className: "card panel result", attrs: { "aria-live": "polite" } });
    mounted = { strip, status, guess: panel };
    document.querySelector("#main").replaceChildren(
      sectionHead(
        "Who did you meet?",
        `Encounter at ${fmtTime(encounter.startedAt)} · ${plural(encounter.shots.length, "shot")}`,
      ),
      el("section", { className: "card panel result-photos" }, [strip, status]),
      panel,
    );
    window.scrollTo(0, 0);
    drawStrip();
    drawGuess();
  }

  async function renderCamera() {
    closeCamera();
    watchLocation();

    const video = el("video", { playsInline: true, muted: true, autoplay: true });
    video.setAttribute("playsinline", "");
    const note = el("div", { className: "camera-note", textContent: "Starting the camera…" });
    const location = el("span", { className: "chip location-chip" });
    const strip = el("div", { className: "shot-strip" });
    const status = el("p", { className: "outbox-line" });

    const close = el("button", {
      type: "button",
      className: "camera-close",
      textContent: "✕",
      title: "Close the camera — the encounter stays open",
      attrs: { "aria-label": "Close the camera; the encounter stays open" },
    });
    close.onclick = () => {
      stopRecording();
      cameraOpen = false;
      render();
    };

    const shutter = el("button", { type: "button", className: "shutter", attrs: { "aria-label": "Take a photo" } }, [
      el("span", { textContent: "Photo" }),
    ]);
    shutter.onclick = () => takePhoto(video).catch((err) => toast(err.message, true));
    const record = el("button", { type: "button", className: "record", attrs: { "aria-label": "Record a video" } }, [
      el("span", { textContent: "Video" }),
    ]);
    record.onclick = () => toggleRecording(video, record);

    const systemPhoto = el("input", { type: "file", accept: "image/*", hidden: true });
    systemPhoto.setAttribute("capture", "environment");
    const systemVideo = el("input", { type: "file", accept: "video/*", hidden: true });
    systemVideo.setAttribute("capture", "environment");
    for (const input of [systemPhoto, systemVideo]) {
      input.onchange = () => {
        const [file] = input.files;
        input.value = "";
        fromSystemCamera(file).catch((err) => toast(err.message, true));
      };
    }
    // The phone's own camera, offered only when the in-app one cannot start
    // (refused, or no camera in this browser) — never alongside it.
    const fallback = el("div", { className: "system-camera" }, [
      button("Take a photo", "btn btn-lg", () => systemPhoto.click()),
      button("Record a video", "btn btn-lg", () => systemVideo.click()),
      systemPhoto,
      systemVideo,
    ]);

    const doneButton = button("Done", "btn", done);

    const camera = el("div", { className: "camera", attrs: { role: "dialog", "aria-label": "Camera" } }, [
      video,
      note,
      el("div", { className: "camera-top" }, [
        close,
        el("div", { className: "camera-title" }, [
          el("b", { textContent: "Encounter" }),
          el("span", { textContent: `since ${fmtTime(encounter.startedAt)}` }),
        ]),
        location,
      ]),
      el("div", { className: "camera-bottom" }, [
        strip,
        status,
        el("div", { className: "capture-controls" }, [record, shutter, doneButton]),
      ]),
    ]);
    document.body.append(camera);
    document.body.classList.add("no-scroll", "camera-open");
    // The app underneath can't be reached by focus or a screen reader while
    // the camera covers it.
    document.querySelector("#app").inert = true;

    mounted = { camera, viewfinder: camera, location, strip, status, video };
    drawLocation();
    drawStrip();
    if (guessesOn() && ["idle", "unavailable"].includes(guess.status)) prepareGuesses();

    const ok = await startCamera(video);
    if (mounted?.camera !== camera) return; // closed while the camera was starting
    if (ok) {
      note.remove();
    } else {
      camera.classList.add("no-camera");
      note.replaceChildren(
        el("div", { className: "camera-fallback" }, [
          el("p", { textContent: "The camera can't start inside the app here. Use the phone's own camera instead — it works the same." }),
          fallback,
        ]),
      );
      shutter.hidden = true;
      record.hidden = true;
    }
  }

  function closeCamera() {
    stopCamera();
    mounted?.camera?.remove();
    document.body.classList.remove("no-scroll", "camera-open");
    document.querySelector("#app").inert = false;
  }

  function drawLocation() {
    const chip = mounted?.location;
    if (!chip) return;
    const text = {
      idle: "📍 …",
      finding: "📍 finding location…",
      ok: fix ? `📍 ±${Math.round(fix.accuracyM)} m` : "📍 …",
      denied: "📍 location is off",
      unavailable: "📍 no location",
    }[locationState];
    chip.textContent = text;
    chip.title =
      locationState === "denied"
        ? "Allow location for this app in your phone's settings — cats are territorial, and where a cat was seen helps tell it apart."
        : "";
    chip.classList.toggle("warn", locationState === "denied" || (fix && fix.accuracyM > 100));
  }

  async function drawStrip() {
    const { items, lastError } = await outbox.snapshot();
    const byId = new Map(items.map((i) => [i.photoId, i]));

    if (mounted?.strip && encounter) {
      mounted.strip.replaceChildren(
        ...encounter.shots
          .slice()
          .reverse()
          .map((shot) => shotTile(shot, byId.get(shot.photoId))),
      );
      mounted.strip.hidden = !encounter.shots.length;
    }
    const line = mounted?.status || document.querySelector(".outbox-panel .outbox-line");
    if (line) line.replaceChildren(...outboxSummary(items, lastError));
  }

  function shotTile(shot, item) {
    const state = item ? item.state : "sent";
    const label = {
      queued: navigator.onLine ? "waiting" : "offline",
      uploading: item?.progress != null ? `${Math.round(item.progress * 100)}%` : "sending",
      failed: "failed",
      sent: "✓",
    }[state];
    return el("div", { className: `shot ${state}` }, [
      shot.thumb ? el("img", { src: shot.thumb, alt: "" }) : el("div", { className: "shot-blank" }),
      shot.kind === "video" ? el("span", { className: "shot-kind", textContent: "▶" }) : null,
      el("span", { className: "shot-state", textContent: label }),
    ]);
  }

  function outboxSummary(items, lastError) {
    const waiting = items.filter((i) => i.state !== "failed").length;
    const failed = items.filter((i) => i.state === "failed");
    const parts = [];
    if (!items.length) parts.push("Everything is uploaded.");
    if (waiting) {
      parts.push(
        navigator.onLine
          ? `${plural(waiting, "file")} uploading…`
          : `${plural(waiting, "file")} saved on this phone — they upload when you're back online.`,
      );
      // Said out loud: a queue that keeps retrying with no reason shown
      // looks exactly like a slow one.
      if (navigator.onLine && lastError) parts.push(` Retrying — last try: ${lastError}.`);
      // What leaving the app does, which differs by phone (sw.js).
      parts.push(
        outbox.backgroundSync()
          ? " You can leave the app — they keep uploading."
          : " Keep the app open until they're done: this phone pauses uploads when you leave it.",
      );
    }
    if (failed.length) {
      parts.push(
        ` ${plural(failed.length, "file")} could not be uploaded (${failed[0].error}). `,
        button("Try again", "btn btn-sm", () => outbox.retryFailed()),
      );
    }
    return parts;
  }

  function outboxPanel() {
    return el("section", { className: "card panel outbox-panel" }, [
      el("p", { className: "meta outbox-line" }),
    ]);
  }

  async function recentPanel() {
    let encounters = [];
    try {
      encounters = (await get("/encounters")).encounters;
    } catch {
      return el("section", { className: "card panel" }, [
        el("p", { className: "muted", textContent: "Your recent encounters show here when you're online." }),
      ]);
    }
    if (!encounters.length) {
      return emptyState("cat-ginger", "No encounters yet", "The first cat you photograph shows up here.");
    }
    return el("section", { className: "card panel" }, [
      el("header", { className: "panel-head" }, [el("h3", { textContent: "Your recent encounters" })]),
      ...encounters.map((e) =>
        el("div", { className: "row encounter-row" }, [
          el("span", { className: "row-main", textContent: fmtDate(e.startedAt) }),
          el("span", { className: "meta", textContent: plural(e.photoCount || 0, "file") }),
          el("span", {
            className: `tag${e.catName ? " good" : ""}`,
            textContent: e.catName || "waiting for a label",
          }),
          verdicts(e),
        ]),
      ),
    ]);
  }

  // What they said and what the model said, each against the label once
  // there is one — the result of the encounter.
  function verdicts(e) {
    if (!e.pick) return null;
    const said = (who, catId, name) => {
      if (!name) return null;
      const right = e.catId && catId === e.catId;
      const wrong = e.catId && !right;
      return el("span", {
        className: `verdict${right ? " pick-right" : wrong ? " pick-wrong" : ""}`,
        textContent: `${who}: ${name}${right ? " ✓" : wrong ? " ✗" : ""}`,
      });
    };
    const yours =
      e.pick.choice === "cat"
        ? said("you", e.pick.catId, e.pick.catName)
        : el("span", { className: "verdict", textContent: e.pick.choice === "none" ? "you: a new cat" : "you: not sure" });
    return el("span", { className: "verdicts" }, [yours, said("model", e.pick.modelCatId, e.pick.modelCatName)].filter(Boolean));
  }

  // Leaving the screen lets go of the camera and GPS — both drain a battery
  // and both show the person an "in use" indicator.
  function leave() {
    closeCamera();
    stopLocation();
    mounted = null;
  }

  // A phone that locks or switches apps gets its camera back on return.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && mounted?.video) {
      stopCamera();
    } else if (document.visibilityState === "visible" && mounted?.video && encounter && cameraOpen) {
      renderCamera();
    }
  });

  outbox.kick();
  return { render, leave, hasOpenEncounter: () => !!encounter };
}

function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}
