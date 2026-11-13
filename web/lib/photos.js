// Presigned photo addresses, kept stable so the browser's cache works.
// Shared by both shells; moved out of app.js unchanged in milestone E0.

// Photo URLs are presigned, so every response signs the same photo afresh,
// and a new URL is a cache miss: every screen used to download every photo
// again. The first URL seen for each object is reused until shortly before
// it expires (kept across launches), and S3 serves it with a long
// Cache-Control (handler._presign), so a photo downloads about once an hour.
const URLS_KEY = "bgucats.photoUrls";
const URL_MARGIN_MS = 5 * 60 * 1000;
const photoUrls = loadPhotoUrls(); // object URL without query -> { url, expiresAt }
let savePhotoUrlsTimer = null;

function loadPhotoUrls() {
  try {
    const now = Date.now();
    return new Map(
      Object.entries(JSON.parse(localStorage.getItem(URLS_KEY)) || {}).filter(
        ([, v]) => v.expiresAt - now > URL_MARGIN_MS,
      ),
    );
  } catch {
    return new Map();
  }
}

function savePhotoUrls() {
  clearTimeout(savePhotoUrlsTimer);
  savePhotoUrlsTimer = setTimeout(() => {
    try {
      localStorage.setItem(URLS_KEY, JSON.stringify(Object.fromEntries(photoUrls)));
    } catch {
      /* this launch still has them in memory */
    }
  }, 1000);
}

// When a presigned URL stops working. SigV2 (what boto3 signs with in
// us-east-1) says so outright; SigV4 gives the signing time and lifetime.
function urlExpiry(url) {
  const q = url.searchParams;
  if (q.get("Expires")) return Number(q.get("Expires")) * 1000;
  const date = q.get("X-Amz-Date")?.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/);
  if (!date || !q.get("X-Amz-Expires")) return null;
  const [, y, mo, d, h, mi, se] = date;
  return Date.parse(`${y}-${mo}-${d}T${h}:${mi}:${se}Z`) + Number(q.get("X-Amz-Expires")) * 1000;
}

export function stablePhotoUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    return value;
  }
  const expiresAt = urlExpiry(url);
  if (!expiresAt) return value;
  const key = url.origin + url.pathname;
  const known = photoUrls.get(key);
  if (known && known.expiresAt - Date.now() > URL_MARGIN_MS) return known.url;
  photoUrls.set(key, { url: value, expiresAt });
  savePhotoUrls();
  return value;
}

// Every "...Url" field in a response: thumbUrl, mediumUrl, coverUrl, videoUrl;
// and the member API's photos, {thumb, medium} (since E2), and a person's
// profile photo, `avatar` (B1b).
const PHOTO_KEYS = new Set(["thumb", "medium", "avatar"]);
export function keepPhotoUrls(data) {
  if (Array.isArray(data)) {
    for (const item of data) keepPhotoUrls(item);
  } else if (data && typeof data === "object") {
    for (const [key, value] of Object.entries(data)) {
      if (
        typeof value === "string" &&
        (key.endsWith("Url") || PHOTO_KEYS.has(key)) &&
        value.startsWith("https://")
      ) {
        data[key] = stablePhotoUrl(value);
      } else if (value && typeof value === "object") {
        keepPhotoUrls(value);
      }
    }
  }
  return data;
}

// A kept URL that fails anyway (the signing credentials ran out first) is
// forgotten, so the next screen uses the fresh one.
document.addEventListener(
  "error",
  (event) => {
    const src = event.target?.currentSrc || event.target?.src;
    if (!src || !(event.target instanceof HTMLImageElement || event.target instanceof HTMLVideoElement)) return;
    try {
      const url = new URL(src);
      if (photoUrls.get(url.origin + url.pathname)?.url === src) {
        photoUrls.delete(url.origin + url.pathname);
        savePhotoUrls();
      }
    } catch {
      /* not one of ours */
    }
  },
  true,
);
