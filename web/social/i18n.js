// Every string the member app shows comes from web/i18n/{lang}.json through
// t() (docs/app-plan/05-client.md, "Direction and language from the first
// line"). No sentence is built by joining pieces: "met {name}" is one string
// with a placeholder, because the order differs by language. A value that is
// an object holds plural forms, chosen with Intl.PluralRules by `count`.
// English is complete first; a language joins the menu only once a native
// speaker has read it (E10, O14).

const RIGHT_TO_LEFT = new Set(["he", "ar"]);

let lang = "en";
let strings = {};

// Relative to this module, so it works the same from the site and from the
// files packed inside the iPhone app.
export async function loadLanguage(code = "en") {
  const url = new URL(`../i18n/${code}.json`, import.meta.url);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`no strings for ${code} (${res.status})`);
  strings = await res.json();
  lang = code;
  const root = document.documentElement;
  root.lang = code;
  root.dir = RIGHT_TO_LEFT.has(code) ? "rtl" : "ltr";
}

export function t(key, values = {}) {
  let text = strings[key];
  if (text == null) return key; // a missing string shows its key, and a test fails
  if (typeof text === "object") {
    const form = new Intl.PluralRules(lang).select(Number(values.count ?? 0));
    text = text[form] ?? text.other;
  }
  return text.replace(/\{(\w+)\}/g, (whole, name) => {
    if (!(name in values)) return whole;
    const value = values[name];
    return typeof value === "number" ? new Intl.NumberFormat(lang).format(value) : String(value);
  });
}

export const language = () => lang;
