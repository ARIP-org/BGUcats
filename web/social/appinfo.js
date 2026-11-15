// "App info" (Profile): what this app was doing on this phone, to read or
// to copy to whoever is fixing it (trail.js). Not in the prototype: it is
// here because a freeze on someone's phone cannot be seen from anywhere
// else. The text is the app's own, in English, as it was kept.

import { html, useState } from "../vendor/preact-htm.js";
import { t } from "./i18n.js";
import { appInfo, copyInfo } from "./trail.js";
import { toast } from "./ui.js";

// "Copy app info", wherever it is offered: says whether the phone copied.
export function CopyInfo({ quiet = false }) {
  const [copied, setCopied] = useState(null);
  const copy = async () => setCopied(await copyInfo());
  return html`
    <button class=${quiet ? "link-button quiet" : "glass-button"} type="button" data-copy-info onClick=${copy}>
      ${copied ? t("appInfo.copied") : t("appInfo.copy")}
    </button>
    ${copied === false && html`<p class="note" role="status">${t("appInfo.copyFailed")}</p>`}
  `;
}

export function AppInfo() {
  // As it was when the page opened: reading it must not add to it.
  const [text] = useState(appInfo);
  const copy = async () => toast(t((await copyInfo(text)) ? "appInfo.copied" : "appInfo.copyFailed"));
  return html`<div class="friends-page app-info-page">
    <h1 class="page-title">${t("appInfo.title")}</h1>
    <p class="page-lead">${t("appInfo.lead")}</p>
    <button class="glass-button" type="button" data-copy-info onClick=${copy}>${t("appInfo.copy")}</button>
    <pre class="app-info" dir="ltr" lang="en" tabindex="0" aria-label=${t("appInfo.title")}>${text}</pre>
  </div>`;
}
