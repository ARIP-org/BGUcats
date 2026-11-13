// The pieces every screen shares, ported from the prototype: icons, the
// toast, the confirm dialog and the menu. Each overlay is one host in the
// frame (Overlays), driven from the store, so any screen can call toast(),
// confirm() or openMenu() without owning markup for it.

import { html, useEffect, useRef } from "../vendor/preact-htm.js";
import { t } from "./i18n.js";
import { get, set, useStore } from "./store.js";

// ------------------------------------------------------------------ icons

// The prototype's stroke icons. `mirror` ones point, and turn round in
// right-to-left (app.css, .mirror).
const PATHS = {
  cat: html`<path d="M6 11.2C6 10 6.9 9.5 8.3 9.5H15.4L15.9 6.6 16.7 3.9 18.4 5.9H19.6L21.3 3.9 21.7 7C21.7 9.2 20.5 10.5 18.7 10.8V20H17.1V14.6H8.6V20H7V13.6C6.4 13.1 6 12.3 6 11.2Z" /><path d="M6.2 11C3.8 10.6 2.9 8.3 3.6 5.4" />`,
  camera: html`<path d="M4 8h3l1.8-2.5h6.4L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z" /><circle cx="12" cy="13.3" r="3.6" />`,
  home: html`<path d="M4.5 20V10.6c0-.5.2-.9.6-1.2l6.2-5a1.2 1.2 0 0 1 1.4 0l6.2 5c.4.3.6.7.6 1.2V20h-5.2v-4.3a2.3 2.3 0 0 0-4.6 0V20z" />`,
  back: html`<path d="M15 5l-7 7 7 7" />`,
  chevron: html`<path d="M9 5l7 7-7 7" />`,
  updown: html`<path d="M8 9l4-4 4 4M8 15l4 4 4-4" />`,
  check: html`<path d="M5 12.5l4.5 4.5L19 7.5" />`,
  person: html`<circle cx="12" cy="8" r="3.6" /><path d="M5 20a7 7 0 0 1 14 0" />`,
  globe: html`<circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c2.4 2.6 3.4 5.4 3.4 8.5s-1 5.9-3.4 8.5c-2.4-2.6-3.4-5.4-3.4-8.5s1-5.9 3.4-8.5z" />`,
  theme: html`<circle cx="12" cy="12" r="8.5" /><path d="M12 3.5v17a8.5 8.5 0 0 0 0-17z" fill="currentColor" />`,
  friends: html`<circle cx="8.3" cy="4.6" r="2.5" /><circle cx="15.7" cy="4.6" r="2.5" /><path d="M5 21v-9.3A2.7 2.7 0 0 1 7.7 9h10.1a1.9 1.9 0 0 1 .5 3.7l-2.8.8V21" /><path d="M8.5 14.5V21M11.8 13.8V21" />`,
  at: html`<circle cx="12" cy="12" r="3.6" /><path d="M15.6 8.6v4.6a2.4 2.4 0 0 0 4.9 0V12a8.5 8.5 0 1 0-3.6 7" />`,
  pencil: html`<path d="M4 20h4L19 9l-4-4L4 16z" /><path d="M13 7l4 4" />`,
  library: html`<rect x="3.5" y="4.5" width="17" height="15" rx="2.5" /><circle cx="9" cy="10" r="1.6" /><path d="M20.5 16l-5-5-8 8.5" />`,
  trash: html`<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3" />`,
  link: html`<path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1" /><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1" />`,
  share: html`<path d="M12 15V3M7.5 7.5L12 3l4.5 4.5M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7" />`,
  personPlus: html`<circle cx="10" cy="8" r="3.5" /><path d="M3.5 20a6.5 6.5 0 0 1 13 0M18.5 8v6M15.5 11h6" />`,
  personMinus: html`<circle cx="10" cy="8" r="3.5" /><path d="M3.5 20a6.5 6.5 0 0 1 13 0M16 11h5" />`,
  signOut: html`<path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4" /><path d="M10 8l-4 4 4 4M6 12h10" />`,
};
const MIRRORED = new Set(["back", "chevron", "signOut"]);

export function Icon({ name, size = 18, width = 2 }) {
  return html`<svg
    class=${MIRRORED.has(name) ? "icon mirror" : "icon"}
    width=${size}
    height=${size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width=${width}
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    ${PATHS[name]}
  </svg>`;
}

// ------------------------------------------------------------------ toast

let toastTimer = null;

