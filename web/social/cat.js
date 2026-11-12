// A cat's page, as far as the feed needs it (E2): its photo, name,
// description, and how often you met it. E4 gives it the gallery's full
// page: more photos, the poll, the map.

import { html, useEffect, useState } from "../vendor/preact-htm.js";
import { cat as loadCat } from "./data.js";
import { t } from "./i18n.js";

export function CatPage({ catId }) {
  const [cat, setCat] = useState(null);
  const [failed, setFailed] = useState(null);
  useEffect(() => {
    let live = true;
    loadCat(catId)
      .then((answer) => live && setCat(answer.cat))
      .catch((err) => live && setFailed(err.message));
    return () => {
      live = false;
    };
  }, [catId]);

  if (failed) return html`<p class="empty" role="alert">${t("error.generic", { message: failed })}</p>`;
  if (!cat) return html`<p class="loading" role="status">${t("feed.loading")}</p>`;
  const [first, ...more] = cat.photos || [];
  return html`<div class="tab-content cat-page" data-cat=${cat.catId}>
    ${first && html`<img class="cat-hero" src=${first.medium} alt=${t("post.photoOf", { name: cat.name || t("cat.noName") })} />`}
    <h1 class="title">${cat.name || t("cat.noName")}</h1>
    ${cat.bio && html`<p class="lead">${cat.bio}</p>`}
    <p class="cat-met">${cat.met ? t("cat.met", { count: cat.met.encounters }) : t("cat.notMet")}</p>
    ${more.length > 0 &&
    html`<div class="cat-grid">
      ${more.map((photo) => html`<img src=${photo.thumb} alt="" loading="lazy" />`)}
    </div>`}
  </div>`;
}
