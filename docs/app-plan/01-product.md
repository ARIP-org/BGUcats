# What the app is: the prototype, screen by screen

Read from the prototype at version `1794478681-698e` (2026-11-12). Names
in `code` are the prototype's own files and props, so a session can find
the source. Sample names and numbers in the prototype (Maya, Professor
Pumpkin, 1,240 points) are placeholders, not data.

Each screen lists what it **shows**, what a person can **do**, and which
routes of `04-api.md` serve it.

## The frame

Three tabs in a glass bar (`<nav>` in `Feed.dc.html`): **Cats** (the
feed), **Scan a cat** (opens the camera), **Home**. The bar shrinks to
the current tab's pill while scrolling down and returns on scrolling up.
The selected tab sits under a "lens" that can be dragged between tabs.

Four themes: BGU light and dark, "cat coats" light and dark
(`themes()` in `Feed.dc.html` holds every colour). Four languages in the
profile: English, עברית, Русский, العربية.

## Cats tab: the feed

**Shows,** newest first:

- **Cat of the day:** one cat's photo and name, "Watch" opens its page.
- **A post:** who ("Maya"), "met *Professor Pumpkin*" or "posted a photo"
  when no cat is tagged, a "NEW CAT" mark for a proposal, one to four
  photos with a "1/3" counter, a like button with its count, the
  description (up to 280 characters), the time, and the area ("Near
  Aranne Library") when the author shared it.
- **A name-vote card:** "Daniel and Noa voted to call *Professor Pumpkin*
  'Mango'", the poll's options with percentages and the initials of
  friends who chose each, "128 votes · You and 2 friends voted",
  "All names" opens the cat's page.

**Does:** like and unlike; tap a photo for a menu (**See the cat**,
**Show on map**); tap the cat's name; vote from a card; three buttons at
the top: open the gallery, search cats, add (a new post, see below).

**Routes:** `GET /feed`, `PUT`/`DELETE /posts/{id}/like`,
`PUT /cats/{id}/vote`.

## Cats tab: the gallery (`start-page="gallery"`)

**Shows:** every cat as a two-column wall of photos of unequal heights.
**Does:** open a cat; search; new post; sort by **Highest GPA**, **Most
posts**, **Recently seen**, **Newest on campus**, **Name A–Z**. Swiping
from the edge returns to the feed.

**Routes:** `GET /cats` once; sorting and searching happen on the phone
(about fifty cats).

## A cat's page (`start-page="cat"`)

**Shows:** a large photo; the name that leads the poll and "Named by
vote · 128 of 235"; "GPA 3.9 / 4"; "Usually near Building 96"; a short
description; three numbers (**Posts**, **Likes**, **Last seen**); the
**name poll** (every option with its votes, the leader marked, your
choice ringed); **recent posts** (who, when).

**Does:** vote, change the vote, take it back (tap your choice again);
**suggest a name** (up to 24 characters; a suggestion that matches an
existing option, ignoring case, becomes a vote for it); show on map.

**Routes:** `GET /cats/{id}`, `GET /cats/{id}/names`,
`POST /cats/{id}/names`, `PUT /cats/{id}/vote`, `GET /cats/{id}/posts`.

## The map (`start-page="map"`)

A drawn map of the campus, not a map service: ground, greens, roads,
buildings in the theme's colours, dragged with a finger. Five habitats
(Building 96 · Engineering, Aranne Library, Student Union, Dorms, Sports
lawn), each a tappable area, with the cats that live there as round
photos. A sheet names the selected habitat, "2 cats live here" or "No
named cats here yet — spotted one? Scan it.", and lists its cats with
their GPA.

Not in the prototype yet, decided 2026-11-12 (D10): the campus's
**feeding spots**, marked on the map so people know where to feed.

**Routes:** none of its own: `GET /cats` and the regions file, which
also lists the feeding spots.

## Scan a cat: the camera (`Main.dc.html`, `Scanner.dc.html`)

The camera opens from the centre tab as a circle growing from the
button: a viewfinder with four corner brackets, flash, a paw-print
shutter, close. One press takes one photo and moves on.

## After the photo (`Capture.dc.html`)

Four pages that slide sideways.

**1 · Which cat?** Your photo in the corner; **three large candidate
photos** (no names, no percentages); under "Not one of these?" a **New
cat** tile and every campus cat as a grid. Tap one to go on. Retake,
close.

**2a · "You met Simba".** The cat's photo with yours overlapping;
"Usually near Aranne Library · met 37 times"; the cat's **name poll**,
marked optional, voting in place; **Create a post**; **Save without
posting**.

**2b · New cat.** One to four photos ("Take another", "2 of 4", remove);
**Name idea** (optional, 24 characters, "e.g. Hummus"); **Coat** (one
of Ginger, Black, White, Gray, Tabby, Calico, Tuxedo); **Where does it
hang out?** (one of the five places or "Somewhere else"); **Anything
else?** (any of Friendly, Shy, Ear-tipped, Kitten, Has a collar);
**Add cat & create a post**; **Add cat without posting**.

**3 · New post.** The tagged cat with **Change** (and NEW for a
proposal); the photos, numbered, up to four; **Description** (optional,
280 characters, "What was the cat up to?"); **Add location** (a switch;
on: "Friends see roughly where — never the exact spot" and a small map
with "Near Aranne Library"; off: "Off · the spot stays with you", see
D13); **Post**; **Save without posting**.

**Post from "+" (no scan)** (`entry="post"`): the same page 3, starting
empty: **Take a photo**, **Tag a cat** (optional; page 4 lists every cat
by name), description, location. The tag can be removed.

**After:** a toast: "Posted to the feed", "Simba saved to your cats", or
"New cat added — thanks!". A new post appears at the top of your feed at
once.

**What each ending writes** (`04-api.md`, "The capture flow"):

| Ending | Encounter and photos | Pick | Proposal | Post |
|---|---|---|---|---|
| Save without posting | yes | the cat chosen | | |
| Create a post | yes | the cat chosen | | yes |
| Add cat without posting | yes | "new" | yes | |
| Add cat & create a post | yes | "new" | yes | yes |
| Post from +, no tag | yes | none | | yes |
| Post from +, tagged | yes | the cat chosen | | yes |

The encounter, its photos and the pick are today's Capture, unchanged:
the same write order, the same outbox, the same measurement of "pick from
3". The post and the proposal are new and sit on top.

**A new cat is not public until an admin approves it** (D7, answered
2026-11-12). In the two "Add cat" endings the proposal goes to the desk;
a post written with it is held, shown only to its author as waiting, and
published under the approved (or merged-into) cat once the admin
decides. The toast "New cat added — thanks!" needs new words for that
moment; and the owner is still to confirm whether the "& create a post"
button stays at all (`DECISIONS.md`, D7).

## Home tab

**Shows:** a profile bar (photo, name, "18 cats met · since Nov 2026")
and a Friends button, both shrinking on scroll; a **Friends card** with
the top three of you and your friends by cats found, each with their
three latest cats; an **Achievements card** ("1,240 points · 6 badges");
**My posts** as a grid ("18 total").

**Does:** the profile bar opens the profile; the Friends button, or
pressing and holding the card, opens Friends; the Achievements card opens
the achievements sheet.

**Routes:** `GET /me`, `GET /friends`, `GET /me/posts`.

## Profile (`mode="profile"`)

**Shows and does:**

- **Photo:** take one, choose from the library, remove.
- **Name** (30 characters), and "@sasha.bgu · since Nov 2026" (the
  username is shown, not edited).
- **Phone:** "Add phone number" → "🇮🇱 +972" and a field → "Done".
  "Add your number so friends who have it can find you. It's never shown
  on your profile." (D5.)
- **Achievements** summary with six badges; opens the sheet.
- **My posts.**
- **Settings:** Notifications (a switch: "New cats nearby, friends'
  posts" / "Off — you won't get alerts"), Language, Interface theme.
- **Sign out** ("You can sign back in with your BGU email anytime."),
  **Privacy policy**, **Delete account** ("Your posts, badges, points
  and friends will be removed for good. This can't be undone.").
- "BGU Cats 1.0 · Made on campus".

**Routes:** `GET`/`PATCH /me`, the avatar and phone routes,
`DELETE /me`.

## Friends (`mode="friends"`)

**Shows:** "This month" / "All time"; a **podium** of three; a search
field ("Search by name or username"); **All friends**, each with a name,
"@user · found 23 cats" and a ••• menu.

**Does:** open a friend; ••• → **Remove from friends**, **Block**,
**Report**; **Add friend** →

- **Invite friends:** "Anyone who joins with your link becomes your
  friend automatically.", the link (`bgucats.app/i/sasha-0224`),
  **Copy link**, **Share…**.
- **Find from contacts:** "BGU Cats needs access to your contacts to
  show who's already here. Numbers are only matched, never stored." →
  **Allow contact access** → "On BGU Cats: 3 of your contacts are here",
  each with "@user · 2 mutual friends" and **Add** / **Added**.

**A friend's page:** initials, name, @user, "23 cats found", "Friends
since Sep 2026", their latest posts.

**Routes:** `GET /friends`, `GET /users/{id}`, `DELETE /friends/{id}`,
`PUT /blocks/{id}`, `POST /reports`, `GET /me/invite`,
`POST /invites/{code}/accept`, `POST /contacts/match`.

## Achievements (`mode="achievements"`)

**Shows:** "1,240 social points"; "Level 4 · Campus Scout", "260 to
Level 5" and a bar; three numbers (**Cats met**, **Cats fed**, **Cats
graded**); **Badges**, "6 of 8": First Meow, Snack Giver, Night Owl,
Critic, Explorer, Name Giver, Dean's List, Cat Whisperer; **How you earn
points:** Feed a cat +10, Meet & post a cat +5, Grade a cat +1.

**Routes:** `GET /achievements`.

### The rules (D11, accepted 2026-11-12, adjusted for D9 and D10)

The prototype names these and does not define them.

| Badge | Earned when |
|---|---|
| First Meow | your first saved encounter |
| Name Giver | a name you suggested has led its poll |
| Night Owl | an encounter between 22:00 and 05:00, Israel time |
| Explorer | encounters in every campus region |
| Snack Giver | your first feeding |
| Dean's List | you met every cat whose GPA is 3.5 or more |
| Cat Whisperer | the same cat met on 10 different days |
| Critic | *has no meaning since D9: nobody grades.* Proposed: you voted in 10 name polls. Not built until the designer confirms or renames it |

Points: +5 for an encounter that became a post, once per cat per day, so
ten photos of one cat in an hour are five points; +10 per feeding, for at
most two feedings a day. Levels: a table of thresholds in the same data
file (level 5 at 1,500 if level 4 is 1,240 with 260 to go); names for
levels other than "Campus Scout" are the owner's.

"Met" follows D8: counted at once, taken back if the label disagrees.

Two things the prototype shows that D9 left without a meaning, for the
designer: the row "Grade a cat +1" and the counter "Cats graded".
Proposed: "Vote on a name +1" (once per cat) and "Names voted". Until
confirmed, the row is not shown and the counter shows the proposed one
only on staging.

### GPA (D9, answered 2026-11-12)

Nobody grades a cat. GPA is a popularity grade the app works out, shown
where the prototype shows it (a cat's page, the map's habitat sheet, the
gallery's "Highest GPA" sort).

- **A cat's popularity** = its counted encounters in the current month
  and the two before, plus the points those encounters earned. One
  person meeting the cat on one day is one encounter, however many
  photos; if it became a post it also earned 5 points. So a met-and-posted
  day is worth 6, a met-and-saved day 1. "Counted" follows D8: a claim
  counts at once and is taken back if the label disagrees.
- **The grade** = `1 + 3 × √(popularity ÷ the most popular cat's)`, to
  one decimal. The most popular cat has 4.0. The square root keeps the
  middle of the campus from being crushed against 1.0 by one famous cat.
- **A cat nobody met in that time shows "—",** not a low number, and
  sorts last.
- Feedings do not count: they would grade the feeding spot, not the cat.

Kept as a counter per cat per month by the events Lambda, corrected when
a label corrects an encounter; the grade is worked out when the cats are
read. One flag, `gpa`, hides it everywhere if the owner decides it is not
needed.

It is a grade of attention, not of the cat. A shy cat will always score
low. If that reads badly once real cats have numbers, hiding it is one
line.

### Feeding (D10, answered 2026-11-12)

The campus has set feeding spots. People log that they fed a cat, and
everyone can see when a cat was last fed.

- **Feeding spots** are a list the owner supplies (O12): a name and a
  place for each. They are drawn on the map, in every region.
- **Logging a feeding:** "I fed this cat", for one cat, optionally at one
  spot. No photo needed.
- **A cat's page** shows "Last fed 3 hours ago · logged by people using
  the app", or "No feeding logged yet".
- **Points:** +10, for at most two feedings a day per person. More can be
  logged; they earn nothing.
- **Limits:** six logs a day per person; one per cat per person every
  four hours.
- A feeding can be reported like anything else, and an admin can remove
  one, which puts "last fed" back to the one before.

Not designed, so not built on the client until it is (G6): where the
control is, and what a feeding spot looks like on the map.

---

## What the design leaves out

Gaps a session must not fill by guessing. "Plan" is what to build
meanwhile; "Ask" is the owner's (`DECISIONS.md`) or the designer's.

| # | Gap | Plan meanwhile |
|---|---|---|
| G1 | **Sign-in and first run.** No sign-in screen, no place where a username is chosen, no acceptance of terms, no request for the camera or notifications | The existing sign-in screen, restyled with the new tokens. The backend supports a username chosen once (`PUT /me/username`). First run is the designer's next job |
| G2 | **Report a post.** The post menu has "See the cat" and "Show on map" only. Apple's rule 1.2 needs it (D15) | Build the route and the desk queue (B8). Do not add the menu item until it is designed |
| G3 | **Report reasons, and what the reporter sees after.** "Report" closes the menu and nothing else | Route takes a reason from a fixed list; UI waits for design |
| G4 | **Blocked people.** One can block; there is no list to unblock from | Route exists; UI waits |
| G5 | **What replaces grading** (D9: GPA is computed, nobody gives one): the row "Grade a cat +1", the counter "Cats graded" and the badge "Critic" have nothing behind them | GPA itself is built. The three leftovers are hidden until the designer confirms the proposed replacements ("GPA", above) |
| G6 | **Feeding** (D10: build it): no control to log a feeding, no drawing of a feeding spot on the map, no "last fed" line on a cat's page | The backend is built (B7c). The screens wait for the design; "Cats fed" counts from the first log |
| G7 | **Friend requests** (D4), if not instant: no incoming list, no pending state | Wait for D4 |
| G8 | **Entering an invite code by hand.** A link tapped before the app is installed loses its code | A "Have an invite code?" field is needed; ask |
| G9 | **Search cats:** a button, no results screen | Filter the gallery in place as the person types; confirm with the designer |
| G10 | **Empty and waiting states:** no posts yet, no friends yet, loading, offline, "your post is being checked", "this name was not accepted", upload progress | Build them plainly from existing components (`05-client.md`, "States the design does not draw") and show the owner screenshots |
| G11 | **Deleting or editing your own post** | A route to delete exists; UI waits. No editing |
| G12 | **Several photos in the feed:** a "1/3" counter, no way shown to see the others | Horizontal swipe within the photo; confirm |
| G13 | **A new cat with no name:** the post reads "met This new cat" | Ask for the wording |
| G14 | **The labeling desk's place.** The prototype has no admin entry | A "Labeling desk" row in the profile, shown to admins only |
| G15 | **Notifications:** no permission prompt screen, no in-app list | Ask for the system permission the first time the switch is turned on; no in-app list |
| G16 | **Username:** shown as "@sasha.bgu", never set or changed | Chosen once at first run (G1); until then derived from the email's local part plus digits |
| G17 | **What a non-friend's profile shows** | Name, username, cats found. Posts only if D3 makes posts public |
| G18 | **"Not sure" and "Skip"** exist in today's Capture and not in the new flow | "Save without posting" after choosing nothing is not offered by the design: closing the flow keeps the photos as an encounter with no pick |

## What changed in the design on 2026-11-12, and why it matters

Between the morning and the evening read, the prototype gained the post
**description** (280 characters), the **new-cat form**, and **posting
without scanning**. `docs/moderation.md` was written against the morning
version and said the design had no free-text post field. It has one now.
The moderation surface is: description (280), name suggestion and name
idea (24), display name (30), username, post photos, avatar. The
"92% match" the morning version showed is gone: the candidate screen now
shows three photos and no numbers, which is the honest version.
