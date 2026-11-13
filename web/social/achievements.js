// Achievements (E8), the prototype's card on Home and the sheet it opens
// (Feed.dc.html, "Achievements"): your points and the level they make, what
// you have done, every badge earned or still to earn, and how points are
// earned. All of it comes from the server (B7); nothing is counted here.
//
// Not in this build, with their backends: feedings ("Cats fed", "Snack
// Giver", "Feed a cat +10": B7c). Left out since nobody grades a cat (D9):
// "Cats graded", "Critic", "Grade a cat +1"; the tiles show encounters and
// posts in their place. A tap on a badge says how it is earned, which the
// prototype does not draw.

import { html, useEffect, useState } from "../vendor/preact-htm.js";
import { achievements as load } from "./data.js";
import { t, tRich } from "./i18n.js";
import { glass } from "./motion.js";
import { get, set, useStore } from "./store.js";
import { toast } from "./ui.js";

// The prototype's badge drawings; the last two are drawn for this build
// (the prototype shows them locked only).
const DRAWINGS = {
  "first-meow": html`<path d="M12 3l2.6 5.6 6 .7-4.5 4.1 1.3 6L12 16.4 6.6 19.4l1.3-6L3.4 9.3l6-.7z" />`,
  "night-owl": html`<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" />`,
  explorer: html`<path d="M9 4L3 6.5V20l6-2.5 6 2.5 6-2.5V4l-6 2.5z" /><path d="M9 4v13.5M15 6.5V20" />`,
  "name-giver": html`<path d="M4 7h16M4 12h10M4 17h7" /><path d="M17 14l1.5 3 3 .4-2.2 2 .6 3-2.9-1.6-2.9 1.6.6-3-2.2-2 3-.4z" />`,
  "deans-list": html`<path d="M2.5 9.5L12 5l9.5 4.5L12 14z" /><path d="M6.5 11.5v4.3c1.6 1.4 3.4 2.2 5.5 2.2s3.9-.8 5.5-2.2v-4.3M21.5 9.5v5" />`,
  "cat-whisperer": html`<path d="M6.2 9.2L5.4 4l4.5 2.6a8.6 8.6 0 0 1 4.2 0L18.6 4l-.8 5.2c1.2 1.2 1.8 2.6 1.8 4.1 0 3.6-3.4 6.2-7.6 6.2s-7.6-2.6-7.6-6.2c0-1.5.6-2.9 1.8-4.1z" /><path d="M9.5 12.8v.6M14.5 12.8v.6" />`,
};
const LOCK = html`<rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" />`;
const TROPHY = html`<path d="M8 4h8v5a4 4 0 0 1-8 0z" /><path d="M8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M9 20h6M10 17h4" />`;
const CAMERA = html`<path d="M4 8h3l1.8-2.5h6.4L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z" /><circle cx="12" cy="13.3" r="3.6" />`;
const RULE_DRAWINGS = { post: CAMERA };

const stroke = (drawing, size, width = 2) =>
  html`<svg width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width=${width} stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    ${drawing}
  </svg>`;

// A badge's disc: its own colour when earned (tokens.css), a dashed ring
// with a lock until then.
function BadgeDisc({ badge, size = 54 }) {
  return html`<span
    class=${badge.earned ? "badge-disc" : "badge-disc locked"}
    data-badge=${badge.id}
    aria-hidden="true"
    style=${{ "--size": `${size}px` }}
    >${stroke(badge.earned ? DRAWINGS[badge.id] : LOCK, Math.round(size * (badge.earned ? 0.48 : 0.41)))}</span
  >`;
}

// Asked for again whenever `shown` turns true.
function useAchievements(shown) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!shown) return undefined;
    let live = true;
    load()
      .then((answer) => {
        if (!live) return;
        setData(answer);
        setFailed(false);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [shown]);
  return { data, failed };
}

// Home's card: the points, how many badges, and the newest three of them.
export function AchievementsCard({ shown }) {
  const on = useStore((s) => s.me?.flags?.achievements);
  const { data } = useAchievements(shown && on);
  if (!on) return null;
  const earned = (data?.badges || []).filter((badge) => badge.earned);
  const newest = [...earned].sort((a, b) => (b.at || "").localeCompare(a.at || "")).slice(0, 3);
  return html`<button type="button" class="card achievements-card" ref=${glass} aria-haspopup="dialog" onClick=${() => set({ achievementsOpen: true })}>
    <span class="achievements-trophy" aria-hidden="true">${stroke(TROPHY, 26, 1.8)}</span>
    <span class="achievements-words">
      <span class="achievements-title">${t("ach.title")}</span>
      ${data &&
      html`<span class="achievements-sub"
        >${tRich("ach.points", { count: data.points }, "count")} · ${t("ach.badgeCount", { count: earned.length })}</span
      >`}
    </span>
    <span class="achievements-newest" aria-hidden="true">
      ${newest.map((badge) => html`<${BadgeDisc} key=${badge.id} badge=${badge} size=${30} />`)}
    </span>
  </button>`;
}

