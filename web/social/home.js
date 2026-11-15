// The Home tab and the profile page it opens (E6), ported from the
// prototype's Feed.dc.html ("isHome", and the profile dialog): the glass
// pill with who you are, the Friends card with the cat sitting on it, your
// posts; and on the profile the photo, the name, your posts, the settings.
//
// What the API cannot answer yet is left out, not drawn with made-up
// numbers: notifications (N2), deleting the account (B10). The Friends card
// and page are friends.js (E7), the Achievements card achievements.js (E8). The name is changed in its row on the profile (B1a),
// the photo with the pencil on it (B1b).

import { logout } from "../lib/auth.js";
import { html, useEffect, useRef, useState } from "../vendor/preact-htm.js";
import { AchievementsCard } from "./achievements.js";
import { squareJpeg } from "./avatar.js";
import { chooseUsername, deletePost, me as loadMe, myPosts, removeAvatar, saveAvatar, updateMe } from "./data.js";
import { FriendsCard, openFriends } from "./friends.js";
import { dayMonth, keepLanguage, language, LANGUAGES, monthYear, t } from "./i18n.js";
import { CatFace, Mascot } from "./mascot.js";
import { glass } from "./motion.js";
import { openScan } from "./scan.js";
import { push, set, useStore } from "./store.js";
import { termsFirst } from "./terms.js";
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
  // A post its author removed leaves the list at once.
  const gone = (card) => setPosts((now) => now?.filter((c) => c.postId !== card.postId));
  return { posts, failed, gone };
}

// A post of the caller's that others cannot see (hidden after reports, or
// by an admin): "This wasn't published", with no reason given, and one tap
// to remove it (05-client.md, "States the design does not draw").
async function notPublished(card, gone) {
  const yes = await confirm({
    title: t("post.notPublishedTitle"),
    body: t("post.notPublishedBody"),
    button: t("post.remove"),
    danger: true,
  });
  if (!yes) return;
  try {
    await deletePost(card.postId);
    gone(card);
    toast(t("post.deleted"));
  } catch (err) {
    toast(t("error.generic", { message: err.message }));
  }
}

// The caller's photo, or the cat's face until they choose one.
function Me({ size = 48 }) {
  const photo = useStore((s) => s.me?.avatar);
  return html`<span class="me-avatar" aria-hidden="true" style=${{ "--size": `${size}px` }}>
    ${photo ? html`<img src=${photo} alt="" />` : html`<${CatFace} size=${Math.round(size * 0.7)} />`}
  </span>`;
}

function postLabel(card) {
  const name = card.cat?.name || t("post.photo");
  return `${name}, ${dayMonth(card.createdAt)}`;
}

