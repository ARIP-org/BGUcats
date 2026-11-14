// Feeding (B7c, D10): "I fed this cat" on a cat's page, and when the cat
// was last fed, as people logged it. The campus has set feeding spots; a
// log may name one.
//
// The prototype has no control for this (G6): its achievements only say
// "Feed a cat: log food or water you left out, +10". The card and the
// sheet are drawn like the app's others.

import { ulid } from "../outbox.js";
import { html, useEffect, useState } from "../vendor/preact-htm.js";
import { feedingSpots, logFeeding } from "./data.js";
import { ago, t } from "./i18n.js";
import { get, set, useStore } from "./store.js";
import { termsFirst } from "./terms.js";
import { toast } from "./ui.js";

const BOWL = html`<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M4 13h16a8 6 0 0 1-16 0z" /><path d="M9 9.5c0-1.4 1-1.9 1-3.3M14 9.5c0-1.4 1-1.9 1-3.3" />
</svg>`;

const REFUSED = { too_soon: "fed.tooSoon", rate_limited: "fed.enoughToday" };

// `fed(at)` is told the cat's new "last fed".
export const openFeeding = (cat, name, fed) => set({ feeding: { cat, name, fed } });

// "Last fed 3 hr. ago". The first minute has its own words: the app's
// "Just now" is a line of its own, not the end of a sentence.
function lastFed(at) {
  if (!at) return t("fed.never");
  return Math.abs(Date.now() - Date.parse(at)) < 60000 ? t("fed.lastNow") : t("fed.last", { when: ago(at) });
}

// The card on a cat's page. Nothing with the `feeding` flag off.
export function FedCard({ cat, name, onFed }) {
  const on = useStore((s) => s.me?.flags?.feeding);
  if (!on) return null;
  return html`<section class="card fed-card" aria-label=${t("fed.title")}>
    <span class="fed-icon" aria-hidden="true">${BOWL}</span>
    <span class="fed-words">
      <span class="fed-last">${lastFed(cat.lastFedAt)}</span>
      ${cat.lastFedAt && html`<span class="fed-by">${t("fed.by")}</span>`}
    </span>
    <button type="button" class="fed-button" aria-haspopup="dialog" onClick=${() => openFeeding(cat, name, onFed)}>${t("fed.log")}</button>
  </section>`;
}

// One host in the frame, opened from the store, like the report sheet.
export function FeedingSheet() {
  const feeding = useStore((s) => s.feeding);
  const [spots, setSpots] = useState([]);
  const [spot, setSpot] = useState(null);
  const [busy, setBusy] = useState(false);
  const close = () => set({ feeding: null });

  useEffect(() => {
    setSpot(null);
    if (feeding) feedingSpots().then(setSpots, () => setSpots([]));
  }, [feeding]);
  // One listener for the life of the frame (see achievements.js).
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && get().feeding && close();
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);

  if (!feeding) return null;
  const { cat, name } = feeding;
  // The spots where this cat usually is come first.
  const near = [...spots.filter((s) => s.regionId === cat.regionId), ...spots.filter((s) => s.regionId !== cat.regionId)];
  const send = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      if (!(await termsFirst())) return;
      const answer = await logFeeding(cat.catId, { feedingId: ulid(), spotId: spot || undefined });
      feeding.fed?.(answer.lastFedAt);
      close();
      toast(t("fed.done", { name }), 4000);
    } catch (err) {
      toast(REFUSED[err.code] ? t(REFUSED[err.code]) : t("error.generic", { message: err.message }), 4000);
    } finally {
      setBusy(false);
    }
  };

  return html`<button class="dim" aria-label=${t("ui.close")} tabindex="-1" onClick=${close}></button>
    <form class="report-sheet feeding-sheet" role="dialog" aria-modal="true" aria-label=${t("fed.ask", { name })} onSubmit=${send}>
      <h2>${t("fed.ask", { name })}</h2>
      <p>${t("fed.lead")}</p>
      ${near.length > 0 &&
      html`<fieldset class="chips">
        <legend>${t("fed.where")} <span class="optional">${t("scan.optional")}</span></legend>
        ${near.map(
          (s) =>
            html`<button type="button" class="chip" key=${s.id} data-spot=${s.id} aria-pressed=${String(spot === s.id)} onClick=${() => setSpot(spot === s.id ? null : s.id)}>
              ${s.names.en}
            </button>`,
        )}
      </fieldset>`}
      <div class="dialog-buttons">
        <button type="button" class="dialog-cancel" onClick=${close}>${t("ui.cancel")}</button>
        <button type="submit" class="dialog-go" disabled=${busy}>${t("fed.send")}</button>
      </div>
    </form>`;
}
