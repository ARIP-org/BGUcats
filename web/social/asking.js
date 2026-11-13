// Asking the phone for the camera or for where it is. Each is a question
// iOS puts to the person, and in a web app installed on the home screen an
// unanswered one stops every touch: on 2026-11-13 the owner's iPhone froze
// the moment the capture flow opened, until the app was closed. The page
// cannot see that happen, so it leaves a note before it asks and takes it
// away when the phone answers. A note still there at the next launch means
// the app was closed with the question unanswered: it then stops asking
// for that by itself, says so, and asks again only when the person chooses
// to (askAgain). One freeze must not be every launch.

const ASKING = "bgucats.asking"; // what is being asked right now
const QUIET = "bgucats.notAsking"; // what is no longer asked without being told to

function kept(key) {
  try {
    const list = JSON.parse(localStorage.getItem(key));
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

function keep(key, list) {
  try {
    if (list.length) localStorage.setItem(key, JSON.stringify(list));
    else localStorage.removeItem(key);
  } catch {
    /* no storage: this launch simply asks */
  }
}

// At launch: what was left unanswered last time, now no longer asked.
export function unanswered() {
  const left = kept(ASKING);
  if (!left.length) return [];
  keep(QUIET, [...new Set([...kept(QUIET), ...left])]);
  keep(ASKING, []);
  return left;
}

export const quiet = (kind) => kept(QUIET).includes(kind);

// The person asked for it themselves: ask again from now on.
export function askAgain(kind) {
  keep(QUIET, kept(QUIET).filter((k) => k !== kind));
}

// ask() -> a promise that settles when the phone has answered, either way.
export async function asking(kind, ask) {
  keep(ASKING, [...new Set([...kept(ASKING), kind])]);
  try {
    return await ask();
  } finally {
    keep(ASKING, kept(ASKING).filter((k) => k !== kind));
  }
}

// The page has been drawn: a question put to the phone inside the tap that
// opened a screen is asked before that screen exists.
export const painted = () =>
  new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
