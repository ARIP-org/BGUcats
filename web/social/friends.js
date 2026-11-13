// Friends (E7), the prototype's friends page in Feed.dc.html: who found the
// most cats, this month or in all, as a podium of three; every friend with
// a search over the list the phone already holds; "Add friend", which is an
// invite link (D4: a link makes two people friends at once; D5: no contacts
// in the first build); and a person's page.
//
// "Block" is in a friend's menu and on anyone's page (B8); the people you
// blocked are listed, with "Unblock", from the profile.
//
// "Report" is beside it (B8b, report.js).
//
// Left out until its backend exists: finding friends from contacts (D5).

import { isNative } from "../install.js";
import { getConfig } from "../lib/auth.js";
import { html, useEffect, useRef, useState } from "../vendor/preact-htm.js";
import {
  acceptInvite,
  block,
  blocks as loadBlocks,
  cats as loadCats,
  friends as loadFriends,
  person as loadPerson,
  personPosts,
  removeFriend,
  unblock,
} from "./data.js";
import { Avatar } from "./feed.js";
import { monthYear, t, tRich } from "./i18n.js";
import { CatFace } from "./mascot.js";
import { glass } from "./motion.js";
import { openReport } from "./report.js";
import { get, pop, push, set, useStore } from "./store.js";
import { termsFirst } from "./terms.js";
import { Icon, confirm, openMenu, toast } from "./ui.js";

const INVITE_KEY = "bgucats.invite";
const CODE = /^[a-z0-9]{1,32}$/;

export const nameOf = (person) => (person.me ? t("home.you") : person.displayName || person.username || "");
const openPerson = (person) =>
  push("person", { userId: person.userId, title: person.displayName || person.username || "" });

// A person's photo or initials; you, until you choose a photo, are the
// cat's face, as on Home.
export function Face({ person, size = 44 }) {
  if (person.me && !person.avatar) {
    return html`<span class="me-avatar" aria-hidden="true" style=${{ "--size": `${size}px` }}>
      <${CatFace} size=${Math.round(size * 0.7)} />
    </span>`;
  }
  return html`<${Avatar} person=${person} size=${size} />`;
}

