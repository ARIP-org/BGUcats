// A cat's page (E4), the prototype's "Cat profile" in Feed.dc.html: the
// photos edge to edge, and over their foot a card with the name and where
// it came from, where the cat usually is, its description and its numbers;
// then who posted it lately.
//
// Left out until their backends exist, not drawn with made-up numbers: the
// grade (B7b), the name poll (B4), the map button (E5).

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.js";
import { cat as loadCat, catPosts, regionName } from "./data.js";
import { Avatar } from "./feed.js";
import { ago, t } from "./i18n.js";

// The cat's photos, one at a time, swiped sideways, with "2/5" on glass.
function Photos({ cat }) {
  const [at, setAt] = useState(0);
  const strip = useRef(null);
  const photos = cat.photos || [];
  const name = cat.name || t("cat.noName");
  if (!photos.length) return html`<div class="cat-photos empty" aria-hidden="true"></div>`;
  const onScroll = () => {
    const el = strip.current;
    setAt(Math.round(Math.abs(el.scrollLeft) / el.clientWidth));
  };
  return html`<div class="cat-photos">
    <div class="photo-strip" ref=${strip} onScroll=${photos.length > 1 ? onScroll : undefined} data-hscroll>
      ${photos.map(
        (photo, i) => html`<img src=${photo.medium} alt=${i ? "" : t("post.photoOf", { name })} loading=${i ? "lazy" : "eager"} decoding="async" />`,
      )}
    </div>
    ${photos.length > 1 &&
    html`<span class="photo-count" aria-label=${t("post.photoCount", { at: at + 1, count: photos.length })}>${at + 1}/${photos.length}</span>`}
  </div>`;
}

function Number({ value, label }) {
  return html`<div class="cat-number"><span class="cat-number-value">${value}</span><span class="cat-number-label">${label}</span></div>`;
}

export function CatPage({ catId }) {
  const [cat, setCat] = useState(null);
  const [failed, setFailed] = useState(null);
  const [posts, setPosts] = useState(null);
  const [region, setRegion] = useState(null);
  useEffect(() => {
    let live = true;
    loadCat(catId)
      .then((answer) => {
        if (!live) return;
        setCat(answer.cat);
        regionName(answer.cat.regionId).then((name) => live && setRegion(name));
      })
      .catch((err) => live && setFailed(err.message));
    catPosts(catId)
      .then((answer) => live && setPosts(answer.cards))
      .catch(() => live && setPosts([]));
    return () => {
      live = false;
    };
  }, [catId]);

  if (failed) return html`<p class="empty cat-wait" role="alert">${t("error.generic", { message: failed })}</p>`;
  if (!cat) return html`<p class="loading cat-wait" role="status">${t("feed.loading")}</p>`;
  const named = { poll: "cat.namedByVote", admin: "cat.namedByAdmins" }[cat.nameSource] || "cat.notNamed";
  return html`<div class="cat-page" data-cat=${cat.catId}>
    <${Photos} cat=${cat} />
    <div class="cat-body">
      <section class="card cat-card">
        <div class="cat-head">
          <h1 class="cat-name">${cat.name || t("cat.noName")}</h1>
          <span class="cat-named">${t(named)}</span>
        </div>
        ${region &&
        html`<span class="cat-place"
          ><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round" aria-hidden="true">
            <path d="M12 21s-6.5-6.2-6.5-11.2a6.5 6.5 0 0 1 13 0C18.5 14.8 12 21 12 21z" />
            <circle cx="12" cy="9.8" r="2.3" /></svg
          >${t("cat.usuallyNear", { place: region })}</span
        >`}
        ${cat.bio && html`<p class="cat-bio">${cat.bio}</p>`}
        <div class="cat-numbers">
          <${Number} value=${cat.posts} label=${t("cat.posts", { count: cat.posts })} />
          <${Number} value=${cat.likes} label=${t("cat.likes", { count: cat.likes })} />
          <${Number} value=${cat.lastSeenAt ? ago(cat.lastSeenAt) : t("cat.never")} label=${t("cat.lastSeen")} />
        </div>
        <p class="cat-met">${cat.met ? t("cat.met", { count: cat.met.encounters }) : t("cat.notMet")}</p>
      </section>

      ${posts?.length > 0 &&
      html`<section class="card cat-posts" aria-label=${t("cat.recentPosts")}>
        <h2 class="card-title">${t("cat.recentPosts")}</h2>
        ${posts.map(
          (card) => html`<div class="cat-post" data-post=${card.postId}>
            <${Avatar} person=${card.author} size=${38} />
            <span class="cat-post-who">${card.author.displayName || card.author.username}</span>
            <span class="cat-post-when">${ago(card.createdAt)}</span>
          </div>`,
        )}
      </section>`}
    </div>
  </div>`;
}
