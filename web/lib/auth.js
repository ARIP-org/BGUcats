// Signing in, shared by both shells: the desk and Capture (app.js) and the
// member app (app.html). Moved out of app.js unchanged in milestone E0
// (docs/app-plan/05-client.md, "Moving shared code out of app.js"), apart
// from two things the desk used to do here itself: where to go after a
// sign-in or sign-out (`home`) and what to show when Cognito turns one away
// (`onRefused`).
//
// Cognito hosted UI, authorization code + PKCE.

import { isNative } from "../install.js";

let config = null;

// The site's public config.json, read once at boot by whichever shell runs.
export function useConfig(value) {
  config = value;
}

export const getConfig = () => config;

export function claims(token) {
  try {
    return JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return {};
  }
}

export const TOKENS_KEY = "bgucats.tokens";
const VERIFIER_KEY = "bgucats.pkce";
// A message for the sign-in screen that has to survive a page load: why the
// last sign-in was turned away, or that the person signed out.
export const LOGIN_NOTE_KEY = "bgucats.loginNote";
// Remembered so the app opens without a connection — under a bush with no
// signal is exactly where Capture gets used. The API still checks the real
// role on every call.
export const ROLE_KEY = "bgucats.role";
// Cognito sends every sign-in back to the site's root (config.redirectUri),
// where the desk's boot trades the code for tokens. A sign-in started from
// the member app (app.html) leaves its address here and is sent back to it.
const RETURN_KEY = "bgucats.returnTo";

export function takeReturnTo() {
  try {
    const back = sessionStorage.getItem(RETURN_KEY);
    sessionStorage.removeItem(RETURN_KEY);
    return back;
  } catch {
    return null;
  }
}

const b64url = (bytes) =>
  btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

async function pkce() {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)));
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(verifier),
  );
  return { verifier, challenge: b64url(new Uint8Array(digest)) };
}

// The iPhone app's way to Cognito and back: iOS's own sign-in sheet, opened
// by a small native plugin (native/plugins/web-auth). Google refuses to sign
// anyone in inside an app's web view, so the page cannot simply go there.
export const nativeSignIn = () => window.Capacitor?.Plugins?.WebAuth;

export async function login({ home = "/", onRefused = () => {} } = {}) {
  const { verifier, challenge } = await pkce();
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.userPoolClientId,
    redirect_uri: config.redirectUri,
    scope: "openid email profile",
    code_challenge: challenge,
    code_challenge_method: "S256",
    // Straight to Google rather than via Cognito's provider chooser — it is
    // the only provider, so the extra page is pure friction.
    identity_provider: "Google",
    // Google's account chooser, every time. Without it Google silently
    // reuses whichever account the phone is signed in to, so someone turned
    // away, or signed out, could never pick a different one. Cognito passes
    // this on to Google only with managed login (infra/main/cognito.tf).
    prompt: "select_account",
  });
  const authorize = `https://${config.cognitoDomain}/oauth2/authorize?${params}`;
  if (!isNative()) {
    sessionStorage.setItem(VERIFIER_KEY, verifier);
    if (home !== "/") sessionStorage.setItem(RETURN_KEY, home);
    location.assign(authorize);
    return;
  }

  // The sheet watches for the scheme of the address Cognito sends people
  // back to (the packed config's redirectUri, scripts/native_bundle.py) and
  // hands that whole address over, where a browser would have loaded it.
  let answer;
  try {
    answer = await nativeSignIn().start({
      url: authorize,
      callbackScheme: new URL(config.redirectUri).protocol.slice(0, -1),
    });
  } catch (err) {
    if (err?.code === "CANCELLED") return; // the person closed the sheet
    throw new Error(err?.message || "Sign-in did not finish.");
  }
  if (await finishSignIn(new URL(answer.url).searchParams, verifier)) {
    location.replace(home); // start again, signed in
  } else {
    onRefused(); // show the sign-in screen, with the reason if Cognito gave one
  }
}

// Signing out forgets this app's tokens and stays inside the app. There is no
// trip to Cognito's /logout page: leaving the app's own address is what makes
// an installed iPhone app show Safari's address bar and toolbar, and nothing
// is gained by it — the next sign-in asks Google which account to use anyway.
export function logout(home = "/") {
  forgetSignIn("Signed out. Choose an account to sign in again.");
  location.replace(home);
}

