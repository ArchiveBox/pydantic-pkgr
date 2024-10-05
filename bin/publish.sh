#!/usr/bin/env bash

echo "Bumping to version $1"

rm -Rf dist 2>/dev/null
nano pyproject.toml
git add -p .
git commit -m "bump version to $1"
git tag -f -a "v$1" -m "v$1"
git push origin
git push origin tags -f
uv build
uv publish
