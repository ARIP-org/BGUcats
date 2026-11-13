// The map (E5), the prototype's in Feed.dc.html: a drawn campus, not a map
// service. Ground, greens, roads and buildings in the theme's colours,
// dragged with a finger; five habitats, each an area to tap, with the cats
// that live there as round photos; and a sheet that names the chosen
// habitat and lists its cats with their grades.
//
// Which cats live where is the cat's usual place, which an admin sets
// (`regionId`); the places and their names are web/regions.json. The
// drawing below is the prototype's and belongs to the placeholder campus:
// when the owner supplies the real places (O12) it is drawn again.
//
// Not drawn yet: feeding spots (D10), which wait for the design (G6).

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.js";
import { cats as loadCats, places } from "./data.js";
import { oneDecimal, t } from "./i18n.js";
import { glass, reducedMotion } from "./motion.js";
import { openScan } from "./scan.js";
import { get, pop, push } from "./store.js";

const WIDE = 900;
const TALL = 1300;
const PINS = 3; // cats shown on the map itself for one habitat; the sheet lists all

// Each habitat's area and where its middle is, by the region's id.
export const HABITATS = {
  engineering: {
    at: [660, 360],
    area: "M769.9 360.0 C766.8 377.9 741.0 393.6 725.4 407.2 C709.9 420.8 696.5 436.2 676.7 441.5 C657.0 446.8 622.5 448.7 606.9 439.2 C591.2 429.6 590.4 402.4 582.9 384.1 C575.4 365.8 557.4 345.6 562.0 329.3 C566.6 313.0 591.8 293.1 610.6 286.3 C629.3 279.6 652.4 286.8 674.6 289.0 C696.8 291.2 727.8 287.7 743.7 299.6 C759.6 311.4 772.9 342.1 769.9 360.0Z",
  },
  library: {
    at: [255, 470],
    area: "M352.0 470.0 C350.7 488.1 338.9 505.0 326.0 521.2 C313.2 537.5 294.3 565.1 275.0 567.7 C255.7 570.3 229.4 548.0 210.2 536.7 C191.0 525.4 169.8 516.4 159.8 499.8 C149.8 483.2 141.6 452.9 150.3 437.2 C159.0 421.6 191.3 415.9 211.9 405.8 C232.6 395.8 253.6 375.9 274.0 377.1 C294.5 378.2 321.4 397.2 334.4 412.7 C347.4 428.2 353.4 451.9 352.0 470.0Z",
  },
  union: {
    at: [565, 790],
    area: "M656.3 790.0 C660.1 809.3 668.8 841.7 656.5 856.0 C644.2 870.3 606.0 874.8 582.6 875.9 C559.2 877.0 538.2 870.9 516.3 862.5 C494.5 854.1 458.0 842.2 451.5 825.5 C444.9 808.9 467.0 781.6 477.0 762.5 C487.1 743.3 493.8 722.6 511.8 710.8 C529.8 698.9 564.9 686.4 585.2 691.3 C605.6 696.2 622.3 723.7 634.1 740.1 C646.0 756.6 652.6 770.7 656.3 790.0Z",
  },
  dorms: {
    at: [245, 1030],
    area: "M360.3 1030.0 C360.8 1050.4 347.7 1079.1 331.2 1092.2 C314.7 1105.3 285.7 1104.1 261.2 1108.9 C236.7 1113.6 203.0 1128.8 184.1 1120.7 C165.3 1112.6 153.6 1080.3 148.2 1060.3 C142.8 1040.3 145.8 1021.1 151.7 1000.8 C157.5 980.5 165.2 947.0 183.5 938.4 C201.8 929.9 237.4 944.2 261.5 949.4 C285.6 954.7 311.7 956.5 328.2 970.0 C344.6 983.4 359.8 1009.6 360.3 1030.0Z",
  },
  lawn: {
    at: [690, 1065],
    area: "M788.6 1065.0 C785.4 1081.3 761.7 1093.4 748.0 1106.8 C734.3 1120.2 723.8 1140.9 706.5 1145.4 C689.1 1149.8 658.6 1143.3 643.9 1133.7 C629.2 1124.0 626.0 1103.9 618.1 1087.5 C610.1 1071.2 591.0 1049.8 596.0 1035.6 C600.9 1021.3 629.8 1008.8 647.8 1002.1 C665.8 995.5 684.3 994.6 704.2 995.7 C724.1 996.9 753.3 997.7 767.3 1009.2 C781.4 1020.7 791.8 1048.7 788.6 1065.0Z",
  },
};

