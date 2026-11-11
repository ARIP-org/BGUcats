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
  total. The deploy role is past 8,500. The next big addition needs a
  managed policy.
- **Two IAM surprises in the alerts work:** an SNS subscription is not a
  resource a policy can name (`Resource: "*"` or nothing), and
  `DescribeAlarms` is checked against every alarm in the account, not the
  ones asked for.
- **CloudWatch cannot publish to a topic encrypted with AWS's own SNS
  key.** The alerts topic is unencrypted for that reason
  (`infra/main/alarms.tf`).
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
  (`admin_api.tf`) is the fix. The local test server answered preflights
  itself, so the tests passed; `curl -X OPTIONS` against the real API with
  an `Origin` header is the check (`docs/deploy.md`, "The iPhone app").
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

## Agents and sessions

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
