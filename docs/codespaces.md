# Working in the codespace from a local machine

The dev container ships both forms of Claude Code:

- the **CLI** (`claude`), installed globally by `.devcontainer/postCreate.sh`
- the **VS Code extension** (`anthropic.claude-code`), installed by
  `devcontainer.json`

Both run *inside* the codespace, so they operate on the codespace's files and
use its Terraform and Python environment. The codespace has **no AWS
credentials** by default: see "AWS access" below. Running
`claude` on your Windows machine instead would operate on the local clone, which
is not what you want once real work moves to the container.

## Three ways in

### 1. VS Code desktop attached to the codespace (recommended)

```bash
gh codespace code -c <codespace-name>
```

Opens your local VS Code connected to the running container. Editor, terminal,
and the Claude Code extension all execute remotely. This is the closest thing to
"working locally on code that lives in the codespace".

Requires the **GitHub Codespaces** extension in your local VS Code.

### 2. Terminal over SSH

```bash
gh codespace ssh -c <codespace-name>
claude
```

A plain shell in the container. Good for running `claude` interactively, or
one-off commands:

```bash
gh codespace ssh -c <codespace-name> -- "cd /workspaces/BGUcats && pytest"
```

### 3. Browser

`github.dev` / the Codespaces web editor. Works, has the extension, but no local
keybindings and no local clipboard integration worth relying on.

## Useful commands

```bash
gh codespace list                          # names and state
gh codespace stop   -c <name>              # stop billing core-hours
gh codespace ports  -c <name>              # forwarded ports
gh codespace cp -e -c <name> local.txt remote:/workspaces/BGUcats/
gh codespace rebuild -c <name> --full      # after changing devcontainer.json
```

## Authenticating Claude Code inside the container

Run `claude` once and complete the browser flow. Codespaces forwards the
callback, so this works over SSH and in the web editor.

Alternative for headless use: set `ANTHROPIC_API_KEY` as a **Codespaces secret**
(repo Settings → Secrets and variables → Codespaces). Note this bills per token
separately from a Claude subscription. Never commit the key — `.gitignore`
covers `.env`, but a codespace secret is the right home for it.

## AWS access

Nothing in the codespace needs AWS to build, lint or test (the tests use
moto), and deploys run in GitHub Actions (`docs/deploy.md`). So the
codespace holds no AWS keys, and neither does a Claude Code session in it.
**Do not add `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` as Codespaces
secrets.** `postCreate.sh` warns if they are there.

When a person needs to look at AWS (logs, a table item, a read-only plan),
they sign in through IAM Identity Center and get credentials that expire
within hours. Six profiles, two per account, set up once per codespace
(`~/.aws` does not survive a rebuild). One SSO session serves all six:

| Profile | Account | Permission set | For |
|---|---|---|---|
| `bgucats-prod-ro` | `395591097129` sasha-bgucats-prod | ReadOnlyAccess | debugging production |
| `bgucats-staging-ro` | `586943192664` bgucats-staging | ReadOnlyAccess | debugging staging |
| `bgucats-staging-admin` | `586943192664` bgucats-staging | AdministratorAccess | the owner's manual jobs on staging |
| `bgucats-prod-admin` | `395591097129` sasha-bgucats-prod | AdministratorAccess | the owner's manual jobs, below |
| `mgmt-ro` | `851725214678` management | ReadOnlyAccess | billing, the organization |
| `mgmt-admin` | `851725214678` management | AdministratorAccess | Identity Center, SCPs, Organizations |

```bash
aws configure sso --use-device-code
#   SSO session name:        bgucats
#   SSO start URL:           https://<your-portal>.awsapps.com/start  (Identity Center dashboard)
#   SSO region:              us-east-1
#   SSO registration scopes: sso:account:access   (the default)
#   then open the printed URL in your own browser, enter the code, approve,
#   pick the account and role from the table above
#   CLI default client Region: us-east-1, output: json
#   CLI profile name:        bgucats-prod-ro
# ...and again for each of the other three rows.
```

