#!/usr/bin/env bash

set -e

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required: https://brew.sh" >&2
    exit 1
fi

if ! brew list --formula uv >/dev/null 2>&1; then
    brew install uv
fi

cd "${project_dir}"
uv sync
