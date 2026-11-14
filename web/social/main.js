// The member app (docs/app-plan/): app.html's boot. Milestone E0 is the
// groundwork only: sign in, ask the member API who you are, and show an
// empty frame in the chosen theme. The screens arrive one milestone at a
// time (E1 onward, 08-milestones.md), one module per screen in web/social/.
//
// Shared with the desk, from web/lib/: signing in, the API client, the
// photo-address cache. Rendered with Preact and htm from web/vendor/ (A4),
// never from a CDN: the page holds sign-in tokens and the iPhone app must
// open with no signal.

import { isInstalled, isNative } from "../install.js";
import { api, onSignedOut } from "../lib/api.js";
import {
  LOGIN_NOTE_KEY,
  claims,
  forgetSignIn,
  idToken,
  login,
  logout,
  readTokens,
  saveTokens,
  useConfig,
} from "../lib/auth.js";
import { html, render } from "../vendor/preact-htm.js";
import { AchievementsSheet } from "./achievements.js";
import { AppInfo, CopyInfo } from "./appinfo.js";
import { CatPage } from "./cat.js";
import { Feed } from "./feed.js";
import { Blocked, Friends, PersonPage, keepInvite, takeInvite } from "./friends.js";
import { Gallery } from "./gallery.js";
import { Home, Profile } from "./home.js";
import { MapPage } from "./map.js";
import { keepLanguage, language, loadLanguage, savedLanguage, t } from "./i18n.js";
import { Stack } from "./stack.js";
import { set, useStore } from "./store.js";
import { TabBar, watchScroll } from "./tabbar.js";
import { adoptTheme, applyTheme, savedTheme } from "./theme.js";
import { ReportSheet } from "./report.js";
import { Scan, openScan, startOutbox } from "./scan.js";
import { mark } from "./trail.js";
import { Overlays, toast } from "./ui.js";
import { unanswered } from "./asking.js";
import { FeedingSheet } from "./feeding.js";

const HOME = "/app.html";
const root = document.getElementById("root");
// A screen of the app's own: the page's "Loading…" (app.html) goes.
const show = (view) => {
  window.bgucatsStarted = true;
  document.getElementById("starting")?.remove();
  render(view, root);
};

// How long one step of the start may take before the app says it failed.
const STEP_MS = 15000;
// The service worker is registered this long after the first screen.
const WORKER_AFTER_MS = 4000;