const GREENS = [
  [110, 140, 200, 150, 30],
  [520, 470, 130, 90, 24],
  [600, 980, 200, 160, 40],
  [110, 640, 170, 110, 26],
  [330, 900, 140, 70, 20],
];
const PATHS = [
  "M120 330 H780",
  "M120 880 H780",
  "M250 80 V600",
  "M650 610 V1220",
  "M450 610 C520 700 600 700 700 760",
  "M160 760 C220 820 300 840 380 830",
];
const BUILDINGS = [
  [140, 360, 80, 120],
  [300, 380, 110, 70],
  [300, 470, 70, 90],
  [490, 120, 110, 80],
  [620, 120, 160, 70],
  [500, 220, 90, 80],
  [610, 260, 90, 60],
  [720, 250, 70, 150],
  [520, 380, 100, 60],
  [700, 430, 90, 120],
  [300, 640, 110, 90],
  [480, 640, 70, 120],
  [720, 640, 80, 100],
  [490, 900, 140, 60],
  [480, 980, 80, 70],
  [130, 900, 80, 70],
  [130, 1000, 60, 90],
  [330, 990, 70, 80],
  [250, 1100, 120, 40],
  [700, 860, 90, 80],
];

const clamp = (value, low) => Math.max(Math.min(low, 0), Math.min(0, value));

// Where the campus sits so that a habitat's middle is in view: across the
// middle, and a little above it, clear of the sheet.
export function centred(at, view) {
  return {
    x: clamp(view.width / 2 - at[0], view.width - WIDE),
    y: clamp(view.height * 0.378 - at[1], view.height - TALL),
  };
}

// The campus as a drawing. The words on it are the app's strings.
function Campus({ chosen, choose }) {
  return html`<svg class="map-drawing" width=${WIDE} height=${TALL} viewBox=${`0 0 ${WIDE} ${TALL}`}>
    <rect class="map-ground" x="60" y="80" width="780" height="1140" rx="120" />
    ${GREENS.map(([x, y, w, h, r]) => html`<rect class="map-green" x=${x} y=${y} width=${w} height=${h} rx=${r} />`)}
    <path class="map-wadi" d="M40 1180 C220 1110 330 1180 470 1150 S720 1070 860 1120" />
    <rect class="map-road ring" x="60" y="80" width="780" height="1140" rx="120" />
    <path class="map-road" d="M60 610 H840 M450 80 V1220" />
    ${PATHS.map((d) => html`<path class="map-path" d=${d} />`)}
    ${BUILDINGS.map(([x, y, w, h]) => html`<rect class="map-building" x=${x} y=${y} width=${w} height=${h} rx="8" />`)}
    <text class="map-label" x="450" y="60" aria-hidden="true">${t("map.campus")}</text>
    <text class="map-label" x="210" y="225" aria-hidden="true">${t("map.lawn")}</text>
    <text class="map-label" x="465" y="1205" aria-hidden="true">${t("map.wadi")}</text>
    ${Object.entries(HABITATS).map(
      ([id, habitat]) => html`<path
        class=${id === chosen ? "map-habitat chosen" : "map-habitat"}
        data-region=${id}
        d=${habitat.area}
        aria-hidden="true"
        onClick=${() => choose(id)}
      />`,
    )}
  </svg>`;
}

