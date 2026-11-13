// Pages over the tabs: a page slides in from the end edge (the prototype's
// cubic-bezier(0.32, 0.72, 0, 1), 0.5 s) and goes back with the back button
// or a swipe from the start edge, which follows the finger. With "reduce
// motion" the slide is a fade (app.css). Mirrored in right-to-left.

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.js";
import { t } from "./i18n.js";
import { reducedMotion } from "./motion.js";
import { pop, useStore } from "./store.js";
import { Icon } from "./ui.js";

const EDGE = 24; // px from the start edge where a swipe back may begin
const LEAVE_MS = 500;

const rtl = () => document.documentElement.dir === "rtl";

function Page({ entry, pages, leaving }) {
  const el = useRef(null);
  const [shown, setShown] = useState(false);
  const swipe = useRef(null);
  const View = pages[entry.name];

  useEffect(() => {
    // One frame in the off-screen position, then the slide.
    const frame = requestAnimationFrame(() => setShown(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  function down(e) {
    const r = el.current.getBoundingClientRect();
    const fromStart = rtl() ? r.x + r.width - e.clientX : e.clientX - r.x;
    if (fromStart > EDGE || e.button > 0) return;
    swipe.current = { x: e.clientX, t: performance.now(), id: e.pointerId, width: r.width };
    el.current.setPointerCapture(e.pointerId);
    el.current.dataset.swiping = "true";
  }
  function move(e) {
    const s = swipe.current;
    if (!s || e.pointerId !== s.id) return;
    const dx = Math.max(0, (e.clientX - s.x) * (rtl() ? -1 : 1));
    s.dx = dx;
    el.current.style.setProperty("--swipe", `${dx}px`);
  }
  function up(e) {
    const s = swipe.current;
    swipe.current = null;
    if (!s) return;
    delete el.current.dataset.swiping;
    const speed = (s.dx || 0) / Math.max(1, performance.now() - s.t);
    if ((s.dx || 0) > s.width * 0.35 || speed > 0.6) {
      pop(); // leaves from where the finger let go
    } else {
      el.current.style.removeProperty("--swipe");
    }
    if (e.pointerId != null && el.current.hasPointerCapture?.(e.pointerId)) {
      el.current.releasePointerCapture(e.pointerId);
    }
  }

  const state = leaving ? "leaving" : shown ? "shown" : "entering";
  return html`<section
    ref=${el}
    class="page"
    data-state=${state}
    data-page=${entry.name}
    role="dialog"
    aria-modal="false"
    aria-label=${entry.props.title || ""}
    onPointerDown=${down}
    onPointerMove=${move}
    onPointerUp=${up}
    onPointerCancel=${up}
  >
    <header class="page-top">
      <button type="button" class="glass-icon" aria-label=${t("ui.back")} onClick=${pop}>
        <${Icon} name="back" size=${22} />
      </button>
    </header>
    <div class="scroller">${View ? html`<${View} ...${entry.props} />` : null}</div>
  </section>`;
}

export function Stack({ pages }) {
  const stack = useStore((s) => s.stack);
  const [leaving, setLeaving] = useState([]);
  const before = useRef(stack);

  // The pages popped since the last draw. They are drawn as leaving in this
  // very draw: found only afterwards (in the effect), a popped page was
  // gone for one frame and then made again to slide away, so it lost what
  // it showed and asked the server for it once more.
  const gone = before.current.filter((p) => !stack.includes(p) && !leaving.includes(p));

  useEffect(() => {
    before.current = stack;
    if (!gone.length) return undefined;
    setLeaving((now) => [...now, ...gone]);
    // Not cleared on the next change: a page popped while another leaves
    // still has to go.
    setTimeout(
      () => setLeaving((now) => now.filter((p) => !gone.includes(p))),
      reducedMotion() ? 0 : LEAVE_MS,
    );
    return undefined;
  }, [stack]);

  // One list, so a page keeps its element (and where a swipe left it) as it
  // moves from shown to leaving.
  const all = [
    ...stack.map((entry) => ({ entry, leaving: false })),
    ...[...leaving, ...gone].map((entry) => ({ entry, leaving: true })),
  ];
  return html`${all.map(
    ({ entry, leaving: going }) =>
      html`<${Page} key=${entry.key} entry=${entry} pages=${pages} leaving=${going} />`,
  )}`;
}
