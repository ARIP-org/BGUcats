// Charts for the stats page. Plain HTML boxes rather than SVG: they reflow
// with their container, so one chart works from a phone to a desk without
// re-rendering on resize, and every label stays real, selectable text.
//
// One hue for every mark (--chart in styles.css). Each chart here is a single
// series; what a bar *means* is carried by its label, never by its colour.

const fmt = new Intl.NumberFormat("en");
export const formatNumber = (n) => fmt.format(n ?? 0);

function h(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

// Round an axis maximum up to 1, 2 or 5 × 10^k, so the one gridline label
// is a number a person would write.
function niceCeil(value) {
  if (value <= 1) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 5, 10]) {
    if (value <= step * magnitude) return step * magnitude;
  }
  return 10 * magnitude;
}

// --------------------------------------------------------------------------
// Tooltip — one per chart; follows hover, keyboard focus and taps alike
// --------------------------------------------------------------------------

function tooltipFor(root) {
  const tip = h("div", "chart-tip");
  tip.hidden = true;
  root.append(tip);

  function show(target, value, label) {
    tip.replaceChildren(h("strong", null, value), h("span", null, label));
    tip.hidden = false;
    const box = root.getBoundingClientRect();
    const at = target.getBoundingClientRect();
    const half = tip.offsetWidth / 2;
    const center = at.left - box.left + at.width / 2;
    tip.style.left = `${Math.min(Math.max(center, half), box.width - half)}px`;
    tip.style.top = `${at.top - box.top}px`;
  }

  return {
    attach(target, value, label) {
      target.tabIndex = 0;
      target.setAttribute("aria-label", `${label}: ${value}`);
      target.addEventListener("pointerenter", () => show(target, value, label));
      target.addEventListener("focus", () => show(target, value, label));
      // A tap focuses the mark, so the tooltip stays up until the next tap
      // elsewhere; only a mouse leaving should hide it.
      target.addEventListener("pointerleave", (e) => {
        if (e.pointerType === "mouse" && document.activeElement !== target) tip.hidden = true;
      });
      target.addEventListener("blur", () => (tip.hidden = true));
    },
  };
}

// --------------------------------------------------------------------------
// Column chart — a value per day
// --------------------------------------------------------------------------

/**
 * points: [{ label, value }] in time order; label is what the tooltip names.
 * unit:   what the value counts, for the tooltip ("photos", "visitors").
 * axis:   [first, last] x-axis captions.
 */
export function columnChart({ points, unit, axis }) {
  const top = niceCeil(Math.max(0, ...points.map((p) => p.value)));
  const root = h("div", "colchart");
  const tip = tooltipFor(root);

  const plot = h("div", "colchart-plot");
  plot.append(h("span", "colchart-max", formatNumber(top)));
  for (const point of points) {
    const col = h("div", "col");
    const bar = h("span", "col-bar");
    if (point.value > 0) {
      bar.style.height = `max(2px, ${(point.value / top) * 100}%)`;
    }
    col.append(bar);
    tip.attach(col, `${formatNumber(point.value)} ${unit}`, point.label);
    plot.append(col);
  }

  const xAxis = h("div", "colchart-axis");
  xAxis.append(h("span", null, axis[0]), h("span", null, axis[1]));
  root.append(plot, xAxis);
  return root;
}

// --------------------------------------------------------------------------
// Horizontal bars — ranked or ordered rows with a value each
// --------------------------------------------------------------------------

/**
 * rows: [{ label, value, display?, note?, tag?, tagTone? }]
 *   display  text shown at the bar's end (defaults to the formatted value)
 *   note     secondary line under the label
 *   tag      small marker beside the label ("partner", "✓ ready")
 * max:  shared scale; defaults to the largest value
 */
export function barList(rows, { max, className = "" } = {}) {
  const scale = max ?? Math.max(1, ...rows.map((r) => r.value));
  const list = h("ol", `barlist ${className}`.trim());
  for (const row of rows) {
    const item = h("li", "barlist-row");
    const label = h("div", "barlist-label");
    label.append(h("span", "barlist-name", row.label));
    if (row.tag) label.append(h("span", `tag ${row.tagTone || ""}`.trim(), row.tag));
    if (row.note) label.append(h("small", "barlist-note", row.note));

    const track = h("div", "barlist-track");
    const bar = h("span", "barlist-bar");
    if (row.value > 0) bar.style.width = `max(3px, ${(row.value / scale) * 100}%)`;
    track.append(bar);

    item.append(label, track, h("span", "barlist-value", row.display ?? formatNumber(row.value)));
    list.append(item);
  }
  return list;
}

/**
 * A funnel is ordered bars where each step also reports what share of the
 * step before it made it through — the number that says where people drop.
 * steps: [{ label, value, partner? }]
 */
export function funnel(steps) {
  const rows = steps.map((step, i) => {
    const previous = i > 0 ? steps[i - 1].value : null;
    const share =
      previous == null
        ? null
        : previous > 0
          ? `${Math.round((step.value / previous) * 100)}% of the step above`
          : "—";
    return {
      label: step.label,
      value: step.value,
      note: share,
      tag: step.partner ? "reported by partner" : null,
    };
  });
  return barList(rows, { className: "funnel" });
}

/** A labelled fraction as a filled track — "7 of 18 cats". */
export function meter(value, total) {
  const track = h("div", "meter");
  const fill = h("span", "meter-fill");
  fill.style.width = `${total ? Math.min(100, (value / total) * 100) : 0}%`;
  track.append(fill);
  track.setAttribute("role", "img");
  track.setAttribute("aria-label", `${value} of ${total}`);
  return track;
}
