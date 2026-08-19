# Working in the codespace from a local machine

The dev container ships both forms of Claude Code:

- the **CLI** (`claude`), installed globally by `.devcontainer/postCreate.sh`
- the **VS Code extension** (`anthropic.claude-code`), installed by
  `devcontainer.json`

Both run *inside* the codespace, so they operate on the codespace's files and
have the codespace's AWS credentials, Terraform, and Python environment. Running
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
