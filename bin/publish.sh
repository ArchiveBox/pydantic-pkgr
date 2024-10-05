#!/usr/bin/env bash

rm -Rf dist 2>/dev/null

uv build
uv publish
