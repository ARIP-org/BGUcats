#!/usr/bin/env bash
# Gets a Claude Code cloud session (claude.ai/code, the phone app) ready to
# run this repo's checks: the dev dependencies and Terraform. It is the
# SessionStart hook in .claude/settings.json, so it runs when any session
# starts and does nothing unless that session is a cloud one.
#
# What a cloud session has without this: Python, Node, git, gh and a Chrome
# (tests/web uses it through $CHROME_PATH). What it never has: AWS. Signing
# in with SSO is not possible there, by design of this project as much as
# of the product (docs/agents.md, "Hands-on sessions in the cloud").
#
# It never fails the session: a missing tool is something Claude can see
# and say, a session that does not start is not.
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/..}" || exit 0

log="${TMPDIR:-/tmp}/bgucats-cloud-setup.log"
{
  echo "== $(date -u +%FT%TZ) cloud session setup"

  # pip skips what is already there, so a resumed session pays seconds.
  pip install --quiet -r requirements-dev.txt || echo "pip install failed"

  # The same version CI pins (.github/workflows/ci.yml), checked against
  # HashiCorp's published checksum. `make lint` needs it for `terraform fmt`.
  version=1.15.9
  sha256=76edd0b22d2f27d3d2e097cd793209646f719cf60f02ff3af626b07361137da1
  bin="$HOME/.local/bin"
  if ! "$bin/terraform" version 2>/dev/null | grep -q "v$version"; then
    zip=$(mktemp)
    if curl -fsSLo "$zip" "https://releases.hashicorp.com/terraform/$version/terraform_${version}_linux_amd64.zip" &&
      echo "$sha256  $zip" | sha256sum --check --status; then
      mkdir -p "$bin" && unzip -oq "$zip" terraform -d "$bin" && echo "terraform $version installed"
    else
      echo "terraform: download failed or checksum did not match; not installed"
    fi
    rm -f "$zip"
  fi
  # For the commands Claude runs in this session.
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    echo "export PATH=\"$bin:\$PATH\"" >>"$CLAUDE_ENV_FILE"
  fi
} >>"$log" 2>&1

echo "Cloud session: dev dependencies and Terraform set up (log: $log). No AWS access here; AWS work belongs to a codespace session with the owner signed in."
exit 0
