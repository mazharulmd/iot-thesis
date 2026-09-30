#!/usr/bin/env bash
# Commit the project (code, docs, thesis, results) and push it to GitHub, refusing to go on if
# anything secret is staged.
#
#   scripts/git-publish.sh "commit message"                                  (usual case)
#   scripts/git-publish.sh https://github.com/<user>/<repo>.git ["message"]   (first push only)
#
# Safe to run again later: it stages the changes, checks them, commits, pulls and pushes.
set -euo pipefail
cd "$(dirname "$0")/.."

REMOTE=""
MSG="Update project and results"
case "${1:-}" in
  https://*|http://*|git@*|ssh://*) REMOTE="$1"; MSG="${2:-$MSG}" ;;
  "") ;;
  *) MSG="$1" ;;
esac
# Repair an origin that is not a repository URL (an older version of this script could set one).
if git remote get-url origin >/dev/null 2>&1; then
  case "$(git remote get-url origin)" in
    https://*|http://*|git@*|ssh://*) ;;
    *) echo "origin was '$(git remote get-url origin)', which is not a URL; set it with:"
       echo "  git remote set-url origin https://github.com/<user>/<repo>.git"; exit 1 ;;
  esac
fi

if [ ! -d .git ]; then
  git init -q -b main
  echo "Initialised a git repository (branch main)."
fi
git config user.name  >/dev/null || { echo "Set your name first:  git config --global user.name \"Your Name\""; exit 1; }
git config user.email >/dev/null || { echo "Set your email first: git config --global user.email you@example.com"; exit 1; }

git add -A

# 1. Files that must never be committed.
bad_files=$(git diff --cached --name-only | grep -E '(^|/)\.env$|^certs/|\.pem$|\.key$|\.crt$|^\.localstack/|^\.mosquitto/|^detection/data/|^runs/|^logs/|^\.venv/|^cdk\.out/' || true)
# 2. Secret-looking content in what is staged (AWS keys, LocalStack token values, private keys).
bad_content=$(git diff --cached -U0 | grep -E '^\+' | grep -nE 'AKIA[0-9A-Z]{16}|aws_secret_access_key *= *[A-Za-z0-9/+]{30,}|LOCALSTACK_AUTH_TOKEN=[A-Za-z0-9-]{8,}|BEGIN (RSA |EC )?PRIVATE KEY' || true)
if [ -n "$bad_files$bad_content" ]; then
  git reset -q
  echo "STOPPED: secret or excluded files are staged. Nothing was committed."
  [ -n "$bad_files" ] && echo "Files:" && echo "$bad_files"
  [ -n "$bad_content" ] && echo "Content matches (check these lines):" && echo "$bad_content" | cut -c1-80
  exit 1
fi

# 3. Very large files (GitHub rejects files over 100 MB and warns above 50 MB).
big=$(git diff --cached --name-only -z | xargs -0 -r du -k 2>/dev/null | awk '$1 > 20000 {print $2 " (" int($1/1024) " MB)"}')
if [ -n "$big" ]; then
  git reset -q
  echo "STOPPED: files larger than 20 MB are staged. Add them to .gitignore or remove them:"
  echo "$big"
  exit 1
fi

echo "Secret check passed. Protected paths are ignored:"
for p in .env certs/ .localstack/ detection/data/ runs/; do
  if [ -e "$p" ]; then git check-ignore -q "$p" && echo "  ignored  $p" || { echo "  NOT IGNORED: $p"; git reset -q; exit 1; }; fi
done

if git diff --cached --quiet; then
  echo "No changes to commit."
else
  git commit -q -m "$MSG"
  echo "Committed: $(git log -1 --oneline)  ($(git ls-files | wc -l) files tracked)"
fi

if [ -n "$REMOTE" ]; then
  if git remote get-url origin >/dev/null 2>&1; then git remote set-url origin "$REMOTE"; else git remote add origin "$REMOTE"; fi
fi
if git remote get-url origin >/dev/null 2>&1; then
  git branch -M main
  # Bring in changes pushed from elsewhere (e.g. code updates) before pushing results.
  if git ls-remote --exit-code --heads origin main >/dev/null 2>&1; then
    git pull --rebase origin main
  fi
  git push -u origin main
else
  echo "No remote yet. Run again with the repository URL to push."
fi
