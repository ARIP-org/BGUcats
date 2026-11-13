// The member app's shared state, in one place (docs/app-plan/05-client.md,
// "The renderer"): who you are, the theme, the open tab and the stack of
// pages over it. No state in globals; a screen reads it with useStore and
// changes it with set().

import { useEffect, useState } from "../vendor/preact-htm.js";

const state = {
  me: null,
  theme: "bgu-dark",
  tab: "feed",
  stack: [], // pages pushed over the tab: [{ name, props }]
  collapsed: false, // the tab bar, shrunk while scrolling down
};
const listeners = new Set();

export const get = () => state;

export function set(changes) {
  Object.assign(state, changes);
  for (const listener of [...listeners]) listener(state);
}

export function useStore(pick = (s) => s) {
  const [, redraw] = useState(0);
  const drawn = pick(state);
  useEffect(() => {
    // What was drawn, not what is there now: a change made between the
    // first draw and this effect (a toast at launch) had no listener yet,
    // and was lost.
    let last = drawn;
    const listener = (next) => {
      const now = pick(next);
      if (now !== last) {
        last = now;
        redraw((n) => n + 1);
      }
    };
    listeners.add(listener);
    listener(state);
    return () => listeners.delete(listener);
  }, []);
  return drawn;
}

// Pages over the tab bar: a cat, a person, a post, settings.
export function push(name, props = {}) {
  set({ stack: [...state.stack, { name, props, key: `${name}-${Date.now()}` }] });
}

export function pop() {
  if (state.stack.length) set({ stack: state.stack.slice(0, -1) });
}

export function showTab(tab) {
  set({ tab, stack: [], collapsed: false });
}
