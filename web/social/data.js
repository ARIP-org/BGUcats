// The member app's data layer (docs/app-plan/05-client.md, "The data
// layer"): every screen reads and writes through here, never with fetch.
// Reads reuse a recent answer (the shared cachedGet); likes change on
// screen at once and are sent, and a refusal puts the old state back.

import { api, cachedGet, del, put } from "../lib/api.js";

const query = (cursor) => (cursor ? `?cursor=${encodeURIComponent(cursor)}` : "");

// One page of the feed: {cards, cursor}; no cursor on the last page.
export const feedPage = (cursor) => api(`/v1/feed${query(cursor)}`);

export const cats = (redraw = () => {}) => cachedGet("/v1/cats", redraw);
export const cat = (catId, redraw = () => {}) => cachedGet(`/v1/cats/${catId}`, redraw);
export const catPosts = (catId) => api(`/v1/cats/${catId}/posts`);

// -> {postId, liked, likes}
export const setLike = (postId, liked) =>
  liked ? put(`/v1/posts/${postId}/like`) : del(`/v1/posts/${postId}/like`);

export const deletePost = (postId) => del(`/v1/posts/${postId}`);

// The campus places (web/regions.json), for an area's name.
let regions = null;
export async function regionName(id, lang = "en") {
  if (!id) return null;
  if (!regions) {
    const res = await fetch(new URL("../regions.json", import.meta.url));
    regions = res.ok ? (await res.json()).regions : [];
  }
  const region = regions.find((r) => r.id === id);
  return region ? region.names[lang] || region.names.en : null;
}
