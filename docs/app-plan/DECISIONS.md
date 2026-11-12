# Decisions that are the owner's

Everything in the plan that is not Claude's to choose. Each has what it
is, the options, a recommendation, and what waits on it.

**How to answer:** write the choice in the "Answer" column below and
commit, or say it in a session and have the session write it here. A
session treats an empty answer as unanswered. Where "Default" says
*may proceed*, work can start on the recommendation and be changed later
at the stated cost; where it says *blocks*, nothing listed starts without
an answer.

## Answer sheet

| ID | Question, short | Recommendation | Default | Answer |
|---|---|---|---|---|
| **A1** | Relational database? | No. DynamoDB | blocks F1 | |
| **A2** | One table or a second one for the social data? | A second, `bgucats-social` | blocks F1 | |
| **A3** | How do side effects run: table stream, or async invoke? | Stream | blocks F1 | |
| A4 | How is the client rendered? | No build step, a small vendored renderer | may proceed | |
| A5 | Push: straight to Apple, or through SNS? | Straight to Apple | may proceed until B9 | |
| A6 | A custom domain now? | Buy it now, wire it when N4 needs it | may proceed until N4 | |
| **D1** | Who may sign up? Sign in with Apple? | BGU Google accounts + invited others; Apple for external TestFlight | blocks F4 | |
| **D2** | TestFlight: internal only, or external (a public link)? | Internal first, external at L2 | may proceed | |
| **D3** | Whose posts are in the feed? | The whole campus, friends marked | blocks B3 | |
| **D4** | Friends: instant, or by request? | Invite link instant; everything else by request | blocks B5 | |
| **D5** | Phone number and contact matching | Not in the first build; invite links only | blocks B5b only | |
| **D6** | Who names a cat: the poll, or an admin? | The poll leads; an admin can lock or remove | blocks B4 | |
| D7 | Is a proposed new cat public before an admin approves? | The post is; the cat joins the gallery on approval | blocks B6 | |
| D8 | When does "met" count? | At once, taken back if the label disagrees | blocks B7 | |
| **D9** | GPA: what is graded, and where? | Design it first | blocks B7b | |
| **D10** | The feeding log | Design it first; check campus policy | blocks B7c | |
| D11 | Badges, points, levels: the rules | The table in `01-product.md` | may proceed | |
| D12 | Extra frames behind each photo? | Yes, three, not shown | may proceed (off) | |
| D13 | What "Add location" off means | Not shown on the post; still recorded for the dataset; reword | blocks E3 copy | |
| **D14** | Deleting an account: what happens to its cat photos? | Kept, cut loose from the person | blocks B10 | |
| **D15** | Reporting a post; reasons; who answers within a day | Add it to the design | blocks B8 | |
| D16 | Age and terms | 16+, a short terms page | blocks L2 | |
| D17 | Languages at the first external build | English and Hebrew; Russian and Arabic after | may proceed | |
| D18 | What sends a notification | A friend's post, a friend request, your name idea leading | blocks B9 | |
| **M1** | Sending people's photos and text to Google | Yes, paid tier only, said in the privacy policy | blocks C1 | |
| M2 | When moderation starts acting | After a gold set and two weeks of shadow | may proceed (shadow) | |
| M3 | If Google is down | Hold for an admin; never publish unchecked | may proceed | |
| M4 | A person's face in a cat photo | Hide from the feed, ask an admin | may proceed | |
| **K1** | Re-rank: sending the query photo to Google live | Yes, same terms as M1 | blocks R3 | |
| K2 | The bar the experiment must clear | In `07-rerank.md` | may proceed | |
| K3 | Daily ceiling on Decision 1 spend | $2 a day per account | may proceed | |
| P1 | Budgets for a public app | Keep $10 / $20 / $40 until L2; revisit there | may proceed | |
| **P2** | When does the app reach production? | Dark behind flags from the start; on at L3 | blocks F1 | |
| **P3** | Changing `CLAUDE.md`'s hard constraints | Agree in principle now; each pull request changes its own rule | blocks F4 | |

Bold is what blocks the first milestones. Answering A1–A3, D1, P2 and P3
unblocks the foundations; D3, D4, D6, D14, D15 and M1 unblock the rest of
the backend.

---

## Architecture

### A1. A relational database

**You asked.** You expect the app to need one.

**Answer: it does not, and I recommend against it.** The reasoning, with
every screen's query written out, is in `02-architecture.md`, "The
database question". Short version: a social graph is relational in
*shape*, but nothing the prototype shows needs a join the database must
do. Friends, likes, votes, leaderboards and the feed are each one key
lookup, one short list, or one batch read. A relational database on AWS
costs a VPC (the thing spec §8.1 forbids), or an always-on minimum above
the $40 budget stop, or a 15-second wake-up for the first person after a
quiet spell.

