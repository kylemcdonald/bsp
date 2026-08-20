#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

curl --fail-with-body --silent --show-error \
    --form "json=@${script_dir}/draw-extents.json;type=application/json" \
    http://localhost:8080/draw-json
printf '\n'
