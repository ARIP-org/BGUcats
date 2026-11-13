// The four themes of web/tokens.css, by the names the prototype gives them,
// and the one the person chose, kept on this phone.

import { updateMe } from "./data.js";
import { get, set } from "./store.js";

export const THEMES = ["bgu-light", "bgu-dark", "cats-light", "cats-dark"];
const KEY = "bgucats.theme";

export function savedTheme() {
  try {
    const saved = localStorage.getItem(KEY);
    if (THEMES.includes(saved)) return saved;
  } catch {
    /* no storage: the default */
  }
  return "bgu-dark"; // the prototype's
}

export function applyTheme(theme) {
  const root = document.documentElement;
  root.dataset.theme = theme;
  // The status bar and the browser's chrome follow the page's background.
  const bg = getComputedStyle(root).getPropertyValue("--bg").trim();
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg);
  if (get().theme !== theme) set({ theme });
}

function keep(theme) {
  applyTheme(theme);
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* chosen for this visit only */
  }
}

// Chosen in the profile: kept on this phone, and with the account, so the
// person's next phone opens in it too. The account's copy is a courtesy:
// if it cannot be saved now, this phone still has it.
export function chooseTheme(theme) {
  keep(theme);
  updateMe({ theme }).catch(() => {});
}

// At sign-in: the theme the account remembers, if this phone has another.
export function adoptTheme(theme) {
  if (THEMES.includes(theme) && theme !== get().theme) keep(theme);
}