**If you still want one,** the only option that fits this project is
**Aurora DSQL** (serverless, PostgreSQL-compatible, no VPC, sign-in by
IAM, scales to zero with no wake-up). It is a new service on the
organization's allowlist, a new resource type, a new driver in the
Lambdas, schema migrations as a new step in the deploy, and a second
source of truth beside the dataset table. Not RDS, not Aurora Serverless
v2. Check DSQL's current limits before choosing: as of my knowledge it
enforced no foreign keys and allowed no extensions.

**What would change my answer:** search over text, reports that need ad
hoc queries every week, a friends-only feed for tens of thousands of
accounts, or several campuses with shared analytics.

### A2. One table or two

- *One:* add the social items to `bgucats-data`. Fewer moving parts.
- *Two (recommended):* a new `bgucats-social`, same shape (PK, SK, three
  indexes, on-demand, point-in-time recovery, deletion protection). The
  member API's role can then write only that table. A bug in "like" can
  never touch a photo record. ROADMAP principle 5: the dataset is the one
  irreplaceable asset.

Cost of changing later: a data migration. Decide now.

### A3. How side effects run

After a post or a name is written, four things must happen without the
person waiting: moderation, counters and badges, the feed's activity
cards, push.

- *DynamoDB stream → an events Lambda (recommended).* The table is the
  log; every change is delivered at least once; failures retry and then
  email through the existing alerts topic. Needs one new resource type
  (`aws_lambda_event_source_mapping`), a stream on the new table, and the
  Lambda boundary widened to read it. No new AWS service.
- *The API calls a second Lambda asynchronously.* No new resource type.
  An event is lost if the API dies between its write and the call, so
  every consumer needs its own "find what was missed" path.

### A4. How the client is rendered

`web/` has no build step and `CLAUDE.md` says it keeps none. The
prototype is about twenty screens with gestures and shared-element
transitions; the desk's `el()` helper does not scale to that.

- *No build step, plus a small renderer kept in the repo (recommended):*
  Preact with `htm`, about 15 KB, self-hosted under `web/vendor/` with a
  checksum, the way ONNX Runtime is. No toolchain, no CDN.
- *Plain DOM code as today.* No new dependency; more code, more bugs in
  state handling.
- *A build step (Vite, React or Svelte).* The usual choice in industry.
  Changes a `CLAUDE.md` rule, the CI, `native_bundle.py` and the tests.

May proceed on the recommendation; the first client milestone (E0) is
where it becomes expensive to change.

### A5. Push notifications

- *Straight to Apple from the events Lambda (recommended):* one secret
  (the `.p8` key) set with `set-secret.sh`, no new AWS resource type.
- *SNS mobile push:* AWS keeps the device list, but the platform
  application holds the key, and Terraform would put it in the state,
  which `CLAUDE.md` forbids. It would have to be made by script.

### A6. A custom domain

The prototype's invite link is `bgucats.app/i/…`. A domain is also what
Apple's universal links, the privacy policy address and printed posters
need. The organization's allowlist keeps domain registration off on
purpose, so the domain is bought at an outside registrar, and `acm` goes
onto the allowlist for the certificate (an `infra/org` change).

- *Buy now, wire at N4 (recommended).* Until then invite links use the
  CloudFront address.
- *Later.* Invite links are ugly for the beta; universal links wait.

---

## Product

### D1. Who may sign up

Today: Google only, and only emails on the allowlist. The prototype's
sign-out text says "sign back in with your BGU email".

- *BGU Google accounts (`@post.bgu.ac.il`, `@bgu.ac.il`), plus anyone an
  admin or an invite link lets in (recommended).* Real one-per-person
  identity, which is also spec §9.1's answer to honest votes.
- *Any Google account.* Easiest; votes and the leaderboard are then only
  as honest as free accounts allow.
- *Invite only.*

**Sign in with Apple:** Apple's review (guideline 4.8) expects an
equivalent option beside Google, and external TestFlight goes through
review. Apple can hide the person's email, which defeats a domain check.
Recommended: add it when going external (L2), and let a hidden-email
Apple account in only through an invite link.

**A login for Apple's reviewer** is needed either way (O16).

Staging stays on its allowlist whatever is chosen here.

### D2. Internal or external TestFlight

- *Internal:* up to 100 people who are members of your App Store Connect
  team. No review. Right for the first builds.
- *External:* up to 10,000 by a public link. Each first build of a
  version passes Beta App Review, which applies the App Store's rules:
  report and block for user content (1.2), account deletion (5.1.1), a
  privacy policy, Sign in with Apple (4.8), a reviewer's login.

