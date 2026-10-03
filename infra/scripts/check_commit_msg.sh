#!/usr/bin/env bash
# commit-msg guard (CLAUDE.md §4): one line, conventional type, no trailers/signatures/co-authors.
set -euo pipefail
msg_file="$1"
msg="$(grep -v '^#' "$msg_file" | sed -e '/^[[:space:]]*$/d')"

if printf '%s\n' "$msg" | grep -qiE '(signed-off-by|co-authored-by|generated with|🤖)'; then
  echo "commit-msg: trailers, signatures, co-authors and tool names are not allowed (CLAUDE.md §4)." >&2
  exit 1
fi
if [ "$(printf '%s\n' "$msg" | wc -l | tr -d ' ')" -ne 1 ]; then
  echo "commit-msg: message must be exactly one line (CLAUDE.md §4)." >&2
  exit 1
fi
if ! printf '%s\n' "$msg" | grep -qE '^(feat|fix|test|docs|chore|refactor|perf|ci)(\([a-z0-9-]+\))?: .+'; then
  echo "commit-msg: use '<type>(pNN): <summary>' with type feat|fix|test|docs|chore|refactor|perf|ci." >&2
  exit 1
fi
