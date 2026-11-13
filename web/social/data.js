// The member app's data layer (docs/app-plan/05-client.md, "The data
// layer"): every screen reads and writes through here, never with fetch.
// Reads reuse a recent answer (the shared cachedGet); likes change on
// screen at once and are sent, and a refusal puts the old state back.

import { api, cachedGet, del, patch, post, put } from "../lib/api.js";

const query = (cursor) => (cursor ? `?cursor=${encodeURIComponent(cursor)}` : "");

// One page of the feed: {cards, cursor}; no cursor on the last page.
export const feedPage = (cursor) => api(`/v1/feed${query(cursor)}`);

export const cats = (redraw = () => {}) => cachedGet("/v1/cats", redraw);
export const cat = (catId, redraw = () => {}) => cachedGet(`/v1/cats/${catId}`, redraw);
export const catPosts = (catId) => api(`/v1/cats/${catId}/posts`);

// A cat's name poll. Each answers with the whole poll as the caller sees
// it: {name, nameSource, options, total, locked, myVote, mySuggestion}.
export const names = (catId) => api(`/v1/cats/${catId}/names`);
export const suggestName = (catId, name) => post(`/v1/cats/${catId}/names`, { name });
export const voteFor = (catId, nameKey) => put(`/v1/cats/${catId}/vote`, { nameKey });
export const takeVoteBack = (catId) => del(`/v1/cats/${catId}/vote`);

// -> {postId, liked, likes}
export const setLike = (postId, liked) =>
  liked ? put(`/v1/posts/${postId}/like`) : del(`/v1/posts/${postId}/like`);

export const deletePost = (postId) => del(`/v1/posts/${postId}`);

// The caller: profile, role, counters (a second or two behind a pick).
export const me = () => api("/v1/me");
// Changes the caller's display name or settings; answers like `me`.
export const updateMe = (changes) => patch("/v1/me", changes);
// -> `me`. Refused with `name_taken` or `bad_username`.
export const chooseUsername = (username) => put("/v1/me/username", { username });
// A new profile photo (a JPEG Blob from avatar.js): asks where to send it,
// sends it straight to storage, then confirms. Answers like `me`.
export async function saveAvatar(blob) {
  const { avatarId, upload } = await post("/v1/me/avatar");
  const form = new FormData();
  for (const [name, value] of Object.entries(upload.fields)) form.append(name, value);
  form.append("file", blob); // must be the last field
  const sent = await fetch(upload.url, { method: "POST", body: form });
  if (!sent.ok) throw new Error(`storage refused the photo (${sent.status})`);
  return post(`/v1/me/avatar/${avatarId}/complete`);
}
export const removeAvatar = () => del("/v1/me/avatar");
// The caller's own posts, newest first, each with its state.
export const myPosts = () => api("/v1/me/posts");

// Points, the level, counters, badges and the rules (B7):
// {points, level: {level, from, next}, counters, badges: [{id, earned, at}], rules}.
export const achievements = () => api("/v1/achievements");

// Friends (B5). `friends`: {period, people, requests}, the caller among the
// people, most cats found first. A person: {userId, username, displayName,
// avatar, found, cats, friend, friendSince, me}.
export const friends = (period) => api(`/v1/friends?period=${period}`);
export const person = (userId) => api(`/v1/users/${userId}`);
export const personPosts = (userId) => api(`/v1/users/${userId}/posts`);
export const removeFriend = (userId) => del(`/v1/friends/${userId}`);
// Blocks (B8): each hides the two people from each other everywhere.
export const blocks = () => api("/v1/blocks");
export const block = (userId) => put(`/v1/blocks/${userId}`);
export const unblock = (userId) => del(`/v1/blocks/${userId}`);
// -> {person}. Refused with `gone` or `own_invite`.
export const acceptInvite = (code) => post(`/v1/invites/${code}/accept`);

// The campus places (web/regions.json), for an area's name and the
// new-cat form.
let regions = null;
export async function places() {
  if (!regions) {
    const res = await fetch(new URL("../regions.json", import.meta.url));
    regions = res.ok ? (await res.json()).regions : [];
  }
  return regions;
}

export async function regionName(id, lang = "en") {
  if (!id) return null;
  await places();
  const region = regions.find((r) => r.id === id);
  return region ? region.names[lang] || region.names.en : null;
}