// {catId: cat}, from the list every screen shares.
function useCats() {
  const [byId, setById] = useState({});
  useEffect(() => {
    let live = true;
    loadCats()
      .then((answer) => live && setById(Object.fromEntries(answer.cats.map((cat) => [cat.catId, cat]))))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);
  return byId;
}

// Who found the most, asked for again whenever `shown` turns true or the
// period changes. -> { people, failed, reload }
function useFriends(period, shown = true) {
  const [people, setPeople] = useState(null);
  const [failed, setFailed] = useState(false);
  const [turn, setTurn] = useState(0);
  useEffect(() => {
    if (!shown) return undefined;
    let live = true;
    loadFriends(period)
      .then((answer) => {
        if (!live) return;
        setPeople(answer.people);
        setFailed(false);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [period, shown, turn]);
  return { people, failed, reload: () => setTurn((n) => n + 1) };
}

// "Block Maya?", then the block. -> true once they are blocked.
async function blockPerson(person) {
  const name = person.displayName || person.username;
  const yes = await confirm({
    title: t("block.title", { name }),
    body: t("block.body"),
    button: t("block.button"),
    danger: true,
  });
  if (!yes) return false;
  try {
    await block(person.userId);
    // The feed already on screen drops their posts at once (feed.js).
    set({ keptApart: [...(get().keptApart || []), person.userId] });
    toast(t("block.done", { name }));
    return true;
  } catch (err) {
    toast(t("error.generic", { message: err.message }));
    return false;
  }
}

// "Report", the last and red, as the prototype's friend menu has it.
const reportItem = (person) => ({
  label: t("report.report"),
  icon: "flag",
  danger: true,
  pick: () => openReport({ type: "user", id: person.userId, name: person.displayName || person.username }),
});

// ------------------------------------------------------------ on Home

// Home's Friends card: the first three of you and your friends, each with
// the cats they met last. The whole card opens the friends page.
export function FriendsCard({ shown, children }) {
  const { people } = useFriends("all", shown);
  const cats = useCats();
  const top = (people || []).slice(0, 3);
  const alone = people && people.length < 2;
  return html`<button type="button" class="card friends-card" aria-label=${t("friends.open")} onClick=${openFriends}>
    ${children}
    <span class="card-title">${t("home.friends")}</span>
    ${top.map(
      (person) => html`<span class="friend-row" key=${person.userId} data-person=${person.userId}>
        <${Face} person=${person} size=${44} />
        <span class="friend-who">
          <span class="friend-name">${nameOf(person)}</span>
          <span class="friend-found">${tRich("home.found", { count: person.found }, "count")}</span>
        </span>
        <span class="friend-cats" aria-hidden="true">
          ${person.cats
            .map((id) => cats[id]?.cover)
            .filter(Boolean)
            .map((cover) => html`<img src=${cover.thumb} alt="" loading="lazy" />`)}
        </span>
      </span>`,
    )}
    ${alone && html`<span class="card-note">${t("friends.inviteNote")}</span>`}
  </button>`;
}

export const openFriends = () => {
  if (get().stack.some((page) => page.name === "friends")) return;
  push("friends", { title: t("home.friends") });
};

// ------------------------------------------------------------ the invite

// The address a friend opens. The iPhone app's pages have no address of
// their own; the site's is in its config.
export function inviteLink(code) {
  const base = isNative() ? getConfig().apiBase || "" : location.origin;
  return `${base}/app.html?invite=${code}`;
}

// The code in what someone pasted: a whole link, or the code alone.
export function codeIn(text) {
  const pasted = text.trim();
  const fromLink = /[?&]invite=([a-z0-9]+)/.exec(pasted)?.[1];
  const code = fromLink || pasted.toLowerCase();
  return CODE.test(code) ? code : null;
}

const REFUSED = {
  gone: "friends.linkGone",
  own_invite: "friends.linkOwn",
  rate_limited: "poll.slowDown",
};

// -> the new friend, or null (with a toast saying why).
async function befriend(code) {
  try {
    if (!(await termsFirst())) return null;
    const { person } = await acceptInvite(code);
    toast(t("friends.added", { name: person.displayName || person.username }));
    return person;
  } catch (err) {
    toast(REFUSED[err.code] ? t(REFUSED[err.code]) : t("error.generic", { message: err.message }), 4000);
    return null;
  }
}

// A link opened on this phone: its code is kept before anything else
// happens (signing in reloads the page), and taken once the app is up.
export function keepInvite() {
  const url = new URL(location.href);
  const code = url.searchParams.get("invite");
  if (!code) return;
  url.searchParams.delete("invite");
  history.replaceState(null, "", url);
  try {
    if (CODE.test(code)) localStorage.setItem(INVITE_KEY, code);
  } catch {
    // no storage: the link does nothing this time
  }
}

export async function takeInvite() {
  let code = null;
  try {
    code = localStorage.getItem(INVITE_KEY);
    localStorage.removeItem(INVITE_KEY);
  } catch {
    return;
  }
  if (!code || code === get().me?.inviteCode) return;
  if (await befriend(code)) openFriends();
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

// "Add friend": your link, to copy or share, and a place for a link a
// friend sent you. The second is not in the prototype: a link tapped in a
// chat opens the browser, not an app added to the home screen, so there
// must be a way to bring it in by hand.
function InviteSheet({ close, added }) {
  const code = useStore((s) => s.me?.inviteCode);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const field = useRef(null);
  const link = inviteLink(code);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && close();
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);

  const doCopy = async () => {
    if (await copy(link)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } else {
      toast(t("friends.copyFailed"));
    }
  };
  const share = async () => {
    if (!navigator.share) return doCopy();
    try {
      await navigator.share({ title: t("app.name"), text: t("friends.shareText"), url: link });
    } catch {
      // closed without sharing
    }
    return undefined;
  };
  const add = async (e) => {
    e.preventDefault();
    const pasted = codeIn(field.current.value);
    if (!pasted) {
      toast(t("friends.linkGone"));
      return;
    }
    setBusy(true);
    const person = await befriend(pasted);
    setBusy(false);
    if (person) {
      added();
      close();
    }
  };

  return html`<button class="dim" aria-label=${t("ui.close")} tabindex="-1" onClick=${close}></button>
    <div class="invite-sheet" role="dialog" aria-modal="true" aria-label=${t("friends.invite")}>
      <div class="invite-head">
        <h2>${t("friends.invite")}</h2>
        <button type="button" class="round-close" aria-label=${t("ui.close")} onClick=${close}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      </div>
      <p>${t("friends.inviteBody")}</p>
      <div class="invite-link">
        <${Icon} name="link" size=${18} />
        <span class="invite-address">${link.replace(/^https?:\/\//, "")}</span>
      </div>
      <div class="invite-buttons">
        <button type="button" class="invite-copy" onClick=${doCopy}>${t(copied ? "friends.copied" : "friends.copy")}</button>
        <button type="button" class="invite-share" onClick=${share}>
          <${Icon} name="share" size=${18} />${t("friends.share")}
        </button>
      </div>
      <form class="invite-paste" onSubmit=${add}>
        <label for="invite-paste">${t("friends.haveLink")}</label>
        <div class="invite-paste-row">
          <input
            id="invite-paste"
            ref=${field}
            placeholder=${t("friends.pasteHere")}
            autocomplete="off"
            autocapitalize="none"
            autocorrect="off"
            spellcheck=${false}
            enterkeyhint="done"
          />
          <button type="submit" disabled=${busy}>${t("friends.add")}</button>
        </div>
      </form>
    </div>`;
}

// ------------------------------------------------------------ the page

function PodiumPlace({ person, place }) {
  if (!person) return html`<div class="podium-place empty" data-place=${place} aria-hidden="true"></div>`;
  return html`<div class="podium-place" data-place=${place} data-person=${person.userId}>
    ${place === 1 &&
    html`<svg class="crown" width="26" height="18" viewBox="0 0 26 18" aria-hidden="true">
      <path d="M2 16 L4 4 L9.5 9.5 L13 2 L16.5 9.5 L22 4 L24 16 Z" stroke-width="1.5" stroke-linejoin="round" />
    </svg>`}
    <${Face} person=${person} size=${place === 1 ? 56 : 48} />
    <span class="podium-name">${nameOf(person)}</span>
    <span class="podium-found">${t("friends.cats", { count: person.found })}</span>
    <div class="podium-step">${place}</div>
  </div>`;
}

const matches = (person, words) =>
  !words || `${person.displayName || ""} ${person.username || ""}`.toLowerCase().includes(words);

export function Friends() {
  const [period, setPeriod] = useState("month");
  const [search, setSearch] = useState("");
  const [inviting, setInviting] = useState(false);
  const { people, failed, reload } = useFriends(period);

  const remove = async (person) => {
    const name = person.displayName || person.username;
    const yes = await confirm({
      title: t("friends.removeTitle", { name }),
      body: t("friends.removeBody"),
      button: t("friends.removeButton"),
      danger: true,
    });
    if (!yes) return;
    try {
      await removeFriend(person.userId);
      reload();
    } catch (err) {
      toast(t("error.generic", { message: err.message }));
    }
  };
  const menu = (e, person) =>
    openMenu(e.currentTarget, {
      label: t("friends.optionsFor", { name: nameOf(person) }),
      items: [
        { label: t("friends.remove"), icon: "personMinus", pick: () => remove(person) },
        { label: t("block.block"), icon: "block", pick: async () => (await blockPerson(person)) && reload() },
        reportItem(person),
      ],
    });

  const friends = (people || []).filter((person) => !person.me);
  const words = search.trim().toLowerCase();
  const listed = friends.filter((person) => matches(person, words));
  const [first, second, third] = people || [];

  return html`<div class="friends-top">
      <button type="button" class="add-friend" ref=${glass} aria-haspopup="dialog" onClick=${() => setInviting(true)}>
        <${Icon} name="personPlus" size=${22} width=${1.9} />${t("friends.addFriend")}
      </button>
    </div>
    <div class="friends-page">
      <h1 class="page-title">${t("home.friends")}</h1>

      <div class="segments" role="tablist" aria-label=${t("friends.period")} data-at=${period}>
        <span class="segment-thumb" aria-hidden="true"></span>
        ${["month", "all"].map(
          (id) => html`<button type="button" role="tab" aria-selected=${String(period === id)} onClick=${() => setPeriod(id)}>
            ${t(`friends.period.${id}`)}
          </button>`,
        )}
      </div>

      ${people &&
      html`<section class="card podium" aria-label=${t("friends.podium")}>
        <${PodiumPlace} person=${second} place=${2} />
        <${PodiumPlace} person=${first} place=${1} />
        <${PodiumPlace} person=${third} place=${3} />
      </section>`}

      ${friends.length > 0 &&
      html`<label class="friends-search">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
            <circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" />
          </svg>
          <input
            type="search"
            aria-label=${t("friends.search")}
            placeholder=${t("friends.search")}
            autocomplete="off"
            autocapitalize="none"
            autocorrect="off"
            spellcheck=${false}
            enterkeyhint="search"
            value=${search}
            onInput=${(e) => setSearch(e.currentTarget.value)}
          />
        </label>
        <div class="card-head friends-head">
          <h2 class="card-title">${t("friends.all")}</h2>
          <span class="card-count">${t("friends.count", { count: friends.length })}</span>
        </div>
        <section class="card friends-list" aria-label=${t("friends.list")}>
          ${listed.map(
            (person) => html`<div class="friends-row" key=${person.userId} data-person=${person.userId}>
              <button type="button" class="friends-open" onClick=${() => openPerson(person)}>
                <${Face} person=${person} size=${46} />
                <span class="friend-who">
                  <span class="friend-name">${nameOf(person)}</span>
                  <span class="friend-found">@${person.username} · ${tRich("home.found", { count: person.found }, "count")}</span>
                </span>
              </button>
              <button
                type="button"
                class="friends-more"
                aria-label=${t("friends.optionsFor", { name: nameOf(person) })}
                aria-haspopup="menu"
                onClick=${(e) => menu(e, person)}
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <circle cx="5.5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="18.5" cy="12" r="2" />
                </svg>
              </button>
            </div>`,
          )}
          ${!listed.length && html`<p class="card-empty friends-none">${t("friends.noMatch", { search: search.trim() })}</p>`}
        </section>`}

      ${people &&
      !friends.length &&
      html`<section class="card friends-empty">
        <p class="card-empty">${t("friends.empty")}</p>
        <button type="button" class="glass-button small" onClick=${() => setInviting(true)}>${t("friends.invite")}</button>
      </section>`}
      ${!people && failed && html`<p class="empty" role="alert">${t("friends.failed")}</p>`}
      ${!people && !failed && html`<p class="loading" role="status">${t("feed.loading")}</p>`}
    </div>
    ${inviting && html`<${InviteSheet} close=${() => setInviting(false)} added=${reload} />`}`;
}

// ------------------------------------------------------------ a person

// A person's page: who they are, how many cats they found, since when you
// are friends, and what they posted lately.
export function PersonPage({ userId }) {
  const [person, setPerson] = useState(null);
  const [posts, setPosts] = useState(null);
  const [failed, setFailed] = useState(null);
  useEffect(() => {
    let live = true;
    loadPerson(userId)
      .then((answer) => live && setPerson(answer.person))
      .catch((err) => live && setFailed(err.code === "gone" ? t("person.gone") : t("error.generic", { message: err.message })));
    personPosts(userId)
      .then((answer) => live && setPosts(answer.cards))
      .catch(() => live && setPosts([]));
    return () => {
      live = false;
    };
  }, [userId]);

  if (failed) return html`<p class="empty" role="alert">${failed}</p>`;
  if (!person) return html`<p class="loading" role="status">${t("feed.loading")}</p>`;
  const name = person.displayName || person.username;
  const shown = (posts || []).filter((card) => card.photos[0]);
  const unfriend = async () => {
    const yes = await confirm({
      title: t("friends.removeTitle", { name }),
      body: t("friends.removeBody"),
      button: t("friends.removeButton"),
      danger: true,
    });
    if (!yes) return;
    try {
      await removeFriend(person.userId);
      setPerson({ ...person, friend: "no", friendSince: null });
    } catch (err) {
      toast(t("error.generic", { message: err.message }));
    }
  };
  const menu = (e) =>
    openMenu(e.currentTarget, {
      label: t("friends.optionsFor", { name }),
      items: [
        ...(person.friend === "yes" ? [{ label: t("friends.remove"), icon: "personMinus", pick: unfriend }] : []),
        // Blocked, their page is gone: back to where one came from.
        { label: t("block.block"), icon: "block", pick: async () => (await blockPerson(person)) && pop() },
        reportItem(person),
      ],
    });
  return html`${!person.me &&
    html`<div class="person-top">
      <button type="button" class="glass-icon" ref=${glass} aria-label=${t("friends.optionsFor", { name })} aria-haspopup="menu" onClick=${menu}>
        <${Icon} name="more" size=${22} width=${2.4} />
      </button>
    </div>`}
    <div class="person-page" data-person=${person.userId}>
    <${Face} person=${person} size=${96} />
    <div class="person-names">
      <h1 class="person-name">${name}</h1>
      <span class="person-username">@${person.username}</span>
    </div>
    <div class="person-chips">
      <span class="person-chip accent">${t("person.found", { count: person.found })}</span>
      ${person.friend === "yes" && html`<span class="person-chip">${t("person.friendsSince", { date: monthYear(person.friendSince) })}</span>`}
      ${person.me && html`<span class="person-chip">${t("person.you")}</span>`}
    </div>
    <div class="card-head person-posts-head">
      <h2 class="card-title">${t("person.posts")}</h2>
      ${shown.length > 0 && html`<span class="card-count">${t("person.latest")}</span>`}
    </div>
    ${shown.length > 0 &&
    html`<div class="person-posts">
      ${shown.map((card) => {
        const label = card.cat?.name || t("post.photo");
        const photo = html`<img src=${card.photos[0].thumb} alt=${label} loading="lazy" decoding="async" />`;
        return card.cat
          ? html`<button
              type="button"
              key=${card.postId}
              data-post=${card.postId}
              aria-label=${t("home.openPost", { name: label })}
              onClick=${() => push("cat", { catId: card.cat.catId, title: card.cat.name || t("cat.noName") })}
            >
              ${photo}
            </button>`
          : html`<div key=${card.postId} data-post=${card.postId}>${photo}</div>`;
      })}
    </div>`}
    ${posts && !shown.length && html`<p class="card-empty">${t("person.noPosts", { name })}</p>`}
  </div>`;
}

// ------------------------------------------------------------ blocked people

// The people you blocked, so there is somewhere to unblock from. The
// prototype has no such list (G4); it opens from the profile.
export function Blocked() {
  const [people, setPeople] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    loadBlocks()
      .then((answer) => live && setPeople(answer.people))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, []);

  const lift = async (person) => {
    try {
      await unblock(person.userId);
      set({ keptApart: (get().keptApart || []).filter((id) => id !== person.userId) });
      setPeople((now) => now.filter((p) => p.userId !== person.userId));
      toast(t("block.lifted", { name: person.displayName || person.username }));
    } catch (err) {
      toast(t("error.generic", { message: err.message }));
    }
  };

  return html`<div class="friends-page blocked-page">
    <h1 class="page-title">${t("block.listTitle")}</h1>
    <p class="page-lead">${t("block.listLead")}</p>
    ${people?.length > 0 &&
    html`<section class="card friends-list" aria-label=${t("block.listTitle")}>
      ${people.map(
        (person) => html`<div class="friends-row" key=${person.userId} data-person=${person.userId}>
          <span class="friends-open">
            <${Face} person=${person} size=${46} />
            <span class="friend-who">
              <span class="friend-name">${person.displayName || person.username}</span>
              <span class="friend-found">@${person.username}</span>
            </span>
          </span>
          <button type="button" class="unblock" onClick=${() => lift(person)}>${t("block.unblock")}</button>
        </div>`,
      )}
    </section>`}
    ${people && !people.length && html`<p class="empty">${t("block.none")}</p>`}
    ${!people && failed && html`<p class="empty" role="alert">${t("block.failed")}</p>`}
    ${!people && !failed && html`<p class="loading" role="status">${t("feed.loading")}</p>`}
  </div>`;
}