Check `~/.aws/config` afterwards: each section header must read
`[profile bgucats-prod-ro]`. Typing `profile bgucats-prod-ro` at the name
prompt gives `[profile profile bgucats-prod-ro]`, a profile with a space in
its name.

`--use-device-code` is there because the codespace has no browser: you
approve on whatever machine you are typing from. Every later day, **always
with `--profile`**: there is no default profile, so a bare `aws sso login`
answers "Missing the following required SSO configuration values:
sso_start_url, sso_region" and suggests `aws configure sso`, which is not
needed. One login serves all six profiles.

```bash
aws sso login --profile bgucats-prod-ro --use-device-code   # works whatever the session is called
aws sts get-caller-identity --profile bgucats-prod-ro   # .../AWSReservedSSO_ReadOnlyAccess_.../<you>
```

### When the device page hangs

Twice on 2026-11-07 the device page (`…/start/#/device`) never loaded,
while the portal itself did. Waiting does not help: a new codespace has no
SSO session at all. Leave out `--use-device-code` and finish the browser
flow by hand:

```bash
aws sso login --profile bgucats-prod-admin     # terminal 1: prints a link, waits
```

Open the link, sign in, *Allow*. The browser then goes to
`http://127.0.0.1:<port>/oauth/callback?code=…&state=…` and fails to load:
that 127.0.0.1 is your computer, not the codespace. Copy the whole address
and hand it to the waiting CLI, quickly (the code is single-use and short-lived):

```bash
curl 'http://127.0.0.1:<port>/oauth/callback?code=…&state=…'   # terminal 2, in single quotes
```

Terminal 1 says `Successfully logged into Start URL`. From VS Code desktop
the redirect may just work, since it forwards ports to your machine.
Fallback: the portal's *Access keys* → "add a profile to your AWS
credentials file", pasted into `~/.aws/credentials` under a new name
(e.g. `[bgucats-prod-admin-keys]`) and used as `AWS_PROFILE`; they last an
hour, delete them after.

**Always name the profile.** Make targets that call AWS take
`PROFILE=...` and refuse to run without it, or while `AWS_ACCESS_KEY_ID`
is set (environment keys silently win over any profile), or against any
account but production's (`infra/scripts/aws-guard.sh`).

**`bgucats-prod-ro`** is for debugging: CloudWatch logs, DynamoDB items,
`make tf-plan PROFILE=bgucats-prod-ro` (it skips the lock, so read-only is
enough; it needs the `TF_VAR_*` values in the environment). It is what a
Claude session uses by default, and only when you choose to sign in.

**`bgucats-prod-admin`** is for the owner's manual jobs only: applying
`infra/bootstrap`, `make model-publish`, and the table writer
(`make admin-add`), always per command
(`make model-publish PROFILE=bgucats-prod-admin`), never exported. Its
sessions are short on purpose. Since 2026-11-07 a Claude session may use an
admin profile too, but only for a job the owner asked for, while the owner is
signed in, and never in place of a deploy (`CLAUDE.md`, "Workflow").

## Costs

The repo lives in the organization `ARIP-org`, whose GitHub Team plan
includes no Codespaces quota. Who pays is `ARIP-org` → *Settings* →
*Codespaces* → *General* → "Codespace ownership": **User ownership** bills
the person who creates the codespace (their own free or Pro quota);
Organization ownership bills the org and needs a spending limit above zero.
`~/.aws/config` and Claude Code's memory do not move to a new codespace on
their own; copy them across (2026-11-07: as a zip in the repo root,
never committed).

Codespaces bills core-hours while running and storage while it exists. This
codespace is a 2-core machine, so it burns 2 core-hours per wall-clock hour.
It suspends automatically after the idle timeout (default 30 minutes).

```bash
gh codespace stop -c <name>
```

is the habit worth having at the end of a session.

## After changing the dev container

`devcontainer.json` changes only take effect on a rebuild:

```bash
gh codespace rebuild -c <name> --full
```

`/workspaces` survives a rebuild; everything installed outside it does not,
which is why all setup lives in `postCreate.sh` rather than in ad-hoc
`apt install` commands.
