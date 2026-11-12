// The feed's tab. E1 gives it its place in the frame; the posts arrive in E2.

import { html } from "../vendor/preact-htm.js";
import { t } from "./i18n.js";

export function Feed() {
  return html`<div class="tab-content">
    <h1 class="title">${t("feed.title")}</h1>
    <p class="lead">${t("feed.soon")}</p>
  </div>`;
}