export function forgetSignIn(note) {
  dropTokens();
  localStorage.removeItem(ROLE_KEY);
  try {
    if (note) sessionStorage.setItem(LOGIN_NOTE_KEY, note);
  } catch {
    /* the note is a courtesy */
  }
}

async function exchangeToken(body) {
  const res = await fetch(`https://${config.cognitoDomain}/oauth2/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: config.userPoolClientId,
      ...body,
    }),
  });
  if (!res.ok) throw new Error(`token endpoint returned ${res.status}`);
  const data = await res.json();
  const tokens = {
    idToken: data.id_token,
    // A refresh grant does not return a new refresh token; keep the old one.
    refreshToken: data.refresh_token || readTokens()?.refreshToken,
    expiresAt: Date.now() + (data.expires_in - 60) * 1000,
  };
  saveTokens(tokens);
  return tokens;
}

// The tokens live in localStorage for the page, and a copy in IndexedDB for
// the service worker, which has no localStorage: it uploads a closed app's
// photos (sw.js, Background Sync) and must sign those requests. Same origin,
// same exposure as localStorage; dropped together on sign-out.
const AUTH_DB = "bgucats-auth";

function authStore(mode, fn) {
  return new Promise((resolve) => {
    try {
      const open = indexedDB.open(AUTH_DB, 1);
      open.onupgradeneeded = () => open.result.createObjectStore("tokens");
      open.onsuccess = () => {
        const tx = open.result.transaction("tokens", mode);
        fn(tx.objectStore("tokens"));
        tx.oncomplete = tx.onerror = () => {
          open.result.close();
          resolve();
        };
      };
      open.onerror = () => resolve();
    } catch {
      resolve(); // the worker just won't upload in the background
    }
  });
}

export function saveTokens(tokens) {
  localStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
  authStore("readwrite", (store) => store.put(tokens, "current"));
}

export function dropTokens() {
  localStorage.removeItem(TOKENS_KEY);
  authStore("readwrite", (store) => store.delete("current"));
}

export function readTokens() {
  try {
    return JSON.parse(localStorage.getItem(TOKENS_KEY));
  } catch {
    return null;
  }
}

export async function idToken() {
  const tokens = readTokens();
  if (!tokens) return null;
  if (Date.now() < tokens.expiresAt) return tokens.idToken;
  if (!tokens.refreshToken) return null;
  try {
    const refreshed = await exchangeToken({
      grant_type: "refresh_token",
      refresh_token: tokens.refreshToken,
    });
    return refreshed.idToken;
  } catch (err) {
    // No connection is not a rejected login: keep the refresh token for when
    // the phone is back online. The stale token fails its API call, and the
    // upload outbox simply retries later.
    if (err instanceof TypeError) return tokens.idToken;
    dropTokens();
    return null;
  }
}

// What Cognito answered a sign-in with: a code to trade for tokens, or why
// not. True once the tokens are stored. The browser finds the answer in its
// own address after the redirect; the iPhone app is handed it by the sheet.
export async function finishSignIn(params, verifier) {
  if (params.get("error")) {
    // Cognito rejected the sign-up — almost always the pre-sign-up trigger
    // refusing an email that is not on the allowlist. Cognito prefixes the
    // trigger's message with its own plumbing.
    const reason = (params.get("error_description") || params.get("error"))
      .replace(/^PreSignUp failed with error\s*/i, "")
      .trim();
    forgetSignIn(`${reason} Sign in with a different Google account.`);
    return false;
  }
  const code = params.get("code");
  if (!code || !verifier) return false;
  await exchangeToken({
    grant_type: "authorization_code",
    code,
    redirect_uri: config.redirectUri,
    code_verifier: verifier,
  });
  return true;
}

export async function consumeCallback() {
  const params = new URLSearchParams(location.search);
  if (!params.get("code") && !params.get("error")) return;
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  sessionStorage.removeItem(VERIFIER_KEY);
  history.replaceState({}, "", location.pathname);
  await finishSignIn(params, verifier);
}
