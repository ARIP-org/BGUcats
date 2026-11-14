// Every string the member app shows comes from web/i18n/{lang}.json through
// t() (docs/app-plan/05-client.md, "Direction and language from the first
// line"). No sentence is built by joining pieces: "met {name}" is one string
// with a placeholder, because the order differs by language. A value that is
// an object holds plural forms, chosen with Intl.PluralRules by `count`.
// English is complete first. The others are drafts (E10) until a native
// speaker has read them (O14); which ones the profile offers is the
// account's setting (`flags.languages`, infra/main/variables.tf).

import { html } from "../vendor/preact-htm.js";

const RIGHT_TO_LEFT = new Set(["he", "ar"]);

// Each language by its own name: the same whatever language is showing.
export const LANGUAGES = { en: "English", he: "עברית", ru: "Русский", ar: "العربية" };
const KEY = "bgucats.language";

let lang = "en";
let strings = {};

// The words of a start that failed, in English, for when the strings file
// is the thing that could not be had. tests/web/test_languages.py holds
// them to en.json.
const BUILT_IN = {
  "start.failedTitle": "The app could not start",
  "start.tooLong": "It took too long.",
  "start.step.files": "It stopped while loading its own files.",
  "start.step.strings": "It stopped while loading its words.",
  "start.step.settings": "It stopped while loading its settings.",
  "start.step.sign-in": "It stopped while checking your sign-in.",
  "start.step.account": "It stopped while reading your account.",
  "start.reset": "Reset the app on this phone",
  "start.resetNote": "Resetting fetches the app again. You stay signed in, and photos still waiting to upload are kept.",
  "ui.tryAgain": "Try again",
  "signOut.button": "Sign out"
};

// The language this phone was last put in, so the sign-in screen is in it
// too. English if none, or if it is no language of the app's.
export function savedLanguage() {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved in LANGUAGES) return saved;
  } catch {
    /* no storage: English */
  }
  return "en";
}

export function keepLanguage(code) {
  try {
    localStorage.setItem(KEY, code);
  } catch {
    /* for this visit only */
  }
}

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

// The string for `key` in the right plural form, its placeholders untouched.
function template(key, values) {
  const text = strings[key] ?? BUILT_IN[key];
  if (text == null || typeof text !== "object") return text;
  const form = new Intl.PluralRules(lang).select(Number(values.count ?? 0));
  return text[form] ?? text.other;
}

const shown = (value) =>
  typeof value === "number" ? new Intl.NumberFormat(lang).format(value) : String(value);

export function t(key, values = {}) {
  const text = template(key, values);
  if (text == null) return key; // a missing string shows its key, and a test fails
  return text.replace(/\{(\w+)\}/g, (whole, name) => (name in values ? shown(values[name]) : whole));
}

// The same string with one of its values set in bold ("found **18** cats"):
// markup, so the sentence stays one string whatever the word order.
export function tRich(key, values, strong) {
  const text = template(key, values);
  if (text == null) return key;
  const fill = (part) => part.replace(/\{(\w+)\}/g, (whole, name) => (name in values ? shown(values[name]) : whole));
  // A plural form may say the number in words ("one cat", "two cats" in
  // Hebrew or Arabic) and leave the placeholder out: then nothing is bold.
  if (!text.includes(`{${strong}}`)) return fill(text);
  const [before, after = ""] = text.split(`{${strong}}`);
  return html`${fill(before)}<b>${shown(values[strong])}</b>${fill(after)}`;
}

// The same, with several values as markup: `marks` gives a class to each
// value that gets one ("{who} voted to call {cat} “{name}”").
export function tMarked(key, values, marks) {
  const text = template(key, values);
  if (text == null) return key;
  return text.split(/(\{\w+\})/).map((part) => {
    const name = /^\{(\w+)\}$/.exec(part)?.[1];
    if (!name || !(name in values)) return part;
    const value = shown(values[name]);
    return name in marks ? html`<span class=${marks[name]}>${value}</span>` : value;
  });
}

export const language = () => lang;

// "3.9", "4.0": a grade always shows its decimal.
export const oneDecimal = (value) =>
  new Intl.NumberFormat(lang, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value);

// "Nov 2026" and "Nov 10", as the language writes them.
const dated = (iso, options) => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat(lang, options).format(date);
};
export const monthYear = (iso) => dated(iso, { month: "short", year: "numeric" });
export const dayMonth = (iso) => dated(iso, { month: "short", day: "numeric" });

// "Just now", "5 min ago", "yesterday": a time as a person says it.
const UNITS = [
  ["year", 31536000],
  ["month", 2592000],
  ["week", 604800],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
];

export function ago(iso, now = Date.now()) {
  const seconds = (Date.parse(iso) - now) / 1000;
  if (!Number.isFinite(seconds)) return "";
  if (Math.abs(seconds) < 60) return t("time.justNow");
  const format = new Intl.RelativeTimeFormat(lang, { numeric: "auto", style: "short" });
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  }
  return "";
}
