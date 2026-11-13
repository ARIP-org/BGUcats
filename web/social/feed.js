// The feed (E2): the campus's posts, newest first, a page at a time, with
// today's cat at the top. Ported from the prototype's feed in Feed.dc.html:
// the card, the photo with its like button on glass, the photo's menu.

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.js";
import { cats, deletePost, feedPage, regionName, setLike, takeVoteBack, voteFor } from "./data.js";
import { openGallery } from "./gallery.js";
import { ago, t, tMarked } from "./i18n.js";
import { openMap } from "./map.js";
import { Empty } from "./mascot.js";
import { glass } from "./motion.js";
import { openReport } from "./report.js";
import { REFUSED, moved } from "./poll.js";
import { get, push, useStore } from "./store.js";
import { openScan, sendingState } from "./scan.js";
import { termsFirst } from "./terms.js";
import { Icon, confirm, openMenu, toast } from "./ui.js";

const openCat = (cat) => push("cat", { catId: cat.catId, title: cat.name || t("cat.noName") });

function initials(person) {
  const name = (person.displayName || person.username || "?").trim();
  const parts = name.split(/\s+/);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)).toUpperCase();
}

// A colour per person that stays the same everywhere (--avatar-0..4).
function hue(id = "") {
  let n = 0;
  for (const ch of id) n = (n * 31 + ch.charCodeAt(0)) % 5;
  return n;
}

// A person's photo, or their initials on their colour until they have one.
export function Avatar({ person, size = 42 }) {
  return html`<span
    class="avatar"
    aria-hidden="true"
    style=${{ "--size": `${size}px`, background: `var(--avatar-${hue(person.userId)})` }}
    >${person.avatar ? html`<img src=${person.avatar} alt="" loading="lazy" />` : initials(person)}</span
  >`;
}

function Heart({ on }) {
  return html`<svg class=${on ? "heart on" : "heart"} width="22" height="22" viewBox="0 0 24 24" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true">
    <path d="M12 20s-7.5-4.6-7.5-10.2A4.3 4.3 0 0 1 12 7.3a4.3 4.3 0 0 1 7.5 2.5C19.5 15.4 12 20 12 20z" />
  </svg>`;
}

function Photos({ card, onMenu }) {
  const [at, setAt] = useState(0);
  const strip = useRef(null);
  const many = card.photos.length > 1;
  const onScroll = () => {
    const el = strip.current;
    setAt(Math.round(Math.abs(el.scrollLeft) / el.clientWidth));
  };
  const alt = card.cat?.name ? t("post.photoOf", { name: card.cat.name }) : t("post.photo");
  return html`<div class="post-photos">
    <div class="photo-strip" ref=${strip} onScroll=${many ? onScroll : undefined} data-hscroll>
      ${card.photos.map(
        (photo) => html`<button
          type="button"
          class="photo"
          aria-haspopup="menu"
          aria-label=${t("post.options", { name: card.cat?.name || t("post.photo") })}
          onClick=${onMenu}
        >
          <img src=${photo.medium} alt=${alt} loading="lazy" decoding="async" />
        </button>`,
      )}
    </div>
    ${many &&
    html`<span class="photo-count" aria-label=${t("post.photoCount", { at: at + 1, count: card.photos.length })}
      >${at + 1}/${card.photos.length}</span
    >`}
  </div>`;
}

