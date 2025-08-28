#!/bin/sh
# Copyright 2025 CS Group
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

d=$(date +"%Y%m%d%H%M%S")
cd services || exit 10
git stash
git checkout develop || exit 20
git pull || exit 30
git clean -f || exit 40
git checkout -b "updates-$d" || exit 60
for s in common adgs cadip catalog staging frontend ; do cd $s && poetry lock --regenerate && poetry show -o && cd - ; done
cd .. || exit 70
poetry lock --regenerate || exit 80
poetry show -o || exit 85
git add . || exit 90
git commit -m "Dependency updates" || exit 100
git push --set-upstream origin "updates-$d"
git stash pop
