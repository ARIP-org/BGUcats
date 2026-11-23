# Notes worth keeping

Things this project learned by getting them wrong, or by being surprised.
Each is short, and says where the full story is. The rules that came out
of them are in `CLAUDE.md`; this file is the reasons and the traps, for
whoever works here next, person or agent. Add to it when something costs
an hour that a sentence would have saved.

## DynamoDB

- **A read can miss a write made milliseconds earlier.** The default read
  may answer from a copy that has not caught up. The phone sends an
  encounter and then its first photo back to back; the second call found
  "no such encounter" one time in twelve, answered 404, and the app's
  outbox treats a 404 as final, so the photo was dropped. Every read of one
  record that decides "exists or not" is now strongly consistent (`_item`
  in `src/admin/handler.py`). `docs/deploy.md`, History, 2026-11-10.
- **An index can never be read consistently.** A count taken through an
  index right after the write that changes it can be short, and if that
  number is then stored, it stays wrong. Counts now add what the call
  itself wrote (issue #55). Lists from an index may lag for a moment;
  nothing may be decided on an item's absence from a list.
- **A status code is a contract with the retry logic.** "404, try later"
  and "404, never" look the same to a client. Before answering 4xx, ask
  what the outbox will do with it (`isPermanent` in `web/outbox.js`).
- **"Not set" and "set to null" are different to a condition.** Every
  session is written with `catId = null`; a condition that only checked
  `attribute_not_exists` refused them all as already labeled (2026-10-29).
- **Invisible characters belong in escapes.** Tests about direction
  overrides and zero-width spaces were written with `\u202e` and came out
  of the editor as the characters themselves, which no reviewer can see.
  Ruff refuses them (PLE2502, PLE2515); write every such character as an
  escape, and check with `od -c` if a line looks shorter than it should.
- **A boto3 resource's client takes plain values.** `table.meta.client`
  is the low-level client with the resource's conversion still attached,
  so a transaction's items are written as plain dicts, exactly as for
  `table.put_item`. Converting them with `TypeSerializer` first converts
  them twice; moto reports it only as "cancellation reasons [TypeError]"
  on every item (2026-11-12, F4).
- **A count handed over to someone else must stop being everyone's.** An
  admin removes a name from a poll; the events Lambda then takes its
  votes off the cat's total as a whole. If a voter leaving that name in
  between still took their one vote off the option, the total would lose
  it once too few. From the moment an option is `removed`, only the
  events Lambda changes its count (`_move_vote` in `src/app/handler.py`,
  `remove_name` in `src/events/handler.py`; B4b, 2026-11-13).
- **`ADD` cannot make an entry in a map that is not there.** A counter
  per month as `pop.#month` fails on the first write of each item
  ("document path invalid"), and making the map first is a second write
  that can race. One plain attribute a month (`pop2026-11`) needs
  neither (B7b, 2026-11-13).
- **A person's things are not all under their key.** Deleting an
  account (B10a) found likes kept only under the post
  (`POST#…/LIKE#{userId}`), votes, names and feedings under the cat, and
  report rows under the thing reported, with no index by person, and no
  role allowed to Scan. The job finds them by walking every listed
  person's posts and every cat, and it deletes the likes on a deleted
  person's posts so that no like is left on a post nobody can list. A new
  item that names a person somewhere other than `USER#{id}` must be
  findable from that person, and `delete_account` must learn it: the
  test that scans for the id after a deletion is what notices.
- **Mocks are always consistent.** moto answers every read with the latest
  write, so none of the above can fail in a unit test. They were found by
  running real calls against a real table.

## Deploying and Terraform

- **The first deploy into a brand-new account fails once, on purpose.**
  The user pool's client needs the Google provider, which can only be
  created after the pool exists. Run `set-secret.sh google-oauth`, re-run
  the job. `docs/MANUAL_STEPS.md`, 12f.
- **Several merges in a row cancel the deploys in between.** GitHub keeps
  only the newest waiting run of a concurrency group. That is fine: the
  last deploy carries every merge. But only the last commit gets the
  `deployed/staging` mark, so that is the one to tag.
- **The same source must give the same zip.** Otherwise every plan shows
  every Lambda changing and a real change hides in the noise. A build on a
  laptop still differs from CI's, so a local plan shows Lambda updates
  that are not real (`Makefile`, `lambda-compile`).
- **CI plans without the state lock.** With it, CI and a deploy running at
  the same time failed each other (2026-11-02).
- **A pipe hides a failure.** A workflow `run:` step has no `pipefail`
  unless it sets it: `python smoke.py | tee log` reports tee's success.
- **A role's inline policies share one limit,** 10,240 characters in
  total, and a managed policy has 6,144. IAM says so at apply, part-way
  through. Measured offline on 2026-11-12 with a mocked provider
  (`infra/bootstrap/tests`): the deploy role was 8,407, and 8,983 after
  the app plan's F1. The test fails past 10,000, and both
  `bootstrap-apply.sh` and CI run it, so the next big addition shows up
  as a red check that says "move statements into a managed policy".
- **A kind of resource joins the allowlist with its first resource, not
  before.** The plan check's own test holds
  `allowed-resource-types.txt` to exactly what `infra/main` declares, so
  a guardrail pull request that adds a line ahead of the resource goes
  red. The cost rule for a kind (`check_plan.py`) can and should come
  first.
- **Two IAM surprises in the alerts work:** an SNS subscription is not a
  resource a policy can name (`Resource: "*"` or nothing), and
  `DescribeAlarms` is checked against every alarm in the account, not the
  ones asked for.
- **CloudWatch cannot publish to a topic encrypted with AWS's own SNS
  key.** The alerts topic is unencrypted for that reason
  (`infra/main/alarms.tf`).
- **The site's files were a list by hand in `infra/main/web.tf`.** A new
  file in `web/` passed every local test, because the local app serves
  the folder, and would have been missing on staging. Found in E0, when
  `web/lib/` arrived; since then Terraform uploads every file under
  `web/`, typed by extension, and an unknown extension fails the plan.
- **A Lambda that uses `zoneinfo` ships `tzdata`.** The runtime image
  may have no system time zones, and then `ZoneInfo("Asia/Jerusalem")`
  at import fails every call. The member API went to staging without it
  (B2), and nothing noticed: the smoke test goes through the desk's
  pipeline, not `/api/v1`. `tests/common/test_packaging.py` checks it
  since B3b.
- **Revoking the bot's token also dropped its webhook,** silently
  (2026-10-31). A script that sets a secret must check what depended on
  the old one.

## Guardrails

- **A denylist of expensive services is never complete.** AWS has
  hundreds and adds more. The organization allows only what the project
  uses; everything else is denied by default (`infra/org/scp.tf`).
- **Before attaching a policy that denies, read the history.** Every call
  the account ever made is in CloudTrail. All 22,568 of production's were
  checked against the allowlist before it went onto the root.
- **Resource Explorer looks like an intruder.** AWS's own indexing role
  lists RDS, SageMaker, EKS and Bedrock in an account that uses none of
  them. Check who made a call before worrying about it.
- **A budget acts hours late.** The limit is "$40 plus whatever was spent
  before AWS noticed". The allowlist and the quotas are what keep that
  remainder small.
- **"Only the owner can release" means "only an admin identity can".**
  The tag rule lets the admin role create `v*` tags. Any session acting as
  the owner is an admin. This is the reason the machine user exists.

## The iPhone app

- **API Gateway's CORS takes only `http://`, `https://` or `*` as an
  origin.** An app's web view has neither: Capacitor serves the pages
  from `capacitor://localhost`, and iOS does not let an app serve them
  from `https`. A plan cannot show this; the apply fails with "Invalid
  format for origin". S3's CORS takes the origin as it is, and Cognito's
  token endpoint answers any origin.
- **A CORS configuration does not answer a preflight on a route with an
  authorizer.** `ANY /api/{proxy+}` matches `OPTIONS` too, so the web
  view's preflight, which never carries a token, got the JWT authorizer's
  401 and every call from the first TestFlight build failed with Safari's
  "Load failed" (2026-11-11). `OPTIONS /api/{proxy+}` without an authorizer
  (`admin_api.tf`) is half the fix. **Nor does API Gateway answer the
  preflight on that route by itself:** it invokes the route's Lambda and
  only adds the CORS headers to the answer. Ours asked for the caller's
  email first and said 401, so the app still failed on every call, for two
  days, behind a fix that had changed only whose 401 it was (2026-11-13).
  The handlers now answer `OPTIONS` 204 before anything else (`preflight`
  in `src/common/api.py`). Both times the local test server had answered
  preflights itself, so the tests passed; it now hands them to the real
  handlers, and the deploy job sends a real preflight to each API after
  every apply ("The front door answers"). A fix to something only the
  deployed API does is not done until that `curl` has been run against it.
- **`*` on an API that takes a token in a header gives nothing away.**
  CORS decides whether a page may read an answer, and matters where a
  browser attaches credentials by itself (cookies). Here the page adds the
  token, another site's page has none, and credentials are off.
- **Everything behind the `testflight` environment is tested only from
  `main`.** The first upload job could not run before its merge. Keep
  what needs the key small, and put everything else in the `simulator`
  job, which a pull request can run.
- **An error message should use the name the reader has to type.** The
  workflow said "no TEAM_ID", its own name for the variable
  `APPLE_TEAM_ID`, and a secret called `TEAM_ID` was added.
- **A permission question asked inside the tap that opens a screen can
  freeze an installed web app.** The member app's capture flow asked for
  the phone's location in the same task as the tap on "+" or "Scan a
  cat". On the owner's iPhone, in the app installed from the staging
  site (a fresh install, so the question was new), nothing appeared and
  no touch worked until the app was closed; Safari's tab was fine, and so
  was the next launch, which resumes the saved flow without asking
  (2026-11-13, before an iOS update). Not reproducible here: Chromium
  with touch and WebKitGTK both work, so the cause is the best
  explanation, not a measurement. What the app does about it
  (`web/social/asking.js`): the screen is drawn first; the camera is
  asked for, then the place, one question at a time; and a question left
  unanswered when the app was closed is not asked again by itself, with a
  line saying so and a way to ask again. A page cannot see itself
  freeze, so the fix is to make the freeze a one-off.
- **That was not the cause, or not the whole of it: the freeze was the
  recognition model starting on the page's own thread** (2026-11-14).
  The owner updated iOS and "+" and "Scan a cat" still froze. Both
  called `prepareForCapture` as the flow opened, and that reads 30 MB,
  checks it and builds the model's session in WebAssembly, on the thread
  that draws and takes touches: about five seconds blocked in Chromium
  slowed four times, 1.3 s in WebKitGTK on a fast machine, with the new
  screen still at the invisible first frame of its opening animation. So
  nothing appeared and nothing answered. It also explains what the first
  diagnosis took as support: the next launch resumed the saved flow,
  which skipped the model as well as the questions. Now the member app
  runs the model in the runtime's own worker (`worker: true`,
  `ort.env.wasm.proxy`; 52 ms blocked in WebKitGTK, the same scores to
  the last digit) and starts it 0.9 s after the screen is drawn. The
  worker is made from a blob, so the runtime's files need a whole
  address, not a path. For a few hours a phone where the worker failed once
  remembered it and used the page's thread from its next launch: one bad
  moment, and the phone was back on the path that froze it, for good,
  with nothing on screen to say so. A fallback must not be the failure
  it replaces. Now a start that fails in the worker means no guesses
  that time, and the mark is removed from any phone that kept it. The
  desk still runs the model on the page, as it has since October.
