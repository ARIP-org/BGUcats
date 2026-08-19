#!/usr/bin/env bash
set -euo pipefail

echo "==> Installing Claude Code CLI"
npm install -g @anthropic-ai/claude-code

echo "==> Upgrading pip"
python -m pip install --upgrade pip

if [ -f requirements-dev.txt ]; then
  echo "==> Installing dev requirements"
  pip install -r requirements-dev.txt
fi

if [ -f requirements.txt ]; then
  echo "==> Installing runtime requirements"
  pip install -r requirements.txt
fi

echo "==> Versions"
python --version
terraform version | head -n 1
aws --version
claude --version || echo "claude CLI installed; run 'claude' once to authenticate"

echo
echo "==> Next: run 'claude' and authenticate (browser flow or ANTHROPIC_API_KEY codespace secret)."
