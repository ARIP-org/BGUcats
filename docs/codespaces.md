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
within hours. Two profiles, set up once per codespace (`~/.aws` does not
survive a rebuild):

```bash
aws configure sso --use-device-code
#   SSO session name:        bgucats
#   SSO start URL:           https://<your-portal>.awsapps.com/start  (Identity Center dashboard)
#   SSO region:              us-east-1
#   SSO registration scopes: sso:account:access   (the default)
#   then open the printed URL in your own browser, enter the code, approve,
#   pick account 851725214678, role ReadOnlyAccess
#   CLI default client Region: us-east-1, output: json
#   CLI profile name:        bgucats-readonly
aws configure sso --use-device-code     # again: same session, role AdministratorAccess
#   CLI profile name:        bgucats-admin
```

`--use-device-code` is there because the codespace has no browser: you
approve on whatever machine you are typing from. Every later day:

```bash
aws sso login --sso-session bgucats --use-device-code
export AWS_PROFILE=bgucats-readonly
aws sts get-caller-identity       # .../AWSReservedSSO_ReadOnlyAccess_.../<you>
```

**`bgucats-readonly`** is for debugging: CloudWatch logs, DynamoDB items,
`make tf-plan` (it skips the lock, so read-only should be enough; it needs the `TF_VAR_*`
values in the environment).

**`bgucats-admin`** is for the owner's three manual jobs only: applying
`infra/bootstrap`, `make model-publish`, and the SSM writers
(`make whatsapp-secrets`, `make admin-add`). Set it per command
(`AWS_PROFILE=bgucats-admin make model-publish`) rather than exporting it,
and never hand it to a Claude session. Its sessions are short on purpose.

## Costs

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
