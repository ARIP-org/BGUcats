// Capture — the app's own way in, next to the Telegram and WhatsApp bots.
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
// Cat guesses (opt-in, recognition.js): after a photo, the phone runs the
// model on it and asks "Is it one of these?" with its top three. The point
// is the moment, not the label: the person is still next to the cat, so an
// unsure guess can turn into a better photo, and a known cat's encounter
// count rewards coming back to cats already met — the re-encounters that
// research/FINDINGS.md found matter most. The answer rides in the outbox
// and is kept apart from the label; the labeling desk never shows it.

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
// "on" or "off"; unset means not asked yet. The model is ~40 MB, so it is
// never downloaded without the person saying yes.
const GUESSES_KEY = "bgucats.guesses";
const GUESS_SHOWN = 3;

const VIDEO_TYPES = [
  "video/mp4;codecs=avc1",
  "video/mp4",
  "video/webm;codecs=vp9",
  "video/webm;codecs=vp8",
  "video/webm",
];

export function createCapture(ui) {
  const { el, button, toast, api, post, sectionHead, plural, fmtDate, emptyState, recognition } = ui;

  let encounter = loadEncounter();
  let stream = null;
  let recorder = null;
  let watchId = null;
  let fix = null; // {lat, lon, accuracyM, at}
  let locationState = "idle"; // idle | finding | ok | denied | unavailable
  let mounted = null; // the elements of the screen while it is showing
  // Reopening the app mid-encounter goes straight back to the camera.
  let cameraOpen = !!encounter;

  const outbox = createOutbox({ post, onChange: () => mounted && drawStrip() });

  // ---- cat guesses --------------------------------------------------------

  // This page's own photos, kept in memory for guessing: the outbox drops a
  // photo's bytes once it is uploaded.
  const shotBlobs = new Map();
  let cats = null; // catId -> { name, coverUrl }
  let guess = { status: "idle" }; // idle | preparing | waiting | looking | ready | unavailable
  let guessRun = null;
  let guessAgain = false;

  const guessesOn = () => !!recognition && readSetting() === "on";
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
      guess = { status: ready ? "waiting" : "unavailable" };
    } catch {
      guess = { status: "unavailable" }; // Capture works exactly as before
    } finally {
      stop();
    }
    drawGuess();
    if (guess.status === "waiting") updateGuess();
  }

  async function loadCats() {
    const list = (await api("/cats")).cats;
    cats = new Map(list.map((c) => [c.catId, c]));
    recognition.setNames(list);
  }

  // Re-guess after every photo, one run at a time.
  function updateGuess() {
    if (!guessesOn() || !encounter || !["waiting", "ready", "looking"].includes(guess.status)) return;
    if (guessRun) {
      guessAgain = true;
      return;
    }
    guessRun = (async () => {
      const shots = encounter.shots.filter((s) => s.kind === "photo" && shotBlobs.has(s.photoId));
      if (!shots.length) return;
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
    saveEncounter();
    drawGuess();
  }

  const catName = (id) => cats?.get(id)?.name || "this cat";

  function guessPanel() {
    const node = el("div", { className: "guess", attrs: { "aria-live": "polite" } });
    return node;
  }

  function drawGuess() {
    const node = mounted?.guess;
    if (!node) return;
    node.hidden = !guessesOn() || guess.status === "idle" || guess.status === "unavailable";
    if (node.hidden) return node.replaceChildren();

    const line = (text, kids = []) => [
      el("p", { className: "guess-line" }, [el("span", { textContent: text }), ...kids]),
    ];
    const picked = encounter?.pick;

    if (picked) {
      const again = button("Change", "btn btn-sm guess-change", changeAnswer);
      if (picked.choice === "cat") {
        const n = recognition.encountersOf(picked.catId) + 1;
        return node.replaceChildren(
          ...line(`You said ${catName(picked.catId)} · encounter #${n} with this cat`, [again]),
        );
      }
      if (picked.choice === "none") {
        return node.replaceChildren(...line("A cat we haven't met? An admin will name it.", [again]));
      }
      return node.replaceChildren(...line("Thanks. A photo of the face helps the most.", [again]));
    }

    if (guess.status === "preparing") {
      const st = recognition.state;
      return node.replaceChildren(
        ...line(`Getting ready to guess: ${st.detail || "starting"}`),
        st.progress != null ? el("progress", { max: 1, value: st.progress }) : "",
      );
    }
    if (guess.status === "waiting") return node.replaceChildren(...line("Take a photo and the app will guess who it is."));
    if (guess.status === "looking") return node.replaceChildren(...line("Looking…"));

    const tiles = guess.ranked.slice(0, GUESS_SHOWN).map((r) => {
      const cat = cats?.get(r.catId);
      const tile = el("button", { type: "button", className: "guess-pick" }, [
        cat?.coverUrl
          ? el("img", { src: cat.coverUrl, alt: "" })
          : el("span", { className: "guess-blank", textContent: "?" }),
        el("span", { className: "guess-name", textContent: catName(r.catId) }),
      ]);
      tile.onclick = () => answer("cat", r.catId);
      return tile;
    });
    node.replaceChildren(
      el("p", { className: "guess-line", textContent: "Is it one of these?" }),
      el("div", { className: "guess-picks" }, tiles),
      el("div", { className: "guess-other" }, [
        button("None of these", "btn btn-sm", () => answer("none")),
        button("Not sure", "btn btn-sm", () => answer("unsure")),
      ]),
    );
  }

  function guessSettingCard() {
    if (!recognition) return null;
    const setting = readSetting();
    const turn = (value) => () => {
      writeSetting(value);
      render();
      if (value === "on") prepareGuesses();
    };
    if (!setting) {
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
    return el("p", { className: "meta guess-setting" }, [
      setting === "on" ? "Cat guesses are on. " : "Cat guesses are off. ",
      button(setting === "on" ? "Turn off" : "Turn on", "btn btn-sm btn-ghost", turn(setting === "on" ? "off" : "on")),
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

  async function finishEncounter() {
    stopRecording();
    const finished = encounter;
    encounter = null;
    cameraOpen = false;
    for (const shot of finished.shots) shotBlobs.delete(shot.photoId);
    if (guess.status === "ready" || guess.status === "looking") guess = { status: "waiting" };
    saveEncounter();
    await outbox.closeEncounter(finished.sessionId);
    toast(
      finished.shots.length
        ? `Encounter saved · ${plural(finished.shots.length, "shot")}`
        : "Encounter closed — nothing was captured",
    );
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

  async function render() {
    if (encounter && cameraOpen) return renderCamera();
    leave();

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
            button("Done — next cat", "btn btn-lg", finishEncounter),
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

    main.replaceChildren(head, guessSettingCard() || "", current, outboxPanel(), await recentPanel());
    drawStrip();
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
    const guessNode = guessPanel();

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

    const done = button("Done — next cat", "btn", finishEncounter);

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
        guessNode,
        strip,
        status,
        el("div", { className: "capture-controls" }, [record, shutter, done]),
      ]),
    ]);
    document.body.append(camera);
    document.body.classList.add("no-scroll", "camera-open");
    // The app underneath can't be reached by focus or a screen reader while
    // the camera covers it.
    document.querySelector("#app").inert = true;

    mounted = { camera, viewfinder: camera, location, strip, status, video, guess: guessNode };
    drawLocation();
    drawStrip();
    drawGuess();
    if (guessesOn() && guess.status === "idle") prepareGuesses();

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
    const { items } = await outbox.snapshot();
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
    if (line) line.replaceChildren(...outboxSummary(items));
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

  function outboxSummary(items) {
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
      encounters = (await api("/encounters")).encounters;
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
        el("div", { className: "row" }, [
          el("span", { className: "row-main", textContent: fmtDate(e.startedAt) }),
          el("span", { className: "meta", textContent: plural(e.photoCount || 0, "file") }),
          el("span", {
            className: `tag${e.catName ? " good" : ""}`,
            textContent: e.catName || "waiting for a label",
          }),
          pickNote(e),
        ]),
      ),
    ]);
  }

  // What they answered, next to what the cat turned out to be.
  function pickNote(e) {
    if (e.pick?.choice !== "cat" || !e.pick.catName) return null;
    if (!e.catName) return el("span", { className: "meta", textContent: `you said ${e.pick.catName}` });
    const right = e.pick.catId === e.catId;
    return el("span", {
      className: `meta${right ? " pick-right" : ""}`,
      textContent: right ? "you were right ✓" : `you said ${e.pick.catName}`,
    });
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