- **`--platform` means that tag and no older one.** The Lambda builds
  install with `--platform manylinux_2_28_x86_64`, and pip then takes
  only wheels carrying exactly that tag. cffi's releases carry the older
  `manylinux2014` one, so for the events Lambda (B9) pip quietly chose a
  beta of cffi that happened to have the newer tag. `build-events` names
  both platforms; every package is pinned, the indirect ones too, so a
  new release cannot change the zip.
- **The freeze was a piece of a flow, kept by the phone** (found
  2026-11-15, from the first App info the owner pasted; it took one
  message). The capture flow is kept in localStorage so a reload lands
  where it was. `update()` merged a change into "the flow" without
  asking whether there was one, so a tap that landed after a flow had
  closed wrote the change alone, `{ step: "which", changing: true }`,
  and that was kept. From then on "Scan a cat" and "+" opened the kept
  piece, the first line that read its photos threw, and the flow stayed
  "open" with nothing drawn and the app under it out of reach, at every
  launch. The iPhone app has its own storage and never held the piece,
  which is why it "had no bug". Three things, each enough alone: a
  change with no flow changes nothing; a kept flow that is not whole is
  dropped at the start; a page that cannot be drawn closes the flow and
  says so (`web/social/scan.js`, `tests/web/test_member_flow_kept.py`).
  The model on the page's thread (#94) was real and was not this.
  Anything kept between launches is input from an older self: check it
  as if a stranger sent it.
