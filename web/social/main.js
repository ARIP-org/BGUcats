// The member app (docs/app-plan/): app.html's boot. Milestone E0 is the
// groundwork only: sign in, ask the member API who you are, and show an
// empty frame in the chosen theme. The screens arrive one milestone at a
// time (E1 onward, 08-milestones.md), one module per screen in web/social/.
//
// Shared with the desk, from web/lib/: signing in, the API client, the
// photo-address cache. Rendered with Preact and htm from web/vendor/ (A4),
// never from a CDN: the page holds sign-in tokens and the iPhone app must
// open with no signal.

import { isInstalled } from "../install.js";
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
import { CatPage } from "./cat.js";
import { Feed } from "./feed.js";
import { Blocked, Friends, PersonPage, keepInvite, takeInvite } from "./friends.js";
import { Gallery } from "./gallery.js";
import { Home, Profile } from "./home.js";
import { MapPage } from "./map.js";
import { loadLanguage, t } from "./i18n.js";
import { Stack } from "./stack.js";
import { set, useStore } from "./store.js";
import { TabBar, watchScroll } from "./tabbar.js";
import { adoptTheme, applyTheme, savedTheme } from "./theme.js";
import { ReportSheet } from "./report.js";
import { Scan, openScan, startOutbox } from "./scan.js";
import { Overlays, toast } from "./ui.js";
import { unanswered } from "./asking.js";
import { FeedingSheet } from "./feeding.js";

const HOME = "/app.html";
const root = document.getElementById("root");
const show = (view) => render(view, root);

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
const PAGES = { profile: Profile, cat: CatPage, gallery: Gallery, friends: Friends, person: PersonPage, map: MapPage, blocked: Blocked };
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
  await loadLanguage("en");
  useConfig(await (await fetch("/config.json")).json());
  onSignedOut(() => show(html`<${SignIn} note=${takeNote()} />`));

  const token = await idToken();
  if (!token) {
    show(html`<${SignIn} note=${takeNote()} />`);
    return;
  }
  saveTokens(readTokens()); // the service worker's copy, as the desk keeps it

  let me;
  try {
    me = await api("/v1/me");
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
    throw err;
  }
  set({ me });
  adoptTheme(me.theme);
  // The photos, picks, proposals and posts waiting on this phone go on
  // uploading, and an unfinished capture flow comes back where it was.
  startOutbox();
  show(html`<${Frame} />`);
  // The app was last closed while the phone was being asked for something
  // (asking.js): it no longer asks for that by itself, and says so once.
  const left = unanswered();
  if (left.includes("location")) toast(t("scan.locationHeld"), 7000);
  else if (left.includes("camera")) toast(t("scan.cameraHeldToast"), 7000);
  takeInvite();
}

boot().catch((err) => show(html`<${SignIn} note=${t("error.generic", { message: err.message })} />`));
