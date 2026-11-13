// What the places a person votes from share: the poll on a cat's page
// (cat.js) and after meeting the cat (scan.js), and a friends' vote card in
// the feed (feed.js).

import { html, useRef, useState } from "../vendor/preact-htm.js";
import { suggestName, takeVoteBack, voteFor } from "./data.js";
import { t } from "./i18n.js";
import { termsFirst } from "./terms.js";
import { toast } from "./ui.js";

// What a tap does to the poll before the server has answered: the caller's
// one vote moves to `key`, or is taken back (null). The server's answer
// replaces this a moment later; a refusal puts the poll back.
export function moved(poll, key) {
  const options = poll.options.map((o) => ({
    ...o,
    votes: o.votes - (o.mine ? 1 : 0) + (o.nameKey === key ? 1 : 0),
    mine: o.nameKey === key,
  }));
  const counted = options.filter((o) => !o.pending);
  return { ...poll, options, myVote: key, total: counted.reduce((sum, o) => sum + o.votes, 0) };
}

export const REFUSED = {
  not_accepted: "poll.notAccepted",
  try_again: "poll.tryAgain",
  rate_limited: "poll.slowDown",
};

// The name poll, the prototype's: every option with its votes as a bar, the
// leader marked, your choice ringed. A tap votes, a tap on your choice
// takes the vote back, and a name typed below joins the poll.
export function NamePoll({ poll, change }) {
  const [busy, setBusy] = useState(false);
  const field = useRef(null);

  // `send` answers with the poll as it now is. Shown at once as `meanwhile`.
  async function act(send, meanwhile) {
    if (busy) return false;
    const before = poll;
    setBusy(true);
    try {
      if (!(await termsFirst())) return false;
      if (meanwhile) change(meanwhile);
      change(await send());
      return true;
    } catch (err) {
      change(before);
      toast(REFUSED[err.code] ? t(REFUSED[err.code]) : t("error.generic", { message: err.message }));
      return false;
    } finally {
      setBusy(false);
    }
  }
  const choose = (option) =>
    option.mine
      ? act(() => takeVoteBack(poll.catId), moved(poll, null))
      : act(() => voteFor(poll.catId, option.nameKey), moved(poll, option.nameKey));
  const suggest = async (e) => {
    e.preventDefault();
    const name = field.current.value.replace(/\s+/g, " ").trim();
    if (!name) return;
    if (await act(() => suggestName(poll.catId, name))) {
      field.current.value = "";
      toast(t("poll.suggested"));
    }
  };

  const most = Math.max(1, ...poll.options.map((o) => o.votes));
  return html`<section class="card poll" aria-label=${t("poll.title")}>
    <div class="card-head">
      <h2 class="card-title">${t("poll.title")}</h2>
      <span class="card-count">${t("poll.votes", { count: poll.total })}</span>
    </div>
    <p class="poll-lead">${poll.locked ? t("poll.locked", { name: poll.locked }) : t("poll.lead")}</p>
    ${poll.options.length > 0 &&
    html`<div class="poll-options" role="radiogroup" aria-label=${t("poll.voteFor")}>
      ${poll.options.map(
        (o) => html`<button
          type="button"
          key=${o.nameKey}
          class="poll-option"
          role="radio"
          aria-checked=${String(o.mine)}
          data-name=${o.nameKey}
          disabled=${busy}
          onClick=${() => choose(o)}
        >
          <span class="poll-bar" aria-hidden="true" style=${{ inlineSize: `${Math.round((o.votes / most) * 100)}%` }}></span>
          <span class="poll-ring" aria-hidden="true"><span></span></span>
          <span class="poll-name">${o.name}</span>
          ${o.pending && html`<span class="badge">${t("poll.checking")}</span>`}
          ${o.leading && html`<span class="badge">${t("poll.leading")}</span>`}
          <span class="poll-count">${o.votes}</span>
        </button>`,
      )}
    </div>`}
    <form class="poll-suggest" onSubmit=${suggest}>
      <input ref=${field} name="suggestion" aria-label=${t("poll.suggest")} placeholder=${t("poll.suggest")} maxlength="24" autocomplete="off" autocapitalize="words" enterkeyhint="done" />
      <button type="submit" disabled=${busy}>${t("poll.suggestButton")}</button>
    </form>
  </section>`;
}
