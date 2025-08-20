#!/bin/sh
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
git push --branch "updates-$d"
git stash pop