function Tile({ value, label }) {
  return html`<div class="ach-tile"><span class="ach-tile-value">${value}</span><span class="ach-tile-label">${label}</span></div>`;
}

// The sheet over the app, the prototype's island. One host in the frame,
// opened from the store, like the dialog and the menu.
export function AchievementsSheet() {
  const open = useStore((s) => !!s.achievementsOpen);
  const { data, failed } = useAchievements(open);
  const close = () => set({ achievementsOpen: false });

  // One listener for the life of the frame, asking the store whether the
  // sheet is open. Added when the sheet opened, it was not there yet for a
  // key pressed in the same instant: an effect runs after the paint.
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && get().achievementsOpen && close();
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);

  if (!open) return null;
  const level = data?.level;
  const span = level?.next == null ? 1 : level.next - level.from;
  const done = level?.next == null ? 1 : (data.points - level.from) / span;
  const earned = (data?.badges || []).filter((badge) => badge.earned).length;
  const say = (badge) =>
    toast(t(badge.earned ? "ach.badgeEarned" : "ach.badgeLocked", { how: t(`badge.${badge.id}.how`) }), 4000);

  return html`<button class="dim island-dim" aria-label=${t("ui.close")} tabindex="-1" onClick=${close}></button>
    <div class="island" role="dialog" aria-modal="true" aria-label=${t("ach.title")}>
      <div class="island-scroll">
        <div class="island-head">
          <h2>${t("ach.title")}</h2>
          <button type="button" class="island-close" ref=${glass} aria-label=${t("ui.close")} onClick=${close}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        ${!data && failed && html`<p class="empty" role="alert">${t("ach.failed")}</p>`}
        ${!data && !failed && html`<p class="loading" role="status">${t("feed.loading")}</p>`}
        ${data &&
        html`<div class="ach-top">
            <span class="ach-number">${t("ach.number", { count: data.points })}</span>
            <span class="ach-number-label">${t("ach.socialPoints", { count: data.points })}</span>
            <div class="ach-level">
              <div class="ach-level-line">
                <span class="ach-level-name">${t("ach.level", { level: level.level, name: t(`level.${level.level}`) })}</span>
                <span class="ach-level-next"
                  >${level.next == null ? t("ach.topLevel") : t("ach.toNext", { count: level.next - data.points, level: level.level + 1 })}</span
                >
              </div>
              <span class="ach-track" role="progressbar" aria-label=${t("ach.progress")} aria-valuemin="0" aria-valuemax="100" aria-valuenow=${Math.round(done * 100)}>
                <span style=${{ inlineSize: `${Math.round(done * 100)}%` }}></span>
              </span>
            </div>
          </div>

          <div class="ach-tiles">
            <${Tile} value=${data.counters.catsMet} label=${t("ach.catsMet", { count: data.counters.catsMet })} />
            <${Tile} value=${data.counters.encounters} label=${t("ach.encounters", { count: data.counters.encounters })} />
            <${Tile} value=${data.counters.posts} label=${t("ach.posts", { count: data.counters.posts })} />
          </div>

          <section class="ach-badges" aria-label=${t("ach.badges")}>
            <div class="ach-section-head">
              <h3>${t("ach.badges")}</h3>
              <span>${t("ach.badgesOf", { earned, count: data.badges.length })}</span>
            </div>
            <div class="ach-grid">
              ${data.badges.map(
                (badge) => html`<button
                  type="button"
                  key=${badge.id}
                  class=${badge.earned ? "ach-badge" : "ach-badge locked"}
                  data-badge=${badge.id}
                  data-earned=${String(badge.earned)}
                  onClick=${() => say(badge)}
                >
                  <${BadgeDisc} badge=${badge} />
                  <span class="ach-badge-name">${t(`badge.${badge.id}`)}</span>
                </button>`,
              )}
            </div>
          </section>

          <section class="ach-rules" aria-label=${t("ach.howPoints")}>
            <h3>${t("ach.howPoints")}</h3>
            ${data.rules.map(
              (rule) => html`<div class="ach-rule" key=${rule.id} data-rule=${rule.id}>
                <span class="ach-rule-icon" aria-hidden="true">${stroke(RULE_DRAWINGS[rule.id], 20, 1.9)}</span>
                <span class="ach-rule-words">
                  <span class="ach-rule-name">${t(`rule.${rule.id}`)}</span>
                  <span class="ach-rule-how">${t(`rule.${rule.id}.how`)}</span>
                </span>
                <span class="ach-rule-points">${t("ach.plus", { points: rule.points })}</span>
              </div>`,
            )}
          </section>`}
      </div>
    </div>`;
}