function Card({ card, onChange, onGone }) {
  const [region, setRegion] = useState(null);
  useEffect(() => {
    regionName(card.region).then(setRegion);
  }, [card.region]);

  async function like() {
    const liked = !card.liked;
    const before = card;
    onChange({ ...card, liked, likes: card.likes + (liked ? 1 : -1) });
    try {
      const answer = await setLike(card.postId, liked);
      onChange({ ...card, liked: answer.liked, likes: answer.likes });
    } catch {
      onChange(before);
      toast(t("post.likeFailed"));
    }
  }

  function menu(e) {
    const items = [];
    if (card.cat) {
      items.push({ label: t("post.seeCat", { name: card.cat.name }), pick: () => openCat(card.cat) });
      // On the cat's usual place, which the list of cats knows.
      items.push({
        label: t("post.showOnMap"),
        pick: async () => {
          const all = await cats().catch(() => ({ cats: [] }));
          openMap(all.cats.find((c) => c.catId === card.cat.catId)?.regionId || null);
        },
      });
    }
    if (!card.mine) {
      items.push({
        label: t("report.report"),
        icon: "flag",
        danger: true,
        pick: () => openReport({ type: "post", id: card.postId, name: t("report.postOf", { name: card.author.displayName || card.author.username }) }),
      });
    }
    if (card.mine) {
      items.push({
        label: t("post.delete"),
        pick: async () => {
          const yes = await confirm({
            title: t("post.deleteTitle"),
            body: t("post.deleteBody"),
            button: t("post.delete"),
            danger: true,
          });
          if (!yes) return;
          try {
            await deletePost(card.postId);
            onGone(card);
            toast(t("post.deleted"));
          } catch (err) {
            toast(t("error.generic", { message: err.message }));
          }
        },
      });
    }
    if (items.length) openMenu(e.currentTarget, { label: t("post.optionsMenu"), items });
  }

  const author = card.author.displayName || card.author.username;
  const openAuthor = () => push("person", { userId: card.author.userId, title: author });
  return html`<article class="post" data-post=${card.postId} aria-label=${t("post.label", { name: author })}>
    <div class="post-head">
      <button type="button" class="post-author" aria-label=${t("post.openAuthor", { name: author })} onClick=${openAuthor}>
        <${Avatar} person=${card.author} />
      </button>
      <div class="post-who">
        <button type="button" class="post-name" onClick=${openAuthor}>${author}</button>
        <h2 class="post-what">
          ${card.cat
            ? html`${t("post.met")}${" "}<button type="button" class="cat-link" onClick=${() => openCat(card.cat)}>
                  ${card.cat.name || t("cat.noName")}
                </button>`
            : t("post.photoPosted")}
          ${card.mine && card.state && card.state !== "visible" && html` <span class="badge">${t(`post.state.${card.state}`)}</span>`}
        </h2>
      </div>
    </div>
    <div class="post-media">
      <${Photos} card=${card} onMenu=${menu} />
      <button
        type="button"
        ref=${glass}
        class="like"
        aria-pressed=${String(card.liked)}
        aria-label=${t("post.like", { name: card.cat?.name || author })}
        onClick=${like}
      >
        <${Heart} on=${card.liked} />
        ${card.likes}
      </button>
    </div>
    ${card.text && html`<p class="post-text">${card.text}</p>`}
    <div class="post-meta">
      <span>${ago(card.createdAt)}</span>
      ${region &&
      html`<span class="post-place"
        ><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z" />
          <circle cx="12" cy="10" r="2.4" /></svg
        >${region}</span
      >`}
    </div>
  </article>`;
}

// A post still on its way: its photo from the phone under a ring that
// fills as the photos arrive, and the outbox's own words for why it waits.
// No actions yet.
function SendingCard({ card }) {
  const tick = useStore((s) => s.outboxTick);
  const [state, setState] = useState(null);
  useEffect(() => {
    let live = true;
    sendingState(card).then((now) => live && setState(now));
    return () => {
      live = false;
    };
  }, [tick, card.postId]);
  const author = card.author.displayName || card.author.username || "";
  const done = state ? state.done : 0;
  const why = card.proposal && state?.sent
    ? t("post.waitingNewCat")
    : !navigator.onLine
      ? t("post.sendingOffline")
      : state?.error
        ? t("post.sendingRetry", { message: state.error })
        : t("post.sendingPhotos", { done: Math.floor(done * card.photos.length), count: card.photos.length });
  const round = 2 * Math.PI * 20;
  return html`<article class="post sending" data-post=${card.postId} aria-label=${t("post.label", { name: author })}>
    <div class="post-head">
      <${Avatar} person=${card.author} />
      <div class="post-who">
        <span class="post-name">${author}</span>
        <h2 class="post-what">
          ${card.cat ? html`${t("post.met")} <span class="cat-link">${card.cat.name}</span>` : t("post.photoPosted")}
          ${" "}<span class="badge">${card.proposal ? t("post.waitingNewCat") : t("post.sending")}</span>
        </h2>
      </div>
    </div>
    <div class="sending-media">
      ${card.photos[0]?.medium && html`<img class="sending-photo" src=${card.photos[0].medium} alt=${t("post.photo")} />`}
      <span class="sending-ring" role="progressbar" aria-label=${t("post.sendingProgress")} aria-valuemin="0" aria-valuemax="100" aria-valuenow=${Math.round(done * 100)}>
        <svg width="52" height="52" viewBox="0 0 52 52" aria-hidden="true">
          <circle class="ring-track" cx="26" cy="26" r="20" />
          <circle class="ring-done" cx="26" cy="26" r="20" stroke-dasharray=${round} stroke-dashoffset=${round * (1 - done)} />
        </svg>
      </span>
    </div>
    <p class="sending-why" role="status">${why}</p>
    ${card.text && html`<p class="post-text">${card.text}</p>`}
  </article>`;
}