export function MapPage({ regionId = null }) {
  const [cats, setCats] = useState(null);
  const [regions, setRegions] = useState([]);
  const [chosen, setChosen] = useState(regionId && HABITATS[regionId] ? regionId : null);
  const view = useRef(null);
  const campus = useRef(null);
  const at = useRef({ x: -50, y: -140 });
  const drag = useRef(null);
  const dragged = useRef(0);

  // The campus is moved by its style, not by a redraw: a finger moves it
  // sixty times a second.
  function place(x, y, glide) {
    at.current = { x, y };
    const el = campus.current;
    if (!el) return;
    el.style.transition = glide && !reducedMotion() ? `translate ${glide}` : "none";
    el.style.translate = `${x}px ${y}px`;
  }
  const size = () => view.current.getBoundingClientRect();
  const show = (id) => {
    const to = centred(HABITATS[id].at, size());
    place(to.x, to.y, "0.75s cubic-bezier(0.3, 1.05, 0.4, 1)");
  };

  useEffect(() => {
    let live = true;
    loadCats()
      .then((answer) => live && setCats(answer.cats))
      .catch(() => live && setCats([]));
    places().then((list) => live && setRegions(list));
    // Opened on a habitat: it is in view from the first frame.
    const first = chosen ? centred(HABITATS[chosen].at, size()) : { x: clamp(-50, size().width - WIDE), y: clamp(-140, size().height - TALL) };
    place(first.x, first.y);
    return () => {
      live = false;
    };
  }, []);

  const choose = (id) => {
    if (performance.now() - dragged.current < 280) return; // the end of a drag, not a tap
    setChosen(id);
    show(id);
  };

  // Dragging. The page under the map also listens for a swipe from its
  // edge to go back; the map keeps its own touches.
  function down(e) {
    e.stopPropagation();
    if (drag.current || (e.pointerType === "mouse" && e.button !== 0)) return;
    drag.current = { id: e.pointerId, x0: e.clientX, y0: e.clientY, bx: at.current.x, by: at.current.y, moved: false, last: [e.clientX, e.clientY, performance.now()], v: [0, 0] };
  }
  function move(e) {
    const d = drag.current;
    if (!d || e.pointerId !== d.id) return;
    const dx = e.clientX - d.x0;
    const dy = e.clientY - d.y0;
    if (!d.moved) {
      if (Math.abs(dx) + Math.abs(dy) < 6) return;
      d.moved = true;
      e.currentTarget.setPointerCapture?.(d.id);
    }
    const now = performance.now();
    const dt = Math.max(1, now - d.last[2]);
    d.v = [(e.clientX - d.last[0]) / dt, (e.clientY - d.last[1]) / dt];
    d.last = [e.clientX, e.clientY, now];
    const r = size();
    // Past an edge the campus follows a third as far, and springs back.
    const soft = (value, low) => (value > 0 ? value / 3 : value < low ? low + (value - low) / 3 : value);
    place(soft(d.bx + dx, Math.min(0, r.width - WIDE)), soft(d.by + dy, Math.min(0, r.height - TALL)));
  }
  function up(e) {
    const d = drag.current;
    if (!d || (e.pointerId != null && e.pointerId !== d.id)) return;
    drag.current = null;
    if (!d.moved) return;
    dragged.current = performance.now();
    const r = size();
    // It glides on a little the way it was going, and stops inside its edges.
    const x = clamp(at.current.x + d.v[0] * 220, r.width - WIDE);
    const y = clamp(at.current.y + d.v[1] * 220, r.height - TALL);
    place(x, y, "0.6s cubic-bezier(0.16, 1, 0.3, 1)");
  }

  const names = Object.fromEntries(regions.map((r) => [r.id, r.names.en]));
  const living = (id) =>
    (cats || [])
      .filter((cat) => cat.regionId === id)
      .sort((a, b) => (b.gpa ?? 0) - (a.gpa ?? 0) || (a.name || "").localeCompare(b.name || ""));
  const here = chosen ? living(chosen) : [];
  const openCat = (cat) => push("cat", { catId: cat.catId, title: cat.name || t("cat.noName") });
  const sub = !chosen
    ? t("map.hint")
    : !cats
      ? t("feed.loading")
      : here.length
        ? t("map.livesHere", { count: here.length })
        : t("map.nobody");

  return html`<div class="map" ref=${view}>
    <div class="map-pan" onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up}>
      <div class="map-campus" ref=${campus}>
        <${Campus} chosen=${chosen} choose=${choose} />
        ${Object.entries(HABITATS).map(([id, habitat]) => {
          const [x, y] = habitat.at;
          const pins = living(id).slice(0, PINS);
          return html`${pins.map(
              (cat, i) => html`<button
                type="button"
                key=${cat.catId}
                class=${id === chosen ? "map-pin chosen" : "map-pin"}
                data-cat=${cat.catId}
                aria-label=${cat.name || t("cat.noName")}
                style=${{ insetInlineStart: `${x - 26 + (i - (pins.length - 1) / 2) * 38}px`, insetBlockStart: `${y - 40}px` }}
                onClick=${() => (id === chosen ? openCat(cat) : choose(id))}
              >
                ${cat.cover && html`<img src=${cat.cover.thumb} alt="" />`}
              </button>`,
            )}
            <button
              type="button"
              class=${id === chosen ? "map-chip chosen" : "map-chip"}
              data-region=${id}
              aria-pressed=${String(id === chosen)}
              style=${{ insetInlineStart: `${x}px`, insetBlockStart: `${y + 34}px` }}
              onClick=${() => choose(id)}
            >
              ${names[id] || ""}
            </button>`;
        })}
      </div>
    </div>
    <section class="map-sheet" aria-label=${t("map.habitat")}>
      <div class="map-sheet-head">
        <button type="button" class="glass-icon map-back" ref=${glass} aria-label=${t("map.close")} onClick=${pop}>
          <svg class="icon mirror" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 5l-7 7 7 7" /></svg>
        </button>
        <div class="map-sheet-words">
          <h1 class="map-sheet-title">${chosen ? names[chosen] || "" : t("map.title")}</h1>
          <span class="map-sheet-sub">${sub}</span>
        </div>
        ${chosen &&
        cats &&
        !here.length &&
        html`<button type="button" class="glass-button small map-scan" onClick=${() => openScan("scan")}>${t("tab.scan")}</button>`}
      </div>
      ${here.length > 0 &&
      html`<div class="map-cats" data-hscroll>
        ${here.map(
          (cat) => html`<button type="button" key=${cat.catId} class="map-cat" data-cat=${cat.catId} onClick=${() => openCat(cat)}>
            ${cat.cover ? html`<img src=${cat.cover.thumb} alt="" />` : html`<span class="map-cat-empty" aria-hidden="true"></span>`}
            <span class="map-cat-name">${cat.name || t("cat.noName")}</span>
            ${cat.gpa != null && html`<span class="map-cat-gpa">${oneDecimal(cat.gpa)}</span>`}
          </button>`,
        )}
      </div>`}
    </section>
  </div>`;
}

// Opens the map, on a cat's usual place if it has one.
export const openMap = (regionId = null) => {
  if (get().stack.some((page) => page.name === "map")) return;
  push("map", { title: t("map.title"), regionId });
};
