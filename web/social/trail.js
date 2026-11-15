// The app's own account of what it was doing, kept on this phone and shown
// under Profile, "App info". The keeping is in app.html (it must work
// when none of these files arrive); this is the way in from the modules.
// A line says what happened, never who: no name, no address, no text
// anyone wrote.

export function mark(what) {
  try {
    window.bgucatsMark?.(what);
  } catch {
    /* a line not kept is never a reason to stop */
  }
}

// Everything kept, as text to read or copy.
export const appInfo = () => window.bgucatsInfo?.() || "";

// copyInfo() -> true when the phone copied it; false when the text must be
// copied by hand. `shown`: the text already on screen, copied as it is.
export const copyInfo = (shown) =>
  new Promise((resolve) => {
    if (!window.bgucatsCopyInfo) resolve(false);
    else window.bgucatsCopyInfo((copied) => resolve(copied), shown);
  });