// The feed as it was last seen, kept on this phone for when there is no
// signal. One page, per person.
const keptKey = () => `bgucats.feed.${get().me?.userId || ""}`;
function keepFeed(page) {
  try {
    localStorage.setItem(keptKey(), JSON.stringify({ cards: page.cards, at: Date.now() }));
  } catch {
    /* no room, or no storage: the feed just has no memory */
  }
}
function keptFeed() {
  try {
    return JSON.parse(localStorage.getItem(keptKey()));
  } catch {
    return null;
  }
}

// The server's poll says nothing of friends; the card keeps who chose what.
const withFriends = (poll, before) => ({
  ...poll,
  options: poll.options.map((o) => ({
    ...o,
    friends: before.options.find((was) => was.nameKey === o.nameKey)?.friends || [],
  })),
});

const BOLD = { a: "vote-strong", b: "vote-strong", cat: "vote-strong", name: "vote-name-said" };

// Friends' votes on one cat's name, the prototype's name-vote card: who
// voted for what, the poll's first names with the friends who chose each,
// and a tap votes, as on the cat's page.
function VoteCard({ card, onChange }) {
  const [busy, setBusy] = useState(false);
  const { cat, poll, voters } = card;
  const catName = cat.name || t("cat.noName");
  const open = () => openCat(cat);

  async function choose(option) {
    if (busy) return;
    const before = card;
    setBusy(true);
    try {
      if (!(await termsFirst())) return;
      const key = option.mine ? null : option.nameKey;
      onChange({ ...card, poll: moved(poll, key) });
      const answer = await (key ? voteFor(cat.catId, key) : takeVoteBack(cat.catId));
      onChange({ ...card, cat: { ...cat, name: answer.name }, poll: withFriends(answer, poll) });
    } catch (err) {
      onChange(before);
      toast(REFUSED[err.code] ? t(REFUSED[err.code]) : t("error.generic", { message: err.message }));
    } finally {
      setBusy(false);
    }
  }

  const said = { a: nameOf(voters[0]), b: voters[1] && nameOf(voters[1]), // A name that already leads is the cat's name: "call Mango “Mango”" says nothing.
    cat: cat.name && cat.name !== card.name ? cat.name : t("vote.thisCat"),
    name: card.name, count: voters.length - 2 };
  const words = tMarked(voters.length > 2 ? "vote.many" : voters.length === 2 ? "vote.two" : "vote.one", said, BOLD);
  // The first three names, and always the one the card is about.
  const live = poll.options.filter((o) => !o.pending);
  const shown = live.slice(0, 3);
  const about = live.find((o) => o.name === card.name);
  if (about && !shown.includes(about)) shown[shown.length - 1] = about;
  const pct = (o) => (poll.total ? Math.round((o.votes / poll.total) * 100) : 0);
  const others = { count: card.friendsVoted };

  return html`<article class="post vote-card" data-card=${card.cardId} aria-label=${t("vote.label", { name: catName })}>
    <div class="vote-head">
      <button type="button" class="vote-cat" aria-label=${t("gallery.open", { name: catName })} onClick=${open}>
        ${cat.cover ? html`<img src=${cat.cover.thumb} alt="" loading="lazy" />` : html`<span class="vote-cat-empty" aria-hidden="true"></span>`}
        <span class="vote-who" aria-hidden="true"><${Avatar} person=${voters[0]} size=${24} /></span>
      </button>
      <p class="vote-words">${words}</p>
      <span class="vote-when">${ago(card.createdAt)}</span>
    </div>
    <div class="vote-options" role="radiogroup" aria-label=${t("poll.voteFor")}>
      ${shown.map(
        (o) => html`<button
          type="button"
          key=${o.nameKey}
          class="vote-option"
          role="radio"
          aria-checked=${String(o.mine)}
          data-name=${o.nameKey}
          disabled=${busy}
          onClick=${() => choose(o)}
        >
          <span class="vote-bar" aria-hidden="true" style=${{ inlineSize: `${pct(o)}%` }}></span>
          <span class="vote-name">${o.name}</span>
          <span class="vote-friends" aria-hidden="true">
            ${(o.friends || []).map((person) => html`<${Avatar} key=${person.userId} person=${person} size=${22} />`)}
          </span>
          <span class="vote-pct">${t("vote.percent", { percent: pct(o) })}</span>
        </button>`,
      )}
    </div>
    <div class="vote-foot">
      <span>${t("poll.votes", { count: poll.total })} · ${t(poll.myVote ? "vote.youAndFriends" : "vote.friendsVoted", others)}</span>
      <button type="button" class="vote-all" onClick=${open}>${t("vote.allNames")}</button>
    </div>
  </article>`;
}

