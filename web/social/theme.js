// The four themes of web/tokens.css, by the names the prototype gives them,
// and the one the person chose, kept on this phone.

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

export function chooseTheme(theme) {
  applyTheme(theme);
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* chosen for this visit only */
  }
}
