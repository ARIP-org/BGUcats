// The feed (E2): the campus's posts, newest first, a page at a time, with
// today's cat at the top. Ported from the prototype's feed in Feed.dc.html:
// the card, the photo with its like button on glass, the photo's menu.

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.js";
import { cats, deletePost, feedPage, regionName, setLike } from "./data.js";
import { ago, t } from "./i18n.js";
import { glass } from "./motion.js";
import { push, useStore } from "./store.js";
import { openScan } from "./scan.js";
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

export function Avatar({ person, size = 42 }) {
  return html`<span
    class="avatar"
    aria-hidden="true"
    style=${{ "--size": `${size}px`, background: `var(--avatar-${hue(person.userId)})` }}
    >${initials(person)}</span
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
    if (card.cat) items.push({ label: t("post.seeCat", { name: card.cat.name }), pick: () => openCat(card.cat) });
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
  return html`<article class="post" data-post=${card.postId} aria-label=${t("post.label", { name: author })}>
    <div class="post-head">
      <${Avatar} person=${card.author} />
      <div class="post-who">
        <span class="post-name">${author}</span>
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

// A post still on its way: its photo from the phone, a note, no actions.
function SendingCard({ card }) {
  const author = card.author.displayName || card.author.username || "";
  const waiting = card.proposal ? t("post.waitingNewCat") : t("post.sending");
  return html`<article class="post sending" data-post=${card.postId} aria-label=${t("post.label", { name: author })}>
    <div class="post-head">
      <${Avatar} person=${card.author} />
      <div class="post-who">
        <span class="post-name">${author}</span>
        <h2 class="post-what">
          ${card.cat ? html`${t("post.met")} <span class="cat-link">${card.cat.name}</span>` : t("post.photoPosted")}
          ${" "}<span class="badge">${waiting}</span>
        </h2>
      </div>
    </div>
    ${card.photos[0]?.medium && html`<img class="sending-photo" src=${card.photos[0].medium} alt=${t("post.photo")} />`}
    ${card.text && html`<p class="post-text">${card.text}</p>`}
  </article>`;
}

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

// The two glass buttons over the feed: search (the gallery, E4) and new
// post (the capture flow, E3).
function TopButtons() {
  const collapsed = useStore((s) => s.collapsed);
  return html`<div class=${collapsed ? "top-buttons collapsed" : "top-buttons"}>
    <button type="button" class="search" ref=${glass} aria-label=${t("feed.search")} onClick=${() => toast(t("feed.searchSoon"))}>
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
  const [today, setToday] = useState(null);
  const end = useRef(null);
  // A ref, not the state: the observer below keeps the function it was
  // given, and a state read there would be the one from that render.
  const loading = useRef(false);
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
    } catch (err) {
      setFailed(err.message);
      if (!from) setCards((now) => now || []);
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
  const change = (next) => setCards((now) => now.map((c) => (c.postId === next.postId ? next : c)));
  const gone = (card) => setCards((now) => now.filter((c) => c.postId !== card.postId));

  return html`<${TopButtons} />
    <div class="tab-content feed">
      ${today && html`<${CatOfTheDay} cat=${today} />`}
      ${mineFirst.map((card) => html`<${SendingCard} key=${card.postId} card=${card} />`)}
      ${cards?.map((card) => html`<${Card} key=${card.postId} card=${card} onChange=${change} onGone=${gone} />`)}
      ${cards && !cards.length && !failed && html`<p class="empty">${t("feed.empty")}</p>`}
      ${failed && html`<p class="empty" role="alert">${t("feed.failed")}</p>`}
      ${cursor && html`<div ref=${end} class="feed-more" aria-hidden="true"></div>`}
      ${busy && html`<p class="loading" role="status">${t("feed.loading")}</p>`}
    </div>`;
}
