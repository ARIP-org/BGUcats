// What the two places a person votes from share: the poll on a cat's page
// (cat.js) and a friends' vote card in the feed (feed.js).

// What a tap does to the poll before the server has answered: the caller's
// one vote moves to `key`, or is taken back (null). The server's answer
// replaces this a moment later; a refusal puts the poll back.
export function moved(poll, key) {
  const options = poll.options.map((o) => ({
    ...o,
    votes: o.votes - (o.mine ? 1 : 0) + (o.nameKey === key ? 1 : 0),
    mine: o.nameKey === key,
  }));
  const counted = options.filter((o) => !o.pending);
  return { ...poll, options, myVote: key, total: counted.reduce((sum, o) => sum + o.votes, 0) };
}

export const REFUSED = {
  not_accepted: "poll.notAccepted",
  try_again: "poll.tryAgain",
  rate_limited: "poll.slowDown",
};
