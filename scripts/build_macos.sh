#!/usr/bin/env bash

# Build a local macOS GUI bundle with the locked packaging dependencies.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Build the macOS app on macOS." >&2
    exit 1
fi

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${project_dir}"
exec uv run --locked --group packaging python -m PyInstaller \
    --noconfirm tiresias-workstation.spec
