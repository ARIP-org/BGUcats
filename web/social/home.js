// The Home tab and the profile page it opens (E6), ported from the
// prototype's Feed.dc.html ("isHome", and the profile dialog): the glass
// pill with who you are, the Friends card with the cat sitting on it, your
// posts; and on the profile the photo, the name, your posts, the settings.
//
// What the API cannot answer yet is left out, not drawn with made-up
// numbers: friends (E7), achievements (E8), changing the name and the photo
// (B1), notifications (N2), deleting the account (B10).

import { logout } from "../lib/auth.js";
import { html, useEffect, useState } from "../vendor/preact-htm.js";
import { me as loadMe, myPosts } from "./data.js";
import { dayMonth, monthYear, t, tRich } from "./i18n.js";
import { CatFace, Mascot } from "./mascot.js";
import { glass } from "./motion.js";
import { openScan } from "./scan.js";
import { push, set, useStore } from "./store.js";
import { THEMES, chooseTheme } from "./theme.js";
import { Icon, confirm, openMenu, toast } from "./ui.js";

const HOME = "/app.html";

const nameOf = (me) => me?.displayName || me?.username || "";
const openCat = (cat) => push("cat", { catId: cat.catId, title: cat.name || t("cat.noName") });

// The caller's posts, asked for again each time the screen comes up.
function useMyPosts(shown) {
  const [posts, setPosts] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!shown) return undefined;
    let live = true;
    myPosts()
      .then((answer) => {
        if (!live) return;
        setPosts(answer.cards);
        setFailed(false);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [shown]);
  return { posts, failed };
}

function Me({ size = 48 }) {
  return html`<span class="me-avatar" aria-hidden="true" style=${{ "--size": `${size}px` }}>
    <${CatFace} size=${Math.round(size * 0.7)} />
  </span>`;
}

function postLabel(card) {
  const name = card.cat?.name || t("post.photo");
  return `${name}, ${dayMonth(card.createdAt)}`;
}

// A post in "My posts": on Home with its cat and day, on the profile the
// photo alone. One still being checked, or hidden, says so on the photo.
function PostTile({ card, small }) {
  const photo = card.photos[0];
  const marked = card.state && card.state !== "visible";
  const inside = html`<span class="post-tile-photo">
      ${photo && html`<img src=${photo.thumb} alt=${small ? postLabel(card) : ""} loading="lazy" decoding="async" />`}
      ${marked && html`<span class="badge post-tile-badge">${t(`post.state.${card.state}`)}</span>`}
    </span>
    ${!small &&
    html`<span class="post-tile-line">
      <span class="post-tile-name">${card.cat?.name || t("post.photoPosted")}</span>
      <span class="post-tile-date">${dayMonth(card.createdAt)}</span>
    </span>`}`;
  if (!card.cat) return html`<div class="post-tile" data-post=${card.postId}>${inside}</div>`;
  return html`<button
    type="button"
    class="post-tile"
    data-post=${card.postId}
    aria-label=${t("home.openPost", { name: postLabel(card) })}
    onClick=${() => openCat(card.cat)}
  >
    ${inside}
  </button>`;
}

function MyPosts({ posts, failed, small }) {
  return html`<section class=${small ? "card my-posts small" : "card my-posts"} aria-label=${t("home.myPosts")}>
    <div class="card-head">
      <h2 class="card-title">${t("home.myPosts")}</h2>
      ${posts?.length > 0 &&
      html`<span class="card-count">${t(small ? "profile.postCount" : "home.postTotal", { count: posts.length })}</span>`}
    </div>
    ${posts?.length > 0 &&
    html`<div class="post-grid">
      ${posts.map((card) => html`<${PostTile} key=${card.postId} card=${card} small=${small} />`)}
    </div>`}
    ${posts && !posts.length &&
    html`<p class="card-empty">${t("home.noPosts")}</p>
      ${!small &&
      html`<button type="button" class="glass-button small" onClick=${() => openScan("scan")}>${t("tab.scan")}</button>`}`}
    ${!posts && failed && html`<p class="card-empty" role="alert">${t("home.postsFailed")}</p>`}
    ${!posts && !failed && html`<p class="card-empty" role="status">${t("feed.loading")}</p>`}
  </section>`;
}

// The glass bar over Home: who you are (it opens the profile) and Friends.
// Scrolling down folds the pill to the photo alone and opens the Friends
// button, as the tab bar folds (tabbar.js, watchScroll).
function HomeTop({ me }) {
  const collapsed = useStore((s) => s.collapsed);
  const met = me?.counters?.all?.catsMet || 0;
  return html`<div class=${collapsed ? "home-top collapsed" : "home-top"}>
    <button
      type="button"
      class="me-pill"
      ref=${glass}
      aria-label=${t("home.profileOf", { name: nameOf(me) })}
      onClick=${() => push("profile", { title: t("profile.title") })}
    >
      <${Me} />
      <span class="me-words">
        <span class="me-name">${nameOf(me)}</span>
        <span class="me-sub"
          ><span class="me-met">${t("home.catsMet", { count: met })}</span>${me?.since &&
          ` · ${t("home.since", { date: monthYear(me.since) })}`}</span
        >
      </span>
    </button>
    <button type="button" class="friends-button" ref=${glass} aria-label=${t("home.friends")} onClick=${() => toast(t("home.friendsSoon"))}>
      <${Icon} name="friends" size=${26} width=${1.7} />
      <span class="friends-words" aria-hidden="true">${t("home.friends")}</span>
    </button>
  </div>`;
}

