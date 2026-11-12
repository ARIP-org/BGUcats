// The Home tab, and the profile page it opens. E1 builds what the frame
// needs from them: the profile's settings (language, theme) and account
// actions (sign out, with the prototype's confirm). Home's cards, the
// profile's name, phone, achievements and posts come with E6.

import { logout } from "../lib/auth.js";
import { html } from "../vendor/preact-htm.js";
import { t } from "./i18n.js";
import { push, useStore } from "./store.js";
import { THEMES, chooseTheme } from "./theme.js";
import { Icon, confirm, openMenu } from "./ui.js";

const HOME = "/app.html";

export function Home() {
  const me = useStore((s) => s.me);
  return html`<div class="tab-content">
    <h1 class="title">${t("frame.hello", { name: me?.displayName || me?.username || "" })}</h1>
    <section class="group" aria-label=${t("home.you")}>
      <button type="button" class="row" onClick=${() => push("profile", { title: t("profile.title") })}>
        <span class="row-icon" aria-hidden="true"><${Icon} name="person" /></span>
        <span class="row-label">${t("profile.title")}</span>
        <span class="row-value">@${me?.username || ""}</span>
        <${Icon} name="chevron" size=${16} width=${2.2} />
      </button>
    </section>
    <p class="lead">${t("home.soon")}</p>
  </div>`;
}

export function Profile() {
  const me = useStore((s) => s.me);
  const theme = useStore((s) => s.theme);

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

  return html`<div class="tab-content">
    <h1 class="title">${me?.displayName || me?.username || ""}</h1>
    <p class="lead">@${me?.username || ""}</p>

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
      <button type="button" class="row" onClick=${signOut}>
        <span class="row-icon neutral" aria-hidden="true"><${Icon} name="signOut" /></span>
        <span class="row-label">${t("signOut.button")}</span>
      </button>
    </section>
  </div>`;
}
