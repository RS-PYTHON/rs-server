#!/usr/bin/env bash
set -euo pipefail
# set -x

# Check all the github branches opened by the bot about dependency updates.
# Checkout the develop branch, create a new branch called fix/bot-dependency-updates.
# Merge the bot modifications into this branch.
# Commit and push it.

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
ROOT_DIR="$(realpath $SCRIPT_DIR/..)"

(set -x; git fetch --all && git remote prune origin)
bot_branches=$(git branch -r | grep origin/dependabot/ || true) # all the bot dependency branches are called like this
if [[ -z "$bot_branches" ]]; then
    echo "No bot dependency branches found with name: 'origin/dependabot/pip/...'"
    exit 0
fi

# Start from develop (this will fail if you have non-commited modifications)
(set -x; git checkout develop)
target="fix/bot-dependency-updates" # branch issued from develop where we'll merge everything

# Create or get the target branch, merge develop into it
(set -x; git checkout "$target" && git pull || git push --set-upstream origin "$target") || \
(set -x; git checkout -b "$target" && git push --set-upstream origin "$target")
(set -x; git merge origin/develop)

# For each bot branch
for bot_branch in $bot_branches; do

    # We have a lot of merge conflicts on the poetry.lock files,
    # so we replace our local files by the bot branch files to avoid conflicts.
    # Then we rebuild them at the end of this script.
    lock_files=$(git diff --name-only "$bot_branch" | grep -E "(^|/)poetry.lock$")
    if [[ "$lock_files" ]]; then
        (set -x;
            git checkout "$bot_branch" -- $lock_files && \
            git commit -m "merge: poetry.lock files from $bot_branch")
    fi

    # Merge the bot branch into ours
    (set -x; git merge "$bot_branch" -m "merge: $bot_branch") && error= || error=1

    # # In case of merge conflict, try to run mergetool
    if [[ $error ]]; then
        (set -x; git mergetool && git commit -m "merge: $bot_branch")
    fi
done

# Override the poetry.lock files from the new pyproject.toml files
for f in $(find "$ROOT_DIR" -name pyproject.toml); do
    (set -x; cd $(dirname $f) && poetry lock)
done

# Commit & push
lock_files=$(git diff --name-only | grep -E "(^|/)poetry.lock$")
if [[ "$lock_files" ]]; then
    (set -x;
        git add -- $lock_files && \
        git commit $lock_files -m "merge: rebuild the poetry.lock files" && git push)
fi

echo -e "
Try 'git clean -n' then 'git clean -f' to remove your git merge backup files.
Then:
  - Go to github
  - Open a pull request for '$target' into 'develop'
  - Check that the CI/CD is ok
  - Merge the pull request
"