export function Home() {
  const me = useStore((s) => s.me);
  const shown = useStore((s) => s.tab === "home");
  const { posts, failed } = useMyPosts(shown);

  // The counters move with every pick and label: ask again when Home opens.
  useEffect(() => {
    if (!shown) return;
    loadMe()
      .then((next) => set({ me: next }))
      .catch(() => {});
  }, [shown]);

  const met = me?.counters?.all?.catsMet || 0;
  const latest = (posts || []).filter((card) => card.photos[0]).slice(0, 3);
  return html`<${HomeTop} me=${me} />
    <div class="tab-content home">
      <section class="card friends-card" aria-label=${t("home.friends")}>
        <${Mascot} coat="gray" size=${64} />
        <h2 class="card-title">${t("home.friends")}</h2>
        <div class="friend-row">
          <${Me} size=${44} />
          <span class="friend-who">
            <span class="friend-name">${t("home.you")}</span>
            <span class="friend-found">${tRich("home.found", { count: met }, "count")}</span>
          </span>
          <span class="friend-cats" aria-hidden="true">
            ${latest.map((card) => html`<img src=${card.photos[0].thumb} alt="" loading="lazy" />`)}
          </span>
        </div>
        <p class="card-note">${t("home.friendsSoon")}</p>
      </section>
      <${MyPosts} posts=${posts} failed=${failed} />
    </div>`;
}

export function Profile() {
  const me = useStore((s) => s.me);
  const theme = useStore((s) => s.theme);
  const { posts, failed } = useMyPosts(true);

  const themeMenu = (e) =>
    openMenu(e.currentTarget, {
      label: t("profile.theme"),
      items: THEMES.map((id) => ({
        label: t(`theme.${id}`),
        swatch: id,
        checked: id === theme,
        pick: () => chooseTheme(id),
      })),
    });
  // One language until E10; the menu is where the others will appear.
  const languageMenu = (e) =>
    openMenu(e.currentTarget, {
      label: t("profile.language"),
      items: [{ label: t("language.en"), checked: true, pick: () => {} }],
    });
  const signOut = async () => {
    const yes = await confirm({
      title: t("signOut.title"),
      body: t("signOut.body"),
      button: t("signOut.button"),
    });
    if (yes) logout(HOME);
  };

  return html`<div class="tab-content profile">
    <div class="profile-head">
      <${Me} size=${112} />
      <h1 class="profile-name">${nameOf(me)}</h1>
      <span class="profile-sub"
        >@${me?.username || ""}${me?.since && ` · ${t("home.since", { date: monthYear(me.since) })}`}</span
      >
    </div>

    <section class="group" aria-label=${t("profile.you")}>
      <div class="row" data-row="name">
        <span class="row-icon" aria-hidden="true"><${Icon} name="person" /></span>
        <span class="row-label">${t("profile.name")}</span>
        <span class="row-value">${nameOf(me)}</span>
      </div>
    </section>

    <${MyPosts} posts=${posts} failed=${failed} small=${true} />

    <section class="group" aria-label=${t("profile.settings")}>
      <button type="button" class="row" aria-haspopup="menu" onClick=${languageMenu}>
        <span class="row-icon" aria-hidden="true"><${Icon} name="globe" /></span>
        <span class="row-label">${t("profile.language")}</span>
        <span class="row-value">${t("language.en")}</span>
        <${Icon} name="updown" size=${16} width=${2.2} />
      </button>
      <div class="divider" aria-hidden="true"></div>
      <button type="button" class="row" aria-haspopup="menu" data-row="theme" onClick=${themeMenu}>
        <span class="row-icon" aria-hidden="true"><${Icon} name="theme" /></span>
        <span class="row-label">${t("profile.theme")}</span>
        <span class="row-value"><span class="swatch small" data-swatch=${theme}></span>${t(`theme.${theme}`)}</span>
        <${Icon} name="updown" size=${16} width=${2.2} />
      </button>
    </section>

    <section class="group" aria-label=${t("profile.account")}>
      <a class="row" href="/?desk" data-row="desk">
        <span class="row-icon neutral" aria-hidden="true"><${Icon} name="camera" /></span>
        <span class="row-label">${t("profile.desk")}</span>
        <span class="row-value"></span>
        <${Icon} name="chevron" size=${16} width=${2.2} />
      </a>
      <div class="divider" aria-hidden="true"></div>
      <button type="button" class="row" onClick=${signOut}>
        <span class="row-icon neutral" aria-hidden="true"><${Icon} name="signOut" /></span>
        <span class="row-label">${t("signOut.button")}</span>
      </button>
    </section>

    <p class="profile-foot">${t("profile.foot")}</p>
  </div>`;
}
