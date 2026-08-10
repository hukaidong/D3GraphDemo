#!/usr/bin/env bash
# Convenience wrapper: render every shot in the demo.
#
#   ./run.sh                    # all three shots, 1600x900
#   ./run.sh --samples 400      # any render_demo.py flag passes straight through
#   ./run.sh --shot hero        # just the hero render
#
# Set BLENDER=/path/to/blender if it is not on PATH.
set -euo pipefail

BLENDER="${BLENDER:-blender}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v "$BLENDER" >/dev/null 2>&1; then
    echo "blender not found. Install it, or set BLENDER=/path/to/blender." >&2
    exit 1
fi

# 300 samples is what the committed renders in renders/ were made with. This
# build has no denoiser compiled in, so samples are the only lever on noise.
exec "$BLENDER" --background --factory-startup \
    --python "$HERE/render_demo.py" -- \
    --shot all --samples 300 "$@"
