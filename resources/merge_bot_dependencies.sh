#!/usr/bin/env bash
# Copyright 2024 CS Group
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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

# Branch issued from develop where we'll merge everything
target="fix/bot-dependency-updates"

# Check if the local and remote target branch exist
git rev-parse --verify "$target" >/dev/null 2>&1 && local_exist=1 || local_exist=
git rev-parse --verify "origin/$target" >/dev/null 2>&1 && remote_exist=1 || remote_exist=

if [[ -z $local_exist ]]; then
    if [[ -z $remote_exist ]]; then
        # Local and remote don't exist
        # Start from develop (this will fail if you have non-commited modifications)
        (set -x; git checkout develop && git checkout -b "$target" && git push --set-upstream origin "$target")

    else
        # Local doesn't exist, remote does exist
        (set -x; git checkout "$target" && git pull && git merge origin/develop)
    fi
else
    if [[ -z $remote_exist ]]; then
        # Local does exist, remote doesn't exist
        (set -x; git checkout "$target" && git merge origin/develop && git push --set-upstream origin "$target")

    else
        # Local and remote exist
        (set -x; git checkout "$target" && git pull && git merge origin/develop)
    fi
fi

# For each bot branch
for bot_branch in $bot_branches; do

    # We have a lot of merge conflicts on the poetry.lock files,
    # so we replace our local files by the bot branch files to avoid conflicts.
    # Then we rebuild them at the end of this script.
    lock_files=$(git diff --name-only "$bot_branch" | grep -E "(^|/)poetry.lock$")
    if [[ "$lock_files" ]]; then
        (set -x;
            git checkout "$bot_branch" -- $lock_files; \
            git diff-index --quiet HEAD || git commit -m "merge: poetry.lock files from $bot_branch")
    fi

    # Merge the bot branch into ours
    (set -x; git merge "$bot_branch" -m "merge: $bot_branch") && error= || error=1

    # In case of merge conflict, try to run mergetool
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
Try \"find . -name "*.orig" -exec rm {} \;\" to remove your git merge backup files.
Then:
  - Go to github
  - Open a pull request for '$target' into 'develop'
  - Check that the CI/CD is ok
  - Merge the pull request
"
