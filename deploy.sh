#!/bin/bash
# deploy.sh — push changes to singhvp.github.io
# Run this from the singhvp.github.io folder after Claude makes changes

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Read token from .github_token file (gitignored)
TOKEN_FILE="$DIR/.github_token"
if [ ! -f "$TOKEN_FILE" ]; then
  echo "❌ Missing .github_token file."
  echo "   Create it by running:"
  echo "   echo 'YOUR_GITHUB_TOKEN' > .github_token"
  exit 1
fi
TOKEN=$(cat "$TOKEN_FILE" | tr -d '[:space:]')
REPO_URL="https://${TOKEN}@github.com/singhvp/singhvp.github.io.git"

if [ ! -d ".git" ]; then
  echo "🔧 Initialising git repo..."
  git init
  git remote add origin "$REPO_URL"
else
  git remote set-url origin "$REPO_URL"
fi

echo "📦 Staging changes..."
git add -A

CHANGED=$(git diff --cached --name-only)
if [ -z "$CHANGED" ]; then
  echo "✅ Nothing to deploy — no changes detected."
  exit 0
fi

echo "Changed files:"
echo "$CHANGED"

git commit -m "Update site — $(date '+%Y-%m-%d %H:%M')"

echo "🚀 Pushing to GitHub..."
git push -u origin main 2>/dev/null || {
  git branch -M main
  git push -u origin main
}

echo ""
echo "✅ Deployed! Live at https://singhvp.github.io in ~60 seconds."
