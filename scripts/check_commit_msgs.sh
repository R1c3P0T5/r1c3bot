#!/usr/bin/env bash
# Validate the commit messages in a git range with check_commit_msg.py.
#
# The range comes from the first argument. Without one it is taken from
# pre-commit's pre-push environment; when the remote branch does not exist yet
# the range becomes every local commit that no remote has.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
empty=0000000000000000000000000000000000000000

if [ "$#" -gt 0 ]; then
  revs=("$1")
  label="$1"
else
  from="${PRE_COMMIT_FROM_REF:-}"
  to="${PRE_COMMIT_TO_REF:-HEAD}"
  if [ -z "$from" ] || [ "$from" = "$empty" ]; then
    revs=("$to" --not --remotes)
    label="$to not on any remote"
  else
    revs=("$from..$to")
    label="$from..$to"
  fi
fi

message="$(mktemp)"
trap 'rm -f "$message"' EXIT

rc=0
count=0
for sha in $(git rev-list "${revs[@]}"); do
  count=$((count + 1))
  git log -1 --format=%B "$sha" >"$message"
  if ! uv run --no-project "$here/check_commit_msg.py" "$message"; then
    echo "  in $(git log -1 --format='%h %s' "$sha")" >&2
    rc=1
  fi
done

[ "$rc" -eq 0 ] && echo "$count commit message(s) OK in $label"
exit "$rc"