// A post in "My posts": on Home with its cat and day, on the profile the
// photo alone. One still being checked, or hidden, says so on the photo.
function PostTile({ card, small, onGone }) {
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
  if (card.state === "hidden") {
    return html`<button type="button" class="post-tile" data-post=${card.postId} data-state="hidden" aria-label=${t("post.notPublishedTitle")} aria-haspopup="dialog" onClick=${() => notPublished(card, onGone)}>
      ${inside}
    </button>`;
  }
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

function MyPosts({ posts, failed, small, onGone }) {
  return html`<section class=${small ? "card my-posts small" : "card my-posts"} aria-label=${t("home.myPosts")}>
    <div class="card-head">
      <h2 class="card-title">${t("home.myPosts")}</h2>
      ${posts?.length > 0 &&
      html`<span class="card-count">${t(small ? "profile.postCount" : "home.postTotal", { count: posts.length })}</span>`}
    </div>
    ${posts?.length > 0 &&
    html`<div class="post-grid">
      ${posts.map((card) => html`<${PostTile} key=${card.postId} card=${card} small=${small} onGone=${onGone} />`)}
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
    <button type="button" class="friends-button" ref=${glass} aria-label=${t("home.friends")} onClick=${openFriends}>
      <${Icon} name="friends" size=${26} width=${1.7} />
      <span class="friends-words" aria-hidden="true">${t("home.friends")}</span>
    </button>
  </div>`;
}

export function Home() {
  const me = useStore((s) => s.me);
  const shown = useStore((s) => s.tab === "home");
  const { posts, failed, gone } = useMyPosts(shown);

  // The counters move with every pick and label: ask again when Home opens.
  useEffect(() => {
    if (!shown) return;
    loadMe()
      .then((next) => set({ me: next }))
      .catch(() => {});
  }, [shown]);

  return html`<${HomeTop} me=${me} />
    <div class="tab-content home">
      <${FriendsCard} shown=${shown}><${Mascot} coat="gray" size=${64} /><//>
      <${AchievementsCard} shown=${shown} />
      <${MyPosts} posts=${posts} failed=${failed} onGone=${gone} />
    </div>`;
}

// A row whose value is typed in place and saved when the field is left or
// "done" is pressed, as the prototype's name row is. `save(text)` answers
// who the person is now (or null if they backed out); `shown(me)` is what
// the field then shows, as the server cleaned it.
//
// The field is the browser's own while someone types in it. Given its text
// as `value`, Preact would write it back on every redraw, and Home asks who
// you are again just as the profile opens: the letters typed meanwhile were
// gone, and "done" saved nothing.
function TextRow({ row, icon, label, value, shown, field, save, errors = {} }) {
  const input = useRef(null);
  useEffect(() => {
    const el = input.current;
    if (el && document.activeElement !== el) el.value = value;
  }, [value]);

  const commit = async (e) => {
    const el = e.currentTarget;
    const text = el.value.replace(/\s+/g, " ").trim();
    if (!text || text === value) {
      el.value = value;
      return;
    }
    try {
      const next = await save(text);
      el.value = next ? shown(next) : value;
    } catch (err) {
      el.value = value;
      toast(errors[err.code] ? t(errors[err.code]) : t("error.generic", { message: err.message }));
    }
  };
  const doneOnEnter = (e) => {
    if (e.key === "Enter") e.currentTarget.blur();
  };
  return html`<label class="row" data-row=${row}>
    <span class="row-icon" aria-hidden="true"><${Icon} name=${icon} /></span>
    <span class="row-label">${label}</span>
    <input class="row-input" ref=${input} defaultValue=${value} enterkeyhint="done" ...${field} onChange=${commit} onKeyDown=${doneOnEnter} />
  </label>`;
}

export function Profile() {
  const me = useStore((s) => s.me);
  const theme = useStore((s) => s.theme);
  const { posts, failed, gone } = useMyPosts(true);

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
  // The languages this account is offered (`flags.languages`), each by its
  // own name. Choosing one saves it with the account and on this phone, and
  // starts the app again in it: every screen is drawn from the strings.
  const offered = (me?.flags?.languages || ["en"]).filter((code) => code in LANGUAGES);
  const chooseLanguage = async (code) => {
    if (code === language()) return;
    try {
      await updateMe({ language: code });
    } catch (err) {
      toast(t("error.generic", { message: err.message }));
      return;
    }
    keepLanguage(code);
    location.reload();
  };
  const languageMenu = (e) =>
    openMenu(e.currentTarget, {
      label: t("profile.language"),
      items: offered.map((code) => ({
        label: LANGUAGES[code],
        checked: code === language(),
        pick: () => chooseLanguage(code),
      })),
    });
  const signOut = async () => {
    const yes = await confirm({
      title: t("signOut.title"),
      body: t("signOut.body"),
      button: t("signOut.button"),
    });
    if (yes) logout(HOME);
  };

  // A name others read needs the terms first; then the server's answer is
  // who you are now. `save` returns what the field should show.
  const changing = (send, saved) => async (text) => {
    if (!(await termsFirst())) return null;
    const next = await send(text);
    set({ me: next });
    toast(t(saved));
    return next;
  };
  const saveName = changing((displayName) => updateMe({ displayName }), "profile.nameSaved");
  const saveUsername = changing(chooseUsername, "profile.usernameSaved");
  const said = {
    name: { rate_limited: "profile.nameLimit" },
    username: {
      rate_limited: "profile.usernameLimit",
      name_taken: "profile.usernameTaken",
      bad_username: "profile.usernameRule",
    },
  };

  // The photo: taken now or chosen, made small on the phone (avatar.js),
  // sent, and shown at once. Everyone else sees it once it has been checked.
  const camera = useRef(null);
  const library = useRef(null);
  const [savingPhoto, setSavingPhoto] = useState(false);
  const photoPicked = async (e) => {
    const file = e.currentTarget.files?.[0];
    e.currentTarget.value = ""; // the same picture can be chosen again
    if (!file) return;
    try {
      if (!(await termsFirst())) return;
      setSavingPhoto(true);
      set({ me: await saveAvatar(await squareJpeg(file)) });
      toast(t("profile.photoSaved"));
    } catch (err) {
      toast(
        err.code === "rate_limited"
          ? t("profile.photoLimit")
          : err.status
            ? t("error.generic", { message: err.message })
            : t("profile.photoBad"),
      );
    } finally {
      setSavingPhoto(false);
    }
  };
  const removePhoto = async () => {
    try {
      set({ me: await removeAvatar() });
      toast(t("profile.photoRemoved"));
    } catch (err) {
      toast(t("error.generic", { message: err.message }));
    }
  };
  const photoMenu = (e) =>
    openMenu(e.currentTarget, {
      label: t("profile.photoMenu"),
      items: [
        { label: t("profile.photoTake"), icon: "camera", pick: () => camera.current?.click() },
        { label: t("profile.photoChoose"), icon: "library", pick: () => library.current?.click() },
        ...(me?.avatar ? [{ label: t("profile.photoRemove"), icon: "trash", danger: true, pick: removePhoto }] : []),
      ],
    });

  return html`<div class="tab-content profile">
    <div class="profile-head">
      <div class=${savingPhoto ? "profile-photo busy" : "profile-photo"}>
        <${Me} size=${112} />
        <button
          type="button"
          class="glass-icon"
          ref=${glass}
          aria-label=${t("profile.photoChange")}
          aria-haspopup="menu"
          disabled=${savingPhoto}
          onClick=${photoMenu}
        >
          <${Icon} name="pencil" size=${17} />
        </button>
        <input ref=${camera} class="hidden-input" type="file" accept="image/*" capture="user" tabindex="-1" aria-hidden="true" data-photo="camera" onChange=${photoPicked} />
        <input ref=${library} class="hidden-input" type="file" accept="image/*" tabindex="-1" aria-hidden="true" data-photo="library" onChange=${photoPicked} />
      </div>
      <h1 class="profile-name">${nameOf(me)}</h1>
      <span class="profile-sub"
        >@${me?.username || ""}${me?.since && ` · ${t("home.since", { date: monthYear(me.since) })}`}</span
      >
    </div>

    <section class="group" aria-label=${t("profile.you")}>
      <${TextRow}
        row="name"
        icon="person"
        label=${t("profile.name")}
        value=${nameOf(me)}
        shown=${nameOf}
        field=${{ "aria-label": t("profile.nameLabel"), placeholder: t("profile.namePlaceholder"), maxlength: "30", autocomplete: "nickname", autocapitalize: "words" }}
        save=${saveName}
        errors=${said.name}
      />
      <div class="divider" aria-hidden="true"></div>
      <${TextRow}
        row="username"
        icon="at"
        label=${t("profile.username")}
        value=${me?.username || ""}
        shown=${(next) => next.username}
        field=${{ "aria-label": t("profile.username"), maxlength: "20", autocomplete: "username", autocapitalize: "none", autocorrect: "off", spellcheck: false }}
        save=${saveUsername}
        errors=${said.username}
      />
    </section>
    ${me?.namePending && html`<p class="group-note" role="status">${t("profile.nameChecking")}</p>`}
    ${me?.avatarPending && html`<p class="group-note" role="status">${t("profile.photoChecking")}</p>`}

    <${MyPosts} posts=${posts} failed=${failed} small=${true} onGone=${gone} />

    <section class="group" aria-label=${t("profile.settings")}>
      <button type="button" class="row" aria-haspopup="menu" data-row="language" onClick=${languageMenu}>
        <span class="row-icon" aria-hidden="true"><${Icon} name="globe" /></span>
        <span class="row-label">${t("profile.language")}</span>
        <span class="row-value">${LANGUAGES[language()]}</span>
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
      <button type="button" class="row" data-row="blocked" onClick=${() => push("blocked", { title: t("block.listTitle") })}>
        <span class="row-icon neutral" aria-hidden="true"><${Icon} name="block" /></span>
        <span class="row-label">${t("block.listTitle")}</span>
        <span class="row-value"></span>
        <${Icon} name="chevron" size=${16} width=${2.2} />
      </button>
      <div class="divider" aria-hidden="true"></div>
      <button type="button" class="row" data-row="app-info" onClick=${() => push("appInfo", { title: t("appInfo.title") })}>
        <span class="row-icon neutral" aria-hidden="true"><${Icon} name="info" /></span>
        <span class="row-label">${t("appInfo.title")}</span>
        <span class="row-value"></span>
        <${Icon} name="chevron" size=${16} width=${2.2} />
      </button>
      <div class="divider" aria-hidden="true"></div>
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
