// How things move, ported from the prototype (makeSpring and bindGlass in
// Feed.dc.html). Movement that follows a finger is written straight to the
// element with the Web Animations API, never through a redraw.

export const reducedMotion = () =>
  matchMedia("(prefers-reduced-motion: reduce)").matches;

// An Apple-style spring (damping ratio, response in seconds) sampled into a
// CSS linear() easing, where the browser has one.
export function makeSpring(zeta, response) {
  const fallback = { ease: "cubic-bezier(0.3, 1.35, 0.5, 1)", dur: 520 };
  try {
    if (!CSS.supports("animation-timing-function", "linear(0, 1)")) return fallback;
    const w = (2 * Math.PI) / response;
    const wd = w * Math.sqrt(1 - zeta * zeta);
    const T = 0.8;
    const n = 48;
    const points = [];
    for (let i = 0; i <= n; i++) {
      const t = (T * i) / n;
      const x = 1 - Math.exp(-zeta * w * t) * (Math.cos(wd * t) + ((zeta * w) / wd) * Math.sin(wd * t));
      points.push(i === n ? "1" : x.toFixed(4));
    }
    return { ease: `linear(${points.join(", ")})`, dur: T * 1000 };
  } catch {
    return fallback;
  }
}

export const spring = makeSpring(0.62, 0.42);

// The glass button's press: it swells under the finger, more if held, with a
// highlight where it was touched (--gx, --gy, --gs in app.css), and springs
// back on release. Use as a ref: <button ref=${glass}>.
export function glass(el) {
  if (!el || el.__glass) return;
  el.__glass = true;
  const anims = {};
  let hover = false;
  let pressed = false;
  let hold = null;

  function go(prop, to, dur, easing) {
    if (reducedMotion()) dur = 0;
    let from;
    try {
      from = prop === "--gs" ? getComputedStyle(el).getPropertyValue("--gs").trim() : getComputedStyle(el)[prop];
    } catch {
      /* the starting value is a nicety */
    }
    if (!from || from === "none") from = prop === "scale" ? "1" : "0";
    let a;
    try {
      a = el.animate({ [prop]: [from, to] }, { duration: dur, easing, fill: "forwards" });
    } catch {
      return;
    }
    anims[prop]?.cancel();
    anims[prop] = a;
  }
  function aim(e) {
    const r = el.getBoundingClientRect();
    if (!r.width) return;
    const x = Math.max(0, Math.min(100, ((e.clientX - r.x) / r.width) * 100));
    const y = Math.max(0, Math.min(100, ((e.clientY - r.y) / r.height) * 100));
    el.style.setProperty("--gx", `${x.toFixed(1)}%`);
    el.style.setProperty("--gy", `${y.toFixed(1)}%`);
  }
  function release() {
    if (!pressed) return;
    pressed = false;
    clearTimeout(hold);
    go("scale", hover ? "1.05" : "1", spring.dur, spring.ease);
    go("--gs", hover ? "0.2" : "0", 420, "ease-out");
  }
  el.addEventListener("pointerenter", (e) => {
    if (e.pointerType !== "mouse") return;
    hover = true;
    aim(e);
    if (!pressed) {
      go("scale", "1.05", 260, "cubic-bezier(0.23, 1, 0.32, 1)");
      go("--gs", "0.2", 260, "ease-out");
    }
  });
  el.addEventListener("pointerleave", () => {
    hover = false;
    if (!pressed) {
      go("scale", "1", spring.dur, spring.ease);
      go("--gs", "0", 320, "ease-out");
    }
  });
  el.addEventListener("pointermove", aim);
  el.addEventListener("pointerdown", (e) => {
    pressed = true;
    aim(e);
    go("scale", "1.1", 300, "cubic-bezier(0.3, 1.45, 0.5, 1)");
    go("--gs", "0.42", 180, "ease-out");
    clearTimeout(hold);
    hold = setTimeout(() => {
      if (!pressed) return;
      go("scale", "1.17", 760, "cubic-bezier(0.22, 1, 0.36, 1)");
      go("--gs", "0.62", 760, "ease-out");
    }, 380);
    addEventListener("pointerup", release, { once: true });
    addEventListener("pointercancel", release, { once: true });
  });
}