const nameOf = (person) => person.displayName || person.username || "";

function CatOfTheDay({ cat }) {
  return html`<button type="button" class="cotd" onClick=${() => openCat(cat)} aria-label=${t("feed.cotdLabel", { name: cat.name || t("cat.noName") })}>
    ${cat.cover ? html`<img src=${cat.cover.thumb} alt="" />` : html`<span class="cotd-empty" aria-hidden="true"></span>`}
    <span class="cotd-words">
      <span class="cotd-kicker">${t("feed.cotd")}</span>
      <span class="cotd-name">${cat.name || t("cat.noName")}</span>
    </span>
    <span class="cotd-go">${t("feed.watch")}<${Icon} name="chevron" size=${16} width=${2.2} /></span>
  </button>`;
}

// The glass buttons over the feed: the gallery of every cat (E4), search,
// which opens the gallery with its search field ready, and new post (the
// capture flow, E3).
function TopButtons() {
  const collapsed = useStore((s) => s.collapsed);
  return html`<div class=${collapsed ? "top-buttons collapsed" : "top-buttons"}>
    <button type="button" class="glass-icon" ref=${glass} aria-label=${t("feed.gallery")} onClick=${() => openGallery()}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round" aria-hidden="true">
        <rect x="4" y="4" width="6.5" height="6.5" rx="1.8" /><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.8" /><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.8" /><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.8" />
      </svg>
    </button>
    <button type="button" class="search" ref=${glass} aria-label=${t("feed.search")} onClick=${() => openGallery({ search: true })}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
        <circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" />
      </svg>
      <span class="search-words">${t("feed.search")}</span>
    </button>
    <button type="button" class="glass-icon plus" ref=${glass} aria-label=${t("feed.newPost")} onClick=${() => openScan("post")}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
    </button>
  </div>`;
}

