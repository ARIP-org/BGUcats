# App backlog

Things decided to leave for later, so they are not lost. Newest first.

## Recognition (phase 1c)

- **Thresholds, once the live record earns them.** Today the model only
  ranks. When Stats → Recognition model shows enough labeled guesses that
  the "right first" and "never seen" top scores separate, pick an accept and
  a "new cat" threshold from that record (biased toward "new cat", CLAUDE.md
  "Open-set") and put them in the manifest. *(Raised 2026-10-29.)*
- **Show the top 3 in the picker — later, and on purpose.** Guesses are
  hidden until a session is labeled, so the labels stay unbiased. Revisit
  only once the numbers are good enough that anchoring costs less than it
  saves, and keep a blind sample even then.
- **Videos are not looked at.** A video-only session gets no guess. The
  Spotter page (research/webapp) already pulls frames from a video in the
  browser; the same would work here, with CORS on the raw object.
- **Every device embeds every labeled photo.** Cheap at 225 photos (a few
  minutes once per phone), less so at thousands. The boring fix is a
  server-side vector per photo — onnxruntime and the 30 MB model fit in the
  process Lambda — which is also where the ULID-as-vector-ID of CLAUDE.md
  was always headed.

## Design

- **A better way out of the full-screen camera.** Today a round ✕ in the top
  corner closes the camera and returns to Capture, with the encounter still
  open. It works, but it is not the most convenient control: it sits far from
  the thumb, and ✕ reads as "cancel", not "step out for a moment". Revisit
  together with the rest of the camera screen. *(Raised 2026-10-28.)*

- **Safari's address bar during sign-in.** An installed iPhone app shows
  Safari's bar and toolbar whenever it is on someone else's address, and
  Google sign-in happens on Google's pages, so the bar appears for those few
  seconds. Sign-out no longer leaves the app, so that is now the only moment
  it shows, and sign-in is rare: a session lasts 30 days. Avoiding it
  entirely would need a native app or a sign-in method of our own.

## Product

- **Translate the app's own screens.** The install page is in Hebrew,
  English, Russian and Arabic; Capture and Cats are still English only. The
  install page quotes the English button names so they match the screen.
- **Remove `?browser`, or keep it.** It opens the app in a browser tab instead
  of the install page, kept as an emergency door in case sign-in fails inside
  the installed app on some phone. Decide once sign-in has been tried on real
  iPhones and Android phones.
