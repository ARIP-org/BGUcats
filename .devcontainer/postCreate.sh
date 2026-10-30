#!/usr/bin/env bash
# Deliberately not "set -e": one failing step should report itself rather than
# abort the rest and leave the container half-configured with no explanation.
set -uo pipefail

fail=0

echo "==> Python dependencies"
python -m pip install --upgrade pip
if ! pip install -r requirements-dev.txt; then
  echo "!! pip install failed - run it by hand to see why"
  fail=1
fi

echo
echo "==> pre-commit hooks"
if ! pre-commit install; then
  echo "!! pre-commit install failed - run it by hand to see why"
  fail=1
fi

echo
echo "==> Tool versions"
python --version
node --version
terraform version | head -n 1
aws --version
gh --version | head -n 1

echo
echo "==> Claude Code"
# Installed by the ghcr.io/anthropics/devcontainer-features/claude-code feature.
# The fallback exists so a feature outage degrades to a warning, not a container
# with no Claude Code in it.
if command -v claude >/dev/null 2>&1; then
  echo "claude $(claude --version)"
else
  echo "!! claude not on PATH - falling back to npm"
  if npm install -g @anthropic-ai/claude-code; then
    echo "claude $(claude --version)"
  else
    echo "!! npm fallback failed too. Node is $(node --version); the CLI needs >= 22."
    fail=1
  fi
fi

echo
echo "==> AWS"
# Deploys run in GitHub Actions with OIDC; people use IAM Identity Center.
# Long-lived keys here would also be visible to every Claude Code session.
if [ -n "${AWS_ACCESS_KEY_ID:-}" ]; then
  echo "!! AWS_ACCESS_KEY_ID is set (probably a Codespaces secret)."
  echo "   Remove it: github.com/settings/codespaces -> Secrets, and the repo's"
  echo "   Settings -> Secrets and variables -> Codespaces. See docs/codespaces.md."
else
  echo "No AWS keys, as intended. For read-only access: aws sso login (docs/codespaces.md)."
fi

echo
if [ "$fail" -ne 0 ]; then
  echo "==> Setup finished WITH ERRORS - see above."
else
  echo "==> Setup complete."
fi
echo "    Run 'claude' once to authenticate (browser flow)."

# Always succeed: a setup warning should not stop the container from starting.
exit 0