export function Feed() {
  const [cards, setCards] = useState(null);
  const [cursor, setCursor] = useState(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  // When the cards on screen are the phone's memory of the feed, not the
  // server's answer: since when.
  const [fromMemory, setFromMemory] = useState(null);
  const [today, setToday] = useState(null);
  const end = useRef(null);
  // A ref, not the state: the observer below keeps the function it was
  // given, and a state read there would be the one from that render.
  const loading = useRef(false);
  const onScreen = useRef(null);
  onScreen.current = cards;
  const tab = useStore((s) => s.tab);

  async function load(from) {
    if (loading.current) return;
    loading.current = true;
    setBusy(true);
    try {
      const page = await feedPage(from);
      setCards((now) => (from ? [...(now || []), ...page.cards] : page.cards));
      setCursor(page.cursor || null);
      setFailed(null);
      if (!from) {
        setFromMemory(null);
        keepFeed(page);
      }
    } catch (err) {
      setFailed(err.message);
      if (!from) {
        // Nothing on screen yet: the feed as this phone last saw it.
        const memory = keptFeed();
        if (!onScreen.current?.length && memory?.cards?.length) {
          setCards(memory.cards);
          setFromMemory(memory.at);
        } else {
          setCards((now) => now || []);
        }
      }
    } finally {
      loading.current = false;
      setBusy(false);
    }
  }

  useEffect(() => {
    if (tab !== "feed") return;
    load(null);
    cats()
      .then((answer) => setToday(answer.cats.find((c) => c.catId === answer.catOfTheDay) || null))
      .catch(() => {});
  }, [tab]);

  // The signal is back: the feed is asked for again.
  useEffect(() => {
    const again = () => get().tab === "feed" && load(null);
    addEventListener("online", again);
    return () => removeEventListener("online", again);
  }, []);

  // The next page, when the end of this one comes into view.
  useEffect(() => {
    if (!end.current || !cursor) return undefined;
    const watch = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) load(cursor);
    // Measured against the feed's own scroller: against the screen, the
    // margin would never reach past the scroller's clipped edge.
    }, { root: end.current.closest(".scroller"), rootMargin: "600px" });
    watch.observe(end.current);
    return () => watch.disconnect();
  }, [cursor, cards]);

  // Posts made on this phone, shown before the server has them (05-client.md,
  // "The data layer"); each drops out once the feed carries it.
  const sending = useStore((s) => s.sending) || [];
  const known = new Set((cards || []).map((c) => c.postId));
  const mineFirst = sending.filter((c) => !known.has(c.postId));
  // A post is known by its id, a friends' vote card by its cat's.
  const idOf = (c) => c.postId || c.cardId;
  const change = (next) => setCards((now) => now.map((c) => (idOf(c) === idOf(next) ? next : c)));
  const gone = (card) => setCards((now) => now.filter((c) => idOf(c) !== idOf(card)));
  // Someone blocked a moment ago: their posts leave the feed that is
  // already on screen; the next page from the server has none.
  const keptApart = useStore((s) => s.keptApart) || [];
  const shown = cards?.filter((card) => !keptApart.includes(card.author?.userId));

  return html`<${TopButtons} />
    <div class="tab-content feed">
      ${fromMemory && html`<p class="feed-note" role="status">
        ${Date.now() - fromMemory < 60000 ? t("feed.fromMemory") : t("feed.fromMemoryWhen", { when: ago(new Date(fromMemory).toISOString()) })}
      </p>`}
      ${today && html`<${CatOfTheDay} cat=${today} />`}
      ${mineFirst.map((card) => html`<${SendingCard} key=${card.postId} card=${card} />`)}
      ${shown?.map((card) =>
        card.type === "vote"
          ? html`<${VoteCard} key=${card.cardId} card=${card} onChange=${change} />`
          : html`<${Card} key=${card.postId} card=${card} onChange=${change} onGone=${gone} />`,
      )}
      ${shown && !shown.length && !mineFirst.length && !failed &&
      html`<${Empty} line=${t("feed.empty")} coat="ginger" action=${t("tab.scan")} onAction=${() => openScan("scan")} />`}
      ${failed && !fromMemory && !shown?.length &&
      html`<${Empty} line=${t("feed.failed")} alert action=${t("ui.tryAgain")} onAction=${() => load(null)} />`}
      ${cursor && html`<div ref=${end} class="feed-more" aria-hidden="true"></div>`}
      ${busy && html`<p class="loading" role="status">${t("feed.loading")}</p>`}
    </div>`;
}