// `ms`: how long it stays; longer for a sentence someone has to read.
export function toast(text, ms = 2400) {
  clearTimeout(toastTimer);
  set({ toast: { text, on: true } });
  toastTimer = setTimeout(() => set({ toast: { ...get().toast, on: false } }), ms);
}

function Toast() {
  const state = useStore((s) => s.toast);
  return html`<div class=${`toast${state?.on ? " on" : ""}`} role="status" aria-live="polite">
    ${state?.text &&
    html`<span class="toast-tick" aria-hidden="true"><${Icon} name="check" size=${15} width=${3} /></span>${state.text}`}
  </div>`;
}

// ------------------------------------------------------------------ confirm

// confirm({ title, body, button, danger }) -> Promise<boolean>
export function confirm(options) {
  return new Promise((resolve) => set({ dialog: { ...options, resolve } }));
}

function Dialog() {
  const dialog = useStore((s) => s.dialog);
  const first = useRef(null);
  const close = (answer) => {
    dialog?.resolve(answer);
    set({ dialog: null });
  };
  useEffect(() => {
    if (!dialog) return undefined;
    first.current?.focus();
    const onKey = (e) => e.key === "Escape" && close(false);
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [dialog]);
  if (!dialog) return null;
  return html`
    <button class="dim" aria-label=${t("ui.cancel")} tabindex="-1" onClick=${() => close(false)}></button>
    <div class="dialog" role="alertdialog" aria-modal="true" aria-labelledby="dialog-title" aria-describedby="dialog-body">
      <h2 id="dialog-title">${dialog.title}</h2>
      <p id="dialog-body">${dialog.body}</p>
      <div class="dialog-buttons">
        <button ref=${first} type="button" class="dialog-cancel" onClick=${() => close(false)}>${t("ui.cancel")}</button>
        <button type="button" class=${dialog.danger ? "dialog-go danger" : "dialog-go"} onClick=${() => close(true)}>
          ${dialog.button}
        </button>
      </div>
    </div>
  `;
}

// ------------------------------------------------------------------ menu

// openMenu(anchorElement, { label, items: [{ label, checked, swatch, pick }] })
// A popover under the button that opened it, at its end edge.
export function openMenu(anchor, menu) {
  const r = anchor.getBoundingClientRect();
  const rtl = document.documentElement.dir === "rtl";
  set({
    menu: {
      ...menu,
      anchor,
      top: r.bottom + 8,
      end: rtl ? r.x : innerWidth - (r.x + r.width),
    },
  });
}

export const closeMenu = () => {
  get().menu?.anchor?.focus?.();
  set({ menu: null });
};

function Menu() {
  const menu = useStore((s) => s.menu);
  const box = useRef(null);
  useEffect(() => {
    if (!menu) return undefined;
    box.current?.querySelector("[aria-checked=true], button")?.focus();
    const onKey = (e) => {
      if (e.key === "Escape") closeMenu();
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        const items = [...box.current.querySelectorAll("button")];
        const at = items.indexOf(document.activeElement);
        const next = (at + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
        items[next]?.focus();
        e.preventDefault();
      }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [menu]);
  if (!menu) return null;
  const pick = (item) => {
    closeMenu();
    item.pick();
  };
  return html`
    <button class="menu-away" aria-label=${t("ui.close")} tabindex="-1" onClick=${closeMenu}></button>
    <div
      ref=${box}
      class="menu"
      role="menu"
      aria-label=${menu.label}
      style=${{ insetBlockStart: `${menu.top}px`, insetInlineEnd: `${Math.max(16, menu.end)}px` }}
    >
      ${menu.items.map(
        (item) => html`<button
          type="button"
          class=${item.danger ? "danger" : undefined}
          role=${item.checked == null ? "menuitem" : "menuitemradio"}
          aria-checked=${item.checked == null ? undefined : String(item.checked)}
          onClick=${() => pick(item)}
        >
          <span class="menu-lead" aria-hidden="true">
            ${item.swatch && html`<span class="swatch" data-swatch=${item.swatch}></span>`}
            ${item.icon && html`<${Icon} name=${item.icon} size=${21} width=${1.8} />`}
          </span>
          <span class="menu-label">${item.label}</span>
          ${item.checked && html`<span class="menu-check"><${Icon} name="check" width=${2.6} /></span>`}
        </button>`,
      )}
    </div>
  `;
}

export function Overlays() {
  return html`<${Menu} /><${Dialog} /><${Toast} />`;
}