// One step of the start, named on the page (app.html reads it when the
// start is slow) and given a time limit: a request that never answers used
// to leave a black screen for as long as anyone cared to wait.
async function step(name, work) {
  document.documentElement.dataset.boot = name;
  mark(`start: ${name}`);
  let timer;
  const late = new Promise((_, refuse) => {
    timer = setTimeout(() => refuse(new Error(t("start.tooLong"))), window.bgucatsStepMs || STEP_MS);
  });
  try {
    return await Promise.race([work(), late]);
  } catch (err) {
    err.step ??= name;
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

// The start did not finish: which step, why, and the ways out. Signing out
// is offered once there is a sign-in to leave.
function StartFailed({ at, message, signedIn }) {
  return html`
    <main class="screen center" data-screen="start-failed" data-step=${at}>
      <h1 class="title">${t("start.failedTitle")}</h1>
      <p class="lead" role="alert">${t(`start.step.${at}`)}</p>
      ${message && html`<p class="note">${message}</p>`}
      <button class="glass-button" type="button" onClick=${() => location.reload()}>${t("ui.tryAgain")}</button>
      <button class="link-button" type="button" onClick=${() => window.bgucatsReset?.()}>${t("start.reset")}</button>
      <p class="starting-note">${t("start.resetNote")}</p>
      <${CopyInfo} quiet=${true} />
      ${signedIn && html`<button class="link-button quiet" type="button" onClick=${() => logout(HOME)}>${t("signOut.button")}</button>`}
    </main>
  `;
}

// The account as the server last gave it, kept for a start with no signal.
// One person's, on their own phone, like the feed's first page (feed.js).
const ME_KEY = "bgucats.me";

function keepMe(who, me) {
  try {
    localStorage.setItem(ME_KEY, JSON.stringify({ who, me }));
  } catch {
    /* the next start with no signal says it cannot start */
  }
}

function keptMe(who) {
  try {
    const kept = JSON.parse(localStorage.getItem(ME_KEY));
    return kept?.who === who ? kept.me : null;
  } catch {
    return null;
  }
}

// Started from memory: the account is read again when the phone says it is
// back, and once a minute until then (a phone on bad Wi-Fi never says).
// An answer that refuses this person starts the app again, to be told so
// by the start itself.
function readAccountWhenBack(who) {
  let timer = 0;
  const again = async () => {
    try {
      const me = await api("/v1/me");
      keepMe(who, me);
      set({ me });
      mark("the account read again");
    } catch (err) {
      if (err.status) location.reload();
      return;
    }
    removeEventListener("online", again);
    clearInterval(timer);
  };
  addEventListener("online", again);
  timer = setInterval(again, 60000);
}

function takeNote() {
  try {
    const note = sessionStorage.getItem(LOGIN_NOTE_KEY);
    sessionStorage.removeItem(LOGIN_NOTE_KEY);
    return note;
  } catch {
    return null;
  }
}

function SignIn({ note }) {
  const start = () =>
    login({ home: HOME, onRefused: () => show(html`<${SignIn} note=${takeNote()} />`) }).catch((err) =>
      show(html`<${SignIn} note=${t("error.generic", { message: err.message })} />`),
    );
  return html`
    <main class="screen center" data-screen="sign-in">
      <h1 class="title">${t("app.name")}</h1>
      <p class="lead">${t("signIn.lead")}</p>
      ${note && html`<p class="note" role="alert">${note}</p>`}
      <button class="glass-button" type="button" onClick=${start}>${t("signIn.button")}</button>
    </main>
  `;
}

// The member API answers 404 to everything while the account's `social`
// flag is off (production, until L3).
function NotOpen() {
  return html`
    <main class="screen center" data-screen="not-open">
      <h1 class="title">${t("notOpen.title")}</h1>
      <p class="lead">${t("notOpen.body")}</p>
      <a class="glass-button" href="/?desk">${t("notOpen.desk")}</a>
    </main>
  `;
}

// An admin banned this account (B8c): every call answers 403 `banned`.
function Banned() {
  return html`
    <main class="screen center" data-screen="banned">
      <h1 class="title">${t("banned.title")}</h1>
      <p class="lead">${t("banned.body")}</p>
      <button class="glass-button" type="button" onClick=${() => logout(HOME)}>${t("signOut.button")}</button>
    </main>
  `;
}

// The frame (E1): the tabs' pages, the pages pushed over them, the tab
// bar, and the overlays (menu, dialog, toast). The screens fill in from E2.
const TAB_PAGES = { feed: Feed, home: Home };
const PAGES = {
  profile: Profile,
  cat: CatPage,
  gallery: Gallery,
  friends: Friends,
  person: PersonPage,
  map: MapPage,
  blocked: Blocked,
  appInfo: AppInfo,
};
const onScroll = watchScroll();

function Frame() {
  const tab = useStore((s) => s.tab);
  const stacked = useStore((s) => s.stack.length > 0);
  // The page on top, by name: the map fills the screen and has its own way
  // back, so the tab bar steps aside for it (app.css).
  const top = useStore((s) => s.stack[s.stack.length - 1]?.name || "");
  return html`
    <div class="frame" data-screen="frame" data-top=${top}>
      ${Object.entries(TAB_PAGES).map(
        ([id, View]) => html`<div
          class=${id === tab ? "tab-page shown" : "tab-page"}
          data-tab-page=${id}
          aria-hidden=${id === tab && !stacked ? undefined : "true"}
          inert=${id !== tab || stacked}
        >
          <div class="scroller" onScroll=${onScroll}><${View} /></div>
        </div>`,
      )}
      <${Stack} pages=${PAGES} />
      <${TabBar} onScan=${() => openScan("scan")} />
      <${Scan} />
      <${AchievementsSheet} />
      <${ReportSheet} />
      <${FeedingSheet} />
      <${Overlays} />
    </div>
  `;
}

async function boot() {
  // A friend's invite link: its code is kept before the page can leave for
  // the install page or for signing in.
  keepInvite();
  if (!isInstalled()) {
    // A browser tab gets the install page, which lives on the site's root
    // (install.js, index.html). `?browser` still opens the app in a tab.
    location.replace("/");
    return;
  }
  applyTheme(savedTheme());
  // The language this phone was last in; English if its strings cannot be
  // had (a draft taken away, or no signal on a first visit).
  await step("strings", () => loadLanguage(savedLanguage()).catch(() => loadLanguage("en")));
  useConfig(await step("settings", async () => (await fetch("/config.json")).json()));
  onSignedOut(() => show(html`<${SignIn} note=${takeNote()} />`));

  const token = await step("sign-in", () => idToken());
  if (!token) {
    mark("start: not signed in");
    show(html`<${SignIn} note=${takeNote()} />`);
    return;
  }
  saveTokens(readTokens()); // the service worker's copy, as the desk keeps it

  // Whose account: the kept copy below is used only for the same sign-in.
  const who = claims(token).sub;
  let me;
  let fromMemory = false;
  try {
    me = await step("account", () => api("/v1/me"));
    keepMe(who, me);
  } catch (err) {
    if (err.status === 404) {
      show(html`<${NotOpen} />`);
      return;
    }
    if (err.status === 403 && err.code === "banned") {
      show(html`<${Banned} />`);
      return;
    }
    if (err.status === 403 && err.code === "not_admitted") {
      // Forget the tokens, or every launch would land here again.
      const email = (claims(token).email || "").toLowerCase();
      forgetSignIn(t("signIn.refused", { email }));
      show(html`<${SignIn} note=${takeNote()} />`);
      return;
    }
    // The sign-in ended (the API refused the token): the sign-in screen is
    // up already (onSignedOut), and that is all there is to say.
    if (!readTokens()) return;
    // No answer at all: no signal, or too slow. The app opens with the
    // account as this phone last read it, because the thing it is for
    // works with no signal: photos taken now upload later (outbox.js).
    me = !err.status && keptMe(who);
    if (!me) throw err;
    fromMemory = true;
    mark("start: the account as last read (no answer)");
  }
  set({ me });
  adoptTheme(me.theme);
  // The account's language, if this account is offered it and this phone
  // is in another (a new phone, or a language no longer offered).
  const offered = me.flags?.languages || ["en"];
  const wanted = offered.includes(me.language) ? me.language : "en";
  if (wanted !== language()) {
    await loadLanguage(wanted).then(() => keepLanguage(wanted), () => {});
  }
  // The photos, picks, proposals and posts waiting on this phone go on
  // uploading, and an unfinished capture flow comes back where it was.
  startOutbox();
  document.documentElement.dataset.boot = "ready";
  mark("start: ready");
  show(html`<${Frame} />`);
  if (fromMemory) readAccountWhenBack(who);
  // The app was last closed while the phone was being asked for something
  // (asking.js): it no longer asks for that by itself, and says so once.
  const left = unanswered();
  if (left.includes("location")) toast(t("scan.locationHeld"), 7000);
  else if (left.includes("camera")) toast(t("scan.cameraHeldToast"), 7000);
  takeInvite();
  // Opens with no signal, and uploads with the app closed where the
  // browser can (sw.js). The desk registers it too; since the installed
  // app comes straight here (index.html) and "Reset" removes the worker,
  // this page must. Later, so it competes with nothing at the start. The
  // iPhone app needs none: its files are already on the phone.
  if ("serviceWorker" in navigator && !isNative()) {
    setTimeout(() => navigator.serviceWorker.register("/sw.js").catch(() => {}), WORKER_AFTER_MS);
  }
}

// A start that fails says so, and where. It used to show the sign-in
// screen with a note, to someone who was signed in.
boot().catch((err) => {
  mark(`start failed at ${err.step || "files"}: ${err.message}`);
  show(html`<${StartFailed} at=${err.step || "files"} message=${err.message} signedIn=${!!readTokens()} />`);
});