Recommended: internal until the launch gates (L1, L2) are met.

### D3. Whose posts are in the feed

The prototype's feed shows friends, says "friends see roughly where", and
ranks friends against each other. It does not say whether a stranger's
post appears.

- *The whole campus, friends marked, location to friends only
  (recommended).* A new person with no friends still sees a living feed;
  fifty cats do not make enough posts to split.
- *Friends and yourself only.* An empty app until you have friends.
- *Both, with a switch.* Needs a control the design does not have.

### D4. How people become friends

The prototype adds a friend with one tap and says anyone who joins with
your link "becomes your friend automatically".

- *Invite link: instant. Everything else (contacts, search): a request
  the other person accepts (recommended).* Sharing your link is consent.
  Being in someone's phone book is not, and a friend sees where you post.
- *Always instant, as drawn.*
- *Always by request.*

By-request needs two screens the design lacks: incoming requests, and a
pending state on the button.

### D5. Phone number and contact matching

The prototype: add your number "so friends who have it can find you";
"Find from contacts"; "numbers are only matched, never stored". It has no
step that proves a number is yours.

Without proof, anyone can type someone else's number and appear in that
person's friends' contact lists. With proof, each sign-up costs an SMS,
and the organization's rules cap SMS at $1 a month until you raise it.

- *Leave both out of the first build; invite links only (recommended).*
- *Ship it with an SMS code* (O17: SNS text messaging to Israel, a
  spending limit, possibly a sender name to register).
- *Ship it unproven for the internal beta only,* marked as such.

### D6. Who names a cat

Spec §9.2: any suggestion goes to an admin first, "the review step is not
optional". The prototype: suggest, it is in the poll, the leader is the
cat's name ("Named by vote · 128 of 235").

- *The poll leads. A suggestion enters the poll once moderation passes
  it; an admin can remove an option or lock a cat's name (recommended).*
  While moderation is in shadow (M2), every suggestion waits for an
  admin, which is spec §9.2 exactly.
- *Admin approves every suggestion, always.*
- *Admin names; the poll is advice.*

### D7. A new cat proposed from the camera

`CLAUDE.md`: cats are admin-curated. The prototype: "Add cat & create a
post", "New cat added — thanks!".

Planned either way: the person's "new cat" is a **proposal**; an admin
approves it as a new cat or merges it into an existing one, in the desk.
The open-set rule already says a false "new cat" costs one merge.

- *The post is public at once, tagged NEW; the cat is in the gallery and
  on the map only after approval (recommended).*
- *The cat is public at once.* Duplicates of existing cats will appear.
- *Nothing is public until approval.*

### D8. When "met" counts

"Found 23 cats", the podium and several badges count cats a person met.
A person's claim is unchecked; an admin's label comes hours later.

- *Count at once; take it back if the label says another cat or the
  session is rejected (recommended).* The reward is immediate, which is
  what brings re-encounters, and the board cannot be padded for long.
- *Count only after a label.* Honest and slow.
- *Count the claim, never correct.*

### D9. GPA

Every cat has a "GPA / 4", the gallery sorts by it, "Grade a cat" earns a
point, and there is no screen to give a grade. Needed from the design:
where the control is, the scale (1–4? halves?), whether a grade can be
changed, whether your own grade is shown. And one sentence on what is
being graded, because a low score on a living animal reads differently
from a low score on a photo.

### D10. The feeding log

"Feed a cat — log food or water you left out, +10", the largest reward in
the app, with no screen. Before designing it: does the university or the
people who care for the cats want feeding encouraged? Ten points for an
unchecked tap will also be farmed. Options: design it; drop it from the
first build (recommended until the policy question is answered); make it
a check-in at a known feeding spot.

### D11. Badges, points, levels

The prototype names eight badges, three ways to earn points and "Level 4
· Campus Scout". It does not say what earns a badge or where levels start.
`01-product.md` proposes rules. May proceed on them; they are one data
file.

### D12. Extra frames behind each photo

The prototype's capture is one to four photos. The spec asks for bursts,
and round 1 of the research says variety across encounters matters most,
with several frames per query a free gain.

- *On each press, keep three frames a third of a second apart; show one;
  the others are stored with the encounter for recognition only
  (recommended, off until you say so).*
- *Exactly what is drawn.*

It must be said in the privacy text if on.

### D13. What "Add location" off means

The toggle's off state reads "the spot stays with you". Today every
encounter records the phone's location, rounded to about 100 m, for the
dataset and the admins.

- *Keep recording for the dataset; the toggle only decides whether the
  post shows the area to friends; change the words to "not shown on the
  post" (recommended).*
