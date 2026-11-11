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
# and say, a session that does not start is not. So the last line it prints,
# which the session shows, names whatever did not install.
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/..}" || exit 0

log="${TMPDIR:-/tmp}/bgucats-cloud-setup.log"
missing=()
{
  echo "== $(date -u +%FT%TZ) cloud session setup"

  # A virtual environment, not the system Python. There Debian installed some
  # packages pip cannot replace ("Cannot uninstall blinker ... installed by
  # debian"), the whole install stopped, and boto3, moto, playwright and the
  # pinned ruff were missing (2026-11-11). Outside the repo, so no check
  # reads it. pip skips what is already there, so a resumed session pays
  # seconds.
  venv="${BGUCATS_VENV:-$HOME/.venvs/bgucats}"
  if { [ -x "$venv/bin/pip" ] || python3 -m venv "$venv"; } &&
    "$venv/bin/pip" install --quiet --disable-pip-version-check -r requirements-dev.txt; then
    echo "dev dependencies installed in $venv"
  else
    echo "pip install failed"
    missing+=("the dev dependencies (pytest, ruff, boto3, moto, playwright)")
  fi

  # The same version CI pins (.github/workflows/ci.yml), checked against
  # HashiCorp's published checksum. `make lint` needs it for `terraform fmt`.
  version=1.15.9
  sha256=76edd0b22d2f27d3d2e097cd793209646f719cf60f02ff3af626b07361137da1
  bin="$HOME/.local/bin"
  if ! "$bin/terraform" version 2>/dev/null | grep -q "v$version"; then
    zip=$(mktemp)
    if curl -fsSLo "$zip" "https://releases.hashicorp.com/terraform/$version/terraform_${version}_linux_amd64.zip" &&
      echo "$sha256  $zip" | sha256sum --check --status &&
      mkdir -p "$bin" && unzip -oq "$zip" terraform -d "$bin"; then
      echo "terraform $version installed"
    else
      echo "terraform: download failed or checksum did not match; not installed"
      missing+=("Terraform $version")
    fi
    rm -f "$zip"
  fi

  # For the commands Claude runs in this session: the venv first, so its
  # python, pytest and ruff win over any older ones already on PATH.
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    path="$bin"
    [ -d "$venv/bin" ] && path="$venv/bin:$path"
    echo "export PATH=\"$path:\$PATH\"" >>"$CLAUDE_ENV_FILE"
  fi
} >>"$log" 2>&1

no_aws="No AWS access here; AWS work belongs to a codespace session with the owner signed in."
if [ ${#missing[@]} -eq 0 ]; then
  echo "Cloud session: dev dependencies and Terraform set up (log: $log). $no_aws"
else
  what=$(printf '%s and ' "${missing[@]}")
  echo "Cloud session setup INCOMPLETE: ${what% and } did not install, so the checks that need them will fail (log: $log). $no_aws"
fi
exit 0
