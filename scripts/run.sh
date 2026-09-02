#!/usr/bin/env bash

set -e

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    source "${project_dir}/.venv/bin/activate"
fi

cd "${project_dir}"
exec uv run tiresias-workstation "$@"
