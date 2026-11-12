// The tab bar (the prototype's <nav aria-label="Main">): Cats, Scan a cat,
// Home, on glass, with a lens behind the open tab. It shrinks to a round
// button with the open tab's icon while the page scrolls down, and comes
// back on scrolling up or a tap. The lens can be dragged to another tab.
// Positions are in percent of the bar and logical (inset-inline-start), so
// it flows at any width and mirrors in right-to-left.

import { html, useRef } from "../vendor/preact-htm.js";
import { t } from "./i18n.js";
import { reducedMotion } from "./motion.js";
import { get, set, showTab, useStore } from "./store.js";
import { Icon } from "./ui.js";

const TABS = [
  { id: "feed", icon: "cat", label: "tab.cats" },
  { id: "scan", icon: "camera", label: "tab.scan" },
  { id: "home", icon: "home", label: "tab.home" },
];

// Turns and hops of the icons, as the prototype's spin() and wagTail().
function hop(button) {
  if (reducedMotion()) return;
  button?.querySelector("svg")?.animate(
    [
      { transform: "perspective(90px) translateY(0) rotateY(0)" },
      { transform: "perspective(90px) translateY(-8px) rotateY(180deg)", offset: 0.35 },
      { transform: "perspective(90px) translateY(0) rotateY(360deg)" },
    ],
    { duration: 800, easing: "cubic-bezier(0.25, 1.2, 0.4, 1)" },
  );
}

export function TabBar({ onScan }) {
  const tab = useStore((s) => s.tab);
  const collapsed = useStore((s) => s.collapsed);
  const nav = useRef(null);
  const drag = useRef(null);
  const active = TABS.findIndex((x) => x.id === tab);

  function choose(index, button) {
    const chosen = TABS[index];
    hop(button);
    if (chosen.id === "scan") {
      onScan();
      return;
    }
    if (chosen.id === get().tab && !get().stack.length) {
      // The open tab again: back to the top, as on iOS.
      document.querySelector(".tab-page.shown .scroller")?.scrollTo({
        top: 0,
        behavior: reducedMotion() ? "auto" : "smooth",
      });
      return;
    }
    showTab(chosen.id);
  }

  // Dragging the lens: it follows the finger and lands on the nearest tab.
  function indexAt(clientX) {
    const r = nav.current.getBoundingClientRect();
    let x = (clientX - r.x) / r.width;
    if (document.documentElement.dir === "rtl") x = 1 - x;
    return Math.max(0, Math.min(TABS.length - 1, Math.floor(x * TABS.length)));
  }
  function down(e) {
    if (collapsed || e.button > 0) return;
    drag.current = { x: e.clientX, moved: false, id: e.pointerId };
  }
  function move(e) {
    const d = drag.current;
    if (!d || e.pointerId !== d.id) return;
    if (!d.moved && Math.abs(e.clientX - d.x) < 8) return;
    if (!d.moved) nav.current.setPointerCapture(e.pointerId);
    d.moved = true;
    const r = nav.current.getBoundingClientRect();
    let x = (e.clientX - r.x) / r.width;
    if (document.documentElement.dir === "rtl") x = 1 - x;
    nav.current.style.setProperty("--drag", Math.max(0, Math.min(1, x)).toFixed(4));
    nav.current.dataset.dragging = "true";
    nav.current.dataset.over = String(indexAt(e.clientX));
  }
  function up(e) {
    const d = drag.current;
    drag.current = null;
    if (!d?.moved) return;
    delete nav.current.dataset.dragging;
    delete nav.current.dataset.over;
    nav.current.style.removeProperty("--drag");
    const index = indexAt(e.clientX);
    // Dropping on Scan opens the camera but leaves the lens where it was.
    choose(index, nav.current.querySelectorAll("button")[index]);
  }

  return html`
    <nav
      ref=${nav}
      class=${collapsed ? "tabbar collapsed" : "tabbar"}
      aria-label=${t("tab.label")}
      style=${{ "--active": active }}
      onPointerDown=${down}
      onPointerMove=${move}
      onPointerUp=${up}
      onPointerCancel=${up}
      onClick=${collapsed ? () => set({ collapsed: false }) : undefined}
    >
      <span class="lens" aria-hidden="true"></span>
      ${TABS.map(
        (item, i) => html`<button
          type="button"
          data-tab=${item.id}
          aria-current=${item.id === tab ? "page" : undefined}
          tabindex=${collapsed ? -1 : 0}
          onClick=${(e) => {
            if (!collapsed) choose(i, e.currentTarget);
          }}
        >
          <${Icon} name=${item.icon} size=${26} width=${1.7} />
          <span class="tab-label">${t(item.label)}</span>
        </button>`,
      )}
    </nav>
  `;
}

// The bar shrinks after 14 px of scrolling down, comes back after 14 px up
// or near the top (the prototype's onScroll).
export function watchScroll() {
  let lastY = 0;
  let lastEl = null;
  let acc = 0;
  return (e) => {
    const el = e.currentTarget;
    const y = el.scrollTop;
    if (lastEl !== el) {
      lastEl = el;
      lastY = y;
      acc = 0;
    }
    const dy = y - lastY;
    lastY = y;
    let next = get().collapsed;
    if (y < 30) {
      next = false;
      acc = 0;
    } else {
      acc = acc > 0 === dy > 0 ? acc + dy : dy;
      if (acc > 14) next = true;
      else if (acc < -14) next = false;
    }
    if (next !== get().collapsed) set({ collapsed: next });
  };
}
