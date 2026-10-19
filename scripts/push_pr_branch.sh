#!/usr/bin/env bash
# Push HEAD to refs/heads/<branch> on <remote> for the Action's create-pr mode.
#
# actions/checkout only fetches the triggering ref, so on runs after the first
# the runner has no refs/remotes/origin/<branch>. A bare --force-with-lease then
# expects the remote branch to be absent and is rejected ("stale info"), so the
# existing PR could never be updated. Fetching the branch is not always enough
# either: with a single-branch fetch refspec git still can't map the branch to a
# tracking ref. So read the branch's current tip from the remote and lease on
# that exact value (empty = must not exist yet). The push still refuses to
# clobber a branch that moved between this lookup and the push.
set -euo pipefail
branch="${1:?usage: push_pr_branch.sh <branch> [remote]}"
remote="${2:-origin}"
expect=$(git ls-remote --heads "$remote" "refs/heads/${branch}" | cut -f1)
if [ -n "$expect" ]; then
  # Best effort: keep a tracking ref around for later git commands / -u.
  git fetch --no-tags --depth=1 "$remote" \
    "+refs/heads/${branch}:refs/remotes/${remote}/${branch}" >/dev/null 2>&1 || true
fi
git push -u "$remote" "HEAD:refs/heads/${branch}" \
  --force-with-lease="refs/heads/${branch}:${expect}"