- **Ask the phone, do not guess.** Three fixes for the owner's phone
  went out on 2026-11-14 without anyone having seen the fault: the model
  in a worker (#94), the visible start (#95), the fallback removed
  (#96). Each fixed something real and none was known to be the cause;
  the owner then said the home-screen app was still broken and the
  TestFlight app was not. Nothing on the phone had been written down, so
  every round cost hours and a guess. Since that evening the page keeps
  its own account ("App info": `app.html`, `web/social/trail.js`),
  including a line each time the screen stops answering. The first
  question about a bug on a phone is now "copy App info after it
  happens".
- **The service worker had never been run by a test.** Every screen test
  blocks it, so two faults sat in `sw.js` unseen: both pages were kept
  under `/index.html` (with no signal the app opened as whichever was
  fetched last), and a page the network neither answered nor refused was
  waited on without limit. `tests/web/test_service_worker.py` runs the
  real worker; Playwright routes the worker's own requests through
  `context.route`, so a request can be made to hang there.
- **A start with nothing on screen cannot be diagnosed from anywhere.**
  The same morning the owner's installed app showed a gray screen, then
  a black one, for three minutes, and I could not say why: staging
  served exactly `main`, the deploy had passed, and both the local app
  and the real site loaded in WebKitGTK. Nothing loads the model at a
  launch. What the code did show: the installed app opens on `/`, which
  fetched the desk's whole script, the settings and a stylesheet from
  Google Fonts before handing over to `app.html`, which fetches some
  thirty files and then makes four requests, three with no time limit,
  with an empty black page throughout. Any one of them stalling is that
  screen. Since 2026-11-14: `/` hands an installed app over before
  fetching anything (it remembers the front door from the last launch);
  `app.html` itself says "Loading…" and, after twelve seconds, which
  step it is on, with "Try again" and "Reset the app on this phone"
  (the service worker and its copy of the app's files, nothing else);
  every step is bounded, and a start that fails says where. The cause on
  that phone is still unknown; the next time, the screen will name it.
- **Two candidate causes that the same evidence fits are one unfinished
  diagnosis.** The first fix was reasoned, not measured, and its note
  said so; the measurement that settled it (a `longtask` observer, the
  published model served to the local app) took twenty minutes and could
  have been made the first time.
- **Nothing here runs Safari.** The screen tests are Chromium. WebKitGTK
  (`apt-get install gir1.2-webkit2-4.1 python3-gi`, run under
  `xvfb-run` with the system's Python 3.12) loads the local app and
  shows JavaScript errors and what is under a point, which rules out the
  engine; it has no touch, no permissions and no home-screen mode, which
  is where the iPhone differed.
- **Glass that changes size stutters.** The tab bar, the search pill,
  Home's profile pill and Friends button folded by animating
  `inline-size`, `block-size`, `inset-*` and `flex-basis` under a
  `backdrop-filter`: every frame of the spring was a layout and a new
  blur, and the owner felt it on the phone (issue 104, 2026-11-21). Their
  glass now changes shape by `clip-path` (`::before`), their rim and shadow
  (`::after`, which a clip would cut off) take the new shape at once and
  fade in as the fold lands, and what is inside moves by `translate`.
  `tests/web/test_member_fold.py` fails on any layout property in their
  transitions. A clip also cuts what is outside it: a border or a
  shadow on the clipped layer disappears. And CSS's own default,
  `transition: all 0s`, names every property: only a transition that
  takes time counts.

## GitHub

- **The author of a pull request cannot approve it.** So whoever writes
  must not be whoever approves: the Fix agent is a GitHub App, hands-on
  sessions are a machine user, and the owner only approves.
- **A workflow started by a push runs the pushed branch's copy of
  itself.** Secrets are safe from an edited workflow only because they
  live in an environment that `main` alone may use.
- **What GitHub's own job token creates starts no workflow.** A label
  added by Triage cannot start Fix, which is the point; a pull request
  opened with that token would get no CI, which is why Fix uses the App's.
- **Dependabot said 164 alerts; it was one package.** Each alert is
  counted once per requirements file, and it never proposed the fix
  because major versions are ignored on purpose. Read the alerts before
  counting them.
- **A fine-grained token fails in pieces.** `gh pr create` needs
  *Contents: read* as well as *Pull requests: write*; `gh pr checks` needs
  *Checks: read*; alerts need their own permission. The error names a
  GraphQL field, not the missing permission.
- **Codespaces secrets load when the codespace starts.** A changed secret
  is the old value until then.
- **A macOS runner's minute counts as about ten.** iOS builds are for
  release candidates, not for every merge.

## Testing

- **A test that fails one run in six is a race, not bad luck.**
  `test_the_cats_screen_lists_every_cat_with_its_cover` failed in CI
  because a screen that waited for its data drew over the one opened since:
  the Queue's late answer replaced Cats. Every screen now checks
  `stillShown()` after its fetch (`web/app.js`), and a test holds the
  Queue's answer back to make the race happen every time (2026-11-11).
- **A seed that goes through the front door is the best first test.**
  `make seed-staging` fills staging by calling its real API, and found the
  dropped-photo bug on its first run. The same code is the smoke test
  after every deploy.
- **moto as a server makes signed URLs real.** The browser tests load
  photos from it and upload to it (`tests/web/localapp.py`). Its state
  lives for the whole process: reset it between app starts.
- **A screen is drawn after its data arrives.** Wait for the words the
  screen should say, not for the tab to look selected.
- **A test seeded with the clock fails at some seconds and passes at the
  rest.** The smoke test's photo was "different every run" by taking the
  time as its seed, but the made-up pictures repeated every 1,800 seeds.
  Four seconds in every 180 it uploaded a byte-for-byte copy of a seeded
  photo, which is a duplicate and leaves the queue: the deploy of #62
  failed on "the new encounter is not in the queue" while CI passed on the
  same commit. Staging's real smoke test had the same odds per seeded
  encounter. Every sample photo now carries its whole seed
  (`sample_photo` in `scripts/seed_campus.py`). A red run that a re-run
  turns green still has a cause.
- **pytest collects anything named `test_*` that a test module imports,**
  including a helper that makes sample photos.
- **Chrome's headless shell never fires Background Sync.** A test of
  background uploads there proves nothing; it needs full Chromium
  (`docs/deploy.md`, History).
- **In the codespace, `playwright install --with-deps` fails** on an
  unsigned package source in the image. Install the browser without
  `--with-deps` and the missing libraries by name.

- **A sleeping browser test holds the page's requests.** The screen tests
  filter every request through a Python function (`context.route` with a
  callable, `tests/web/conftest.py`), and with Playwright's synchronous
  API that function runs only while the test is inside a Playwright call.
  A test that waited with `time.sleep` for the outbox to send a post froze
  every request of the page, and failed by timing (E3, 2026-11-12). Wait
  with `page.wait_for_timeout`.

- **A test that fails one run in five is telling the truth about one
  phone in five.** The area test of 2026-11-13 failed in CI and passed
  here: the phone's GPS answered sometimes before the first photo and
  sometimes a moment after, and in the second case the post page said
  "Near Aranne Library" while the encounter had gone to the server with
  no place. Three windows had to close: the place arriving after the
  encounter was written, while it was being written, and while its
  request was on its way (`placeEncounter` in `web/outbox.js`, a step of
  its own; the server takes a place only for an encounter that has
  none). The test that found the rest answers the GPS by hand, after
  the photo. A timing a test meets by chance deserves a test that
  chooses it.
- **The whole browser suite, before the push, when a shared piece
  changes.** Running only the tests of the screen being changed let two
  failures reach CI that night: a second `role="status"` on the page
  broke a test of another screen that asked for "the" status.
- **Taking a block off a request lets the waiting request through.**
  `page.unroute()` on a route whose handler never answered releases
  what it was holding, so the page carries on by itself. The start's
  test took the block off and then tapped "Try again"; on CI's slower
  machine the app had already started and the button was gone
  (2026-11-14). A request that should answer later gets a handler that
  decides, not an unroute.
- **A screen that changes before its request is sent proves nothing
  about the API.** A like counts on screen at once; the feed's test saw
  the 2, asked the API, and once in CI got 1, on a pull request that
  changed only docs (2026-11-22). A test that then asks the API waits for
  the request's answer first (`page.expect_response`).
- **A screen test that fails once must leave something to read.** On
  2026-11-23 the capture flow's post "did not arrive within the time" in
  one CI run, on a pull request that touched no screen; it passed on
  `main` twice and six times in a row on a session's machine. The log
  showed the encounter arriving and no photo after it, and nothing of
  the browser's side: which step waited could not be told. The outbox
  retries after 2, 5 and 15 seconds, so one request that fails twice is
  already past a test's twenty. A failed member-app test now prints the
  app's own "App info" and every request that failed or was refused
  (`tests/web/conftest.py`, held by `test_failure_report.py`). The next
  failure, an hour later, printed `404 POST /api/encounters/{id}/media`:
  it was the app, not the test (the next entry).
- **The deploy runs the tests with no browser, and CI did not.** A test
  that starts a pytest of its own and expects "1 failed" got "1 skipped"
  on the deploy's machine, where no browser is installed; it had passed
  CI, which has one. The deploy of its own pull request stopped at
  `make test` and staging did not get that merge (2026-11-23, #118; the
  next merge carried the fix). A test that needs a browser takes the
  `browser` fixture, even when it only starts another pytest; and CI now
  runs `tests/web` a second time with `BGUCATS_NO_BROWSER=1`, as the
  deploy sees it. After a merge, "CI is green on `main`" is not "it is
  deployed": the Deploy run's own job is what says so.
- **A queue that reads two stores in two steps reads two moments.** The
  outbox's pass read the encounters, then the photos. The place arriving
  a moment before the first photo started a pass; the encounter and the
  photo were stored between its two reads; the pass saw a photo whose
  encounter it had not read, took it for one that needs none, and sent it
  first. The server said "no such encounter", which the queue takes as
  final, so the photo was given up and the post never went (2026-11-23,
  on `main` since the place began to follow the photo, 2026-11-13; on a
  phone it needs GPS to answer within milliseconds of the first photo).
  The pass now reads the photos first: an encounter is stored before its
  photo, so whatever photo the pass reads, its encounter is in the read
  that follows. `tests/web/test_outbox_order.py` stores the first photo
  after each of the pass's reads in turn; it fails on the old order.
  "It passes when I run it again" was the report of a real bug here.

## Agents and sessions

- **Claude's action runs on some events and stops at the rest.** The
  builder's queue was read "on: push" to `main`; the pick worked, three
  builds started, and each ended in two seconds with "Unsupported event
  type: push", before Claude did (2026-11-23). The safety net caught it:
  each issue went to `needs-owner` with a comment. The action takes
  issues, comments, pull requests, `workflow_dispatch`,
  `repository_dispatch`, `schedule` and `workflow_run`; a test holds
  every agent workflow's triggers to that list. A workflow cannot run
  before it is on `main`, so an event it was never run on is a guess.
- **The reviewer did not review the builder.** Claude's action stops a
  run that a bot started ("Workflow initiated by non-human actor"), and
  the builder's pull requests are opened by the App. Every review until
  then had been of a pull request a person or the bot account opened, so
  the first pull request the factory made by itself got "The review did
  not finish" (2026-11-23). It failed closed: nothing merged. Each agent
  workflow now names the App in `allowed_bots`. Two halves that each work
  were never run together until the day they had to.
- **A green run can have done nothing.** Two builds ended "success" with
  no branch, no pull request and no comment, at a dollar and three
  dollars of the plan. The action hides Claude's output, and the step
  that printed its last message ran only on failure. It now runs every
  time and its text goes on the issue.
- **In a workflow, ending the turn ends the run.** A session like this
  one is woken when a background command finishes; Claude in an action is
  not. The builder ran `make test` (eighteen minutes, past the two-minute
  default for a command), let it go to the background, and ended with
  "I'll wait for the notification that the tests have finished": three
  builds, about seven dollars of the plan, nothing pushed. Background
  commands are off for it, the foreground limit is twenty-five minutes,
  and its prompt says to run the tests in pieces.
- **The token does not choose the model.** It decides whose Claude plan
  pays. The workflows ran on the action's default, Sonnet, until each one
  named its model (`claude_args`, `--model`).
- **A cloud session knows the repo and nothing else.** Notes a session
  keeps on its own machine do not travel. What the next session must
  know goes into `docs/ROADMAP.md`, "Next session starts here", and here.
- **In a cloud session:** no AWS at all; GitHub goes through a proxy that
  refuses tag pushes, branch deletions and GraphQL, so `gh pr create`
  fails and `gh api repos/...` works; a Chrome is at `$CHROME_PATH`.
- **A cloud session's system Python cannot take `pip install`.** Debian
  installed `blinker` there, pip cannot uninstall it to upgrade it, and the
  whole install stopped: no boto3, moto or playwright, and an older ruff
  that reported a false import-order error. The setup hook said "set up"
  anyway (2026-11-11). It now installs into `~/.venvs/bgucats`, puts that
  first on PATH, and its message says what did not install.
- **A command typed with `!` has no keyboard.** A script that asks "type
  yes" gets nothing and stops. `echo yes | script` answers it.
- **Claude Code refuses some things whoever asks,** and the owner runs
  those: an apply to the whole organization, an apply whose plan was not
  shown first, and printing any part of a token. Show the plan (`echo no |
  script`), then apply.
- **An issue is text from outside.** Triage reads it with a token that
  cannot write code; Fix starts only on an admin's label
  (`docs/agents.md`).

## Models from outside

Nothing here is built; these came out of assessing Google's Decision 1 as a
moderation layer for phase 4 (`docs/moderation.md`, 2026-11-12) and out of
planning the app (`docs/app-plan/`). They are the traps that work turned
up.

- **A design that is being edited is not a specification.** The prototype
  was read twice on 2026-11-12. Between the reads it gained a 280-character
  post description, a new-cat form and a second way to post, and lost the
  "92% match" numbers. A note written from the first read said "there is no
  caption field" and was wrong by the evening. Before costing or building
  from a design, record its version, and have the owner freeze it
  (`docs/app-plan/OWNER_STEPS.md`, O2).
- **A vendor's page read through a summariser is hearsay.** The Decisions
  API's yes/no type came back spelled `noul`, twice; the price came back as
  $0.10 where the owner had been told $0.75. Neither is settled until a
  real request succeeds. The plan says so where it uses them, and makes one
  real request the first task of the milestone that depends on them.
- **Apple reviews an external TestFlight build like a store release.** A
  public beta link means the rules for user content apply: report a post,
  block a person, delete an account, a privacy policy, a login for the
  reviewer, and probably Sign in with Apple beside Google. Internal
  testers (members of the App Store Connect team, up to 100) need none of
  it. The prototype had report and block for friends only.
- **A cosine similarity is not a probability.** The phase 4 prototype's
  scanner showed "92% match" until the same day's redesign removed the
  numbers. The manifest ships `"thresholds": null`
  precisely because right guesses, wrong guesses and never-seen cats overlap
  on BGU photos, and the first guess is right on 3–5 of 13 sessions. A
  number rendered as a percentage promises a calibration the system does not
  have. Rank is honest; per cent is a claim.
- **A calibrated model is calibrated on someone else's data.** "Calibrated"
  means 0.7 is right 70% of the time *on the distribution it was measured
  on*. That distribution is not 24-character cat names in Hebrew, Russian
  and Arabic. Same rule as public-dataset accuracy in `CLAUDE.md`: the
  number is well-formed, and its accuracy here is unknown until it is
  measured against what an admin decided.
- **The cheapest moderation is the field nobody added.** The morning
  prototype had no caption and no comments, so its whole text surface was a
  24-character name and a 30-character display name. By the evening it had
  a 280-character description, and moderation went from optional to
  necessary. Grep a design for `<textarea>` before costing moderation work,
  and again before building it. There are still no comments.
- **A relational shape does not need a relational database.** Friends,
  likes, votes and a feed look like joins. Written out screen by screen
  (`docs/app-plan/02-architecture.md`), each is one key, one short list or
  one batch read, and where two lists meet both are bounded by one campus.
  The question to ask is not "is the data relational?" but "which query
  needs the database to do the join?".
- **A single-select over our cats is the banned classifier with an API in
  front of it.** Decision 1 takes its options per request, so it dodges
  "needs retraining per cat" — the objection most people remember — while
  keeping the other two: no embedding space, no enrollment template, no
  honest "I don't know this one". Recognise the shape, not the wording; the
  ban holds.
- **A model with no output tokens is a smaller injection target.** A cat
  name is attacker-controlled text going into a model. Where the job is a
  verdict, a model that cannot emit text or call a tool bounds the worst
  case at a flipped probability. Prefer that shape over asking a chat model
  for JSON.
- **An outside HTTPS call is cheaper here than an AWS service.** Bedrock or
  Rekognition needs `allowed-resource-types.txt`, the bootstrap deploy role
  and `infra/org/scp.tf` all widened — three owner decisions. A call out to
  a vendor needs none: Lambda has full internet outside a VPC, and
  `set-secret.sh` already puts keys in SSM. The guardrails make the
  not-AWS option the path of least resistance, which is worth knowing before
  reaching for the AWS-native one by reflex.

## Money

What this costs, measured on 2026-11-10, so nobody has to work it out
again:

- **AWS, production:** about 2 cents a month. **Staging:** under a cent.
  Both are inside the free allowances; alarms, alert emails and the
  guardrails cost nothing.
- **AWS, the management account:** about $2 a month, the largest AWS cost
  of the project, for something that is optional: Identity Center was set
  up (2026-10-30) with a customer-managed encryption key, which exists
  twice (us-east-1 and a replica in us-west-2) at $1 a month each. The
  default, a key AWS owns, is free. Changing it is a careful job in the
  management account, not a quick fix; it is written here so the bill is
  not a mystery.
- **GitHub Team:** two seats, the owner and the machine user.
- **The Claude plan,** which also pays for the agents and the cloud
  sessions: they use the plan's limits, and no machine is billed.
- **Apple's developer program,** yearly.
- **Codespaces** hours come from the owner's personal quota and are now
  needed only for jobs that use AWS by hand.