- *Off means nothing is recorded.* The dataset loses territory data from
  everyone who leaves it off.

### D14. Deleting an account

The dialog: "Your posts, badges, points and friends will be removed for
good." The cat photos that person took are the dataset.

- *Posts, votes, likes, friends and the profile are deleted. The photos
  and their sessions stay, with nothing left that points to the person;
  the dialog and the privacy policy say so (recommended).*
- *Photos are deleted too.* Every departure removes training data and
  templates.
- *The person chooses in the dialog.*

### D15. Reporting

The prototype has Report on a friend, with no reasons, and nothing on a
post. Apple's rule 1.2 for user content needs: report content, block a
person, and someone who acts within 24 hours.

Needed from the design: "Report" in a post's menu, a short list of
reasons, and what the reporter sees after. Needed from you: who reads
reports daily, and at how many reports from different people a post hides
itself until an admin looks (recommended: 3).

### D16. Age and terms

App Store Connect asks for an age rating, and user content needs terms
the person accepts. Recommended: 16 and over, a short terms page with a
zero-tolerance line for abuse, accepted once at first sign-in (O10).

### D17. Languages

The profile offers English, Hebrew, Russian, Arabic. Two of them read
right to left. Recommended: build every screen direction-neutral from the
first line of CSS; ship English and Hebrew at the first external build;
Russian and Arabic when a native speaker has read them (O14).

### D18. What sends a notification

The setting says "New cats nearby, friends' posts". "Nearby" would need
the phone's location while the app is closed, which is a heavy permission
for a small gain. Recommended triggers: a friend posted; someone asked to
be your friend or joined by your link; a name you suggested took the lead;
a cat you proposed was approved. No more than a few a day per person.

---

## Moderation

### M1. Sending people's content to Google

Moderation sends post text, names and photos to Google's API. Free-tier
requests are used to improve Google's products; paid-tier requests are
not (pricing page, read 2026-11-12). The project rounds GPS so a
contributor cannot be located; this is a bigger disclosure than that.

Recommended: yes; paid tier only, in every account including staging;
only content that is about to be public is sent (not the whole dataset);
the privacy policy names Google as a processor.

### M2. When moderation starts acting

`06-moderation.md` runs it in **shadow** first: verdicts are recorded and
an admin decides everything. It moves to **enforce** when a gold set of
names in four languages (O11) and two weeks of real traffic show the
thresholds work. You flip the flag. May proceed in shadow.

### M3. If Google does not answer

- *The item waits for an admin and is not public (recommended).*
- *The item is published and checked later.*

### M4. A person's face in a cat photo

- *Hidden from the feed until an admin looks; the photographer still sees
  their post (recommended).*
- *Published; flagged for an admin.*
- *Blurred automatically.* More code, and a wrong blur ruins a cat photo.

---

## Re-ranking

### K1. The query photo goes to Google while the person waits

Live re-ranking sends a small copy of the photo just taken, with photos
of the candidate cats, to Decision 1. Same disclosure as M1, but in real
time and for every scan. The research and shadow stages (R0–R2) only use
photos already uploaded.

### K2. The bar

`07-rerank.md` proposes: live only if, on at least 100 labeled encounters
of known cats, the right cat is first at least 10 points more often than
with the embedding alone, and in the top three no less often. Thirteen
sessions, which is what exists today, cannot show that.

### K3. A ceiling on spend

Google's bill is outside the AWS budgets. Recommended: a counter in the
table that stops Decision 1 calls at $2 a day per account (moderation
then falls to M3, re-ranking simply does not run), plus a budget alert in
Google Cloud (O5).

---

## Platform

### P1. AWS budgets

$10 emails, $20 freezes changes, $40 stops the API. A public app with
photos will stay far under that at campus size
(`02-architecture.md`, "What it costs"). Revisit at L2 with a month of
real numbers; a stopped API is then an outage for real users.

### P2. When production gets it

- *From the start, dark: every pull request merges, staging runs it,
  production can be promoted at any tag because the flags are off there;
  the app turns on in production at L3 (recommended).* Production keeps
  receiving fixes.
- *Hold all promotes until the app is done.* Production falls weeks
  behind `main`, and the first promote in the project's history would
  also be its largest.

The first promote has still never been made (`docs/ROADMAP.md`). Do it
before F1 (O3).

### P3. `CLAUDE.md`'s rules

This plan lifts "no browse, identify, voting or polls yet", amends "cats
are admin-curated" with proposals, and adds a third role. Recommended:
you agree in principle now; each pull request that lifts a rule edits
that rule in the same change, so the file never promises something the
code does not do.
