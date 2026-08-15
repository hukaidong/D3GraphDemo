#!/usr/bin/env bash
# Convenience wrapper: render the demo with both engines and save a .blend.
#
#   ./run.sh                 # both engines, 1280x720
#   ./run.sh --samples 512   # any render_demo.py flag passes straight through
#   ./run.sh --no-project    # skip the .blend project
#
# PNGs land in renders/; a .blend project with both renders packed inside it
# lands in example/ once rendering completes.
#
# Set BLENDER=/path/to/blender if it is not on PATH.
set -euo pipefail

BLENDER="${BLENDER:-blender}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v "$BLENDER" >/dev/null 2>&1; then
    echo "blender not found. Install it, or set BLENDER=/path/to/blender." >&2
    exit 1
fi

exec "$BLENDER" --background --factory-startup \
    --python "$HERE/render_demo.py" -- \
    --engine both --samples 256 "$@"
