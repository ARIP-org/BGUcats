// The gallery (E4): every cat on campus, two columns of photos, the
// prototype's "Cat gallery" in Feed.dc.html. It opens from the feed's
// top-left button and from its search bar; a photo opens the cat's page.
// The list is sorted and searched on the phone (04-api.md, GET /cats):
// fifty cats is one answer.

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.js";
import { cats as loadCats } from "./data.js";
import { t } from "./i18n.js";
import { glass } from "./motion.js";
import { openScan } from "./scan.js";
import { get, push, set, useStore } from "./store.js";
import { openMenu } from "./ui.js";

// How the photos are cut, in turn, so the two columns do not line up: the
// prototype's heights. A cat keeps its shape while the list is as it is.
const SHAPES = ["3 / 4.4", "1 / 1", "3 / 4", "4 / 5", "3 / 4.8", "1 / 1", "4 / 5", "3 / 4.2"];

const byText = (a, b) => (a || "").localeCompare(b || "", undefined, { sensitivity: "base" });
const newest = (key) => (a, b) => (b[key] || "").localeCompare(a[key] || "");
// "Highest GPA" joins these with the grade itself (B7b).
export const SORTS = {
  seen: newest("lastSeenAt"),
  posts: (a, b) => b.posts - a.posts || newest("lastSeenAt")(a, b),
  newest: newest("firstSeenAt"),
  name: (a, b) => !a.name - !b.name || byText(a.name, b.name),
};

export function sorted(cats, sort, search) {
  const words = search.trim().toLowerCase();
  return cats
    .filter((cat) => !words || (cat.name || "").toLowerCase().includes(words))
    .sort(SORTS[sort] || SORTS.seen);
}

function Tile({ cat, shape }) {
  const name = cat.name || t("cat.noName");
  return html`<button
    type="button"
    class="gallery-tile"
    data-cat=${cat.catId}
    aria-label=${t("gallery.open", { name })}
    style=${{ aspectRatio: shape }}
    onClick=${() => push("cat", { catId: cat.catId, title: name })}
  >
    ${cat.cover ? html`<img src=${cat.cover.medium} alt=${name} loading="lazy" decoding="async" />` : html`<span class="gallery-name">${name}</span>`}
  </button>`;
}

export function Gallery({ search: focusSearch }) {
  const [cats, setCats] = useState(null);
  const [failed, setFailed] = useState(false);
  const [search, setSearch] = useState("");
  const sort = useStore((s) => s.gallerySort) || "seen";
  const field = useRef(null);

  useEffect(() => {
    let live = true;
    const show = (answer) => live && setCats(answer.cats);
    loadCats(() => loadCats().then(show))
      .then(show)
      .catch(() => live && setFailed(true));
    if (focusSearch) field.current?.focus();
    return () => {
      live = false;
    };
  }, []);

  const sortMenu = (e) =>
    openMenu(e.currentTarget, {
      label: t("gallery.sortBy"),
      items: Object.keys(SORTS).map((id) => ({
        label: t(`gallery.sort.${id}`),
        checked: id === sort,
        pick: () => set({ gallerySort: id }),
      })),
    });

  const shown = cats ? sorted(cats, sort, search) : [];
  // Dealt to one column, then the other: the order reads across, as the
  // eye does.
  const columns = [[], []];
  shown.forEach((cat, i) => columns[i % 2].push(html`<${Tile} key=${cat.catId} cat=${cat} shape=${SHAPES[i % SHAPES.length]} />`));

  return html`<div class="gallery-top">
      <label class="search gallery-search" ref=${glass}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
          <circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" />
        </svg>
        <input
          ref=${field}
          type="search"
          aria-label=${t("feed.search")}
          placeholder=${t("feed.search")}
          autocomplete="off"
          autocapitalize="none"
          enterkeyhint="search"
          value=${search}
          onInput=${(e) => setSearch(e.currentTarget.value)}
        />
      </label>
      <button type="button" class="glass-icon" ref=${glass} aria-label=${t("gallery.sort")} aria-haspopup="menu" onClick=${sortMenu}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5 7h14M8 12h8M10.5 17h3" /></svg>
      </button>
      <button type="button" class="glass-icon" ref=${glass} aria-label=${t("feed.newPost")} onClick=${() => openScan("post")}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
      </button>
    </div>
    <div class="gallery" data-sort=${sort}>
      ${columns.map((column) => html`<div class="gallery-column">${column}</div>`)}
    </div>
    ${cats && !shown.length && html`<p class="empty">${search.trim() ? t("gallery.noMatch", { search: search.trim() }) : t("gallery.empty")}</p>`}
    ${!cats && failed && html`<p class="empty" role="alert">${t("gallery.failed")}</p>`}
    ${!cats && !failed && html`<p class="loading" role="status">${t("feed.loading")}</p>`}`;
}

export const openGallery = (options = {}) => {
  if (get().stack.some((page) => page.name === "gallery")) return;
  push("gallery", { title: t("gallery.title"), ...options });
};
