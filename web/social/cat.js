// A cat's page (E4), the prototype's "Cat profile" in Feed.dc.html: the
// photos edge to edge, and over their foot a card with the name and where
// it came from, where the cat usually is, its description and its numbers;
// then the name poll (B4), and who posted it lately.
//
// The grade is a popularity grade the app works out (B7b, D9); a cat nobody
// met lately shows a dash, and with the `gpa` flag off there is no chip.
//
// Left out until its backend exists: the map button (E5).

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.js";
import { cat as loadCat, catPosts, names as loadNames, regionName, suggestName, takeVoteBack, voteFor } from "./data.js";
import { Avatar } from "./feed.js";
import { ago, oneDecimal, t } from "./i18n.js";
import { REFUSED, moved } from "./poll.js";
import { get } from "./store.js";
import { termsFirst } from "./terms.js";
import { toast } from "./ui.js";

// The cat's photos, one at a time, swiped sideways, with "2/5" on glass.
function Photos({ cat }) {
  const [at, setAt] = useState(0);
  const strip = useRef(null);
  const photos = cat.photos || [];
  const name = cat.name || t("cat.noName");
  if (!photos.length) return html`<div class="cat-photos empty" aria-hidden="true"></div>`;
  const onScroll = () => {
    const el = strip.current;
    setAt(Math.round(Math.abs(el.scrollLeft) / el.clientWidth));
  };
  return html`<div class="cat-photos">
    <div class="photo-strip" ref=${strip} onScroll=${photos.length > 1 ? onScroll : undefined} data-hscroll>
      ${photos.map(
        (photo, i) => html`<img src=${photo.medium} alt=${i ? "" : t("post.photoOf", { name })} loading=${i ? "lazy" : "eager"} decoding="async" />`,
      )}
    </div>
    ${photos.length > 1 &&
    html`<span class="photo-count" aria-label=${t("post.photoCount", { at: at + 1, count: photos.length })}>${at + 1}/${photos.length}</span>`}
  </div>`;
}

function Number({ value, label }) {
  return html`<div class="cat-number"><span class="cat-number-value">${value}</span><span class="cat-number-label">${label}</span></div>`;
}

// The name poll, the prototype's: every option with its votes as a bar, the
// leader marked, your choice ringed. A tap votes, a tap on your choice
// takes the vote back, and a name typed below joins the poll.
function Poll({ poll, change }) {
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

export function CatPage({ catId }) {
  const [cat, setCat] = useState(null);
  const [failed, setFailed] = useState(null);
  const [posts, setPosts] = useState(null);
  const [region, setRegion] = useState(null);
  const [poll, setPoll] = useState(null);
  useEffect(() => {
    let live = true;
    loadCat(catId)
      .then((answer) => {
        if (!live) return;
        setCat(answer.cat);
        regionName(answer.cat.regionId).then((name) => live && setRegion(name));
      })
      .catch((err) => live && setFailed(err.message));
    catPosts(catId)
      .then((answer) => live && setPosts(answer.cards))
      .catch(() => live && setPosts([]));
    loadNames(catId)
      .then((answer) => live && setPoll(answer))
      .catch(() => {}); // no poll shown; the rest of the page stands
    return () => {
      live = false;
    };
  }, [catId]);

  if (failed) return html`<p class="empty cat-wait" role="alert">${t("error.generic", { message: failed })}</p>`;
  if (!cat) return html`<p class="loading cat-wait" role="status">${t("feed.loading")}</p>`;
  // The poll's own answer is the newest word on the name: it counts the
  // vote just cast, where the cat's item follows a moment later.
  const name = poll ? poll.name : cat.name;
  const source = poll ? poll.nameSource : cat.nameSource;
  const leader = poll?.options.find((o) => o.leading);
  const named =
    source === "poll"
      ? leader
        ? t("cat.namedByVoteOf", { votes: leader.votes, total: poll.total })
        : t("cat.namedByVote")
      : t(source === "admin" ? "cat.namedByAdmins" : "cat.notNamed");
  return html`<div class="cat-page" data-cat=${cat.catId}>
    <${Photos} cat=${cat} />
    <div class="cat-body">
      <section class="card cat-card">
        <div class="cat-top">
          <div class="cat-head">
            <h1 class="cat-name">${name || t("cat.noName")}</h1>
            <span class="cat-named">${named}</span>
          </div>
          ${get().me?.flags?.gpa &&
          html`<div
            class="cat-gpa"
            role="img"
            aria-label=${cat.gpa == null ? t("cat.gpaNone") : t("cat.gpaLabel", { gpa: oneDecimal(cat.gpa) })}
          >
            <span class="cat-gpa-word">${t("cat.gpa")}</span>
            <span class="cat-gpa-value">${cat.gpa == null ? t("cat.never") : oneDecimal(cat.gpa)}</span>
            <span class="cat-gpa-of">${t("cat.gpaOf")}</span>
          </div>`}
        </div>
        ${region &&
        html`<span class="cat-place"
          ><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round" aria-hidden="true">
            <path d="M12 21s-6.5-6.2-6.5-11.2a6.5 6.5 0 0 1 13 0C18.5 14.8 12 21 12 21z" />
            <circle cx="12" cy="9.8" r="2.3" /></svg
          >${t("cat.usuallyNear", { place: region })}</span
        >`}
        ${cat.bio && html`<p class="cat-bio">${cat.bio}</p>`}
        <div class="cat-numbers">
          <${Number} value=${cat.posts} label=${t("cat.posts", { count: cat.posts })} />
          <${Number} value=${cat.likes} label=${t("cat.likes", { count: cat.likes })} />
          <${Number} value=${cat.lastSeenAt ? ago(cat.lastSeenAt) : t("cat.never")} label=${t("cat.lastSeen")} />
        </div>
        <p class="cat-met">${cat.met ? t("cat.met", { count: cat.met.encounters }) : t("cat.notMet")}</p>
      </section>

      ${poll && html`<${Poll} poll=${poll} change=${setPoll} />`}

      ${posts?.length > 0 &&
      html`<section class="card cat-posts" aria-label=${t("cat.recentPosts")}>
        <h2 class="card-title">${t("cat.recentPosts")}</h2>
        ${posts.map(
          (card) => html`<div class="cat-post" data-post=${card.postId}>
            <${Avatar} person=${card.author} size=${38} />
            <span class="cat-post-who">${card.author.displayName || card.author.username}</span>
            <span class="cat-post-when">${ago(card.createdAt)}</span>
          </div>`,
        )}
      </section>`}
    </div>
  </div>`;
}
