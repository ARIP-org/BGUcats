// Reporting (B8b): a post, a person or a name that should not be here, with
// a reason from a short list and, if the person wants, a line of their own.
// Apple's rule 1.2 asks for it of any app with content people make. The
// prototype has "Report" in a friend's menu and no sheet for it; this one
// is drawn like the app's other sheets.
//
// The answer is always the same: nobody learns what others reported.

import { ulid } from "../outbox.js";
import { html, useEffect, useRef, useState } from "../vendor/preact-htm.js";
import { sendReport } from "./data.js";
import { t } from "./i18n.js";
import { get, set, useStore } from "./store.js";
import { toast } from "./ui.js";

// The server's list (src/common/reports.py), in the order shown.
export const REASONS = ["spam", "offensive", "harassment", "privacy", "not_cat", "other"];

// openReport({ type: "post" | "user" | "name", id, name }): `name` is what
// the sheet calls the thing ("Maya", "Maya's post").
export const openReport = (target) => set({ report: target });

export function ReportSheet() {
  const target = useStore((s) => s.report);
  const [reason, setReason] = useState(null);
  const [busy, setBusy] = useState(false);
  const note = useRef(null);
  const close = () => set({ report: null });

  useEffect(() => {
    setReason(null);
  }, [target]);
  // One listener for the life of the frame (see achievements.js).
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && get().report && close();
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);

  if (!target) return null;
  const send = async (e) => {
    e.preventDefault();
    if (!reason || busy) return;
    setBusy(true);
    try {
      await sendReport({
        reportId: ulid(),
        targetType: target.type,
        targetId: target.id,
        reason,
        note: note.current.value.trim() || undefined,
      });
      close();
      toast(t("report.sent"), 4000);
    } catch (err) {
      toast(err.code === "rate_limited" ? t("poll.slowDown") : t("error.generic", { message: err.message }), 4000);
    } finally {
      setBusy(false);
    }
  };

  return html`<button class="dim" aria-label=${t("ui.close")} tabindex="-1" onClick=${close}></button>
    <form class="report-sheet" role="dialog" aria-modal="true" aria-label=${t("report.title", { name: target.name })} onSubmit=${send}>
      <h2>${t("report.title", { name: target.name })}</h2>
      <p>${t("report.lead")}</p>
      <div class="report-reasons" role="radiogroup" aria-label=${t("report.why")}>
        ${REASONS.map(
          (id) => html`<button type="button" key=${id} role="radio" class="report-reason" aria-checked=${String(reason === id)} data-reason=${id} onClick=${() => setReason(id)}>
            <span class="poll-ring" aria-hidden="true"><span></span></span>
            ${t(`report.reason.${id}`)}
          </button>`,
        )}
      </div>
      <textarea ref=${note} class="report-note" rows="2" maxlength="280" aria-label=${t("report.note")} placeholder=${t("report.note")}></textarea>
      <div class="dialog-buttons">
        <button type="button" class="dialog-cancel" onClick=${close}>${t("ui.cancel")}</button>
        <button type="submit" class="dialog-go danger" disabled=${!reason || busy}>${t("report.send")}</button>
      </div>
    </form>`;
}
