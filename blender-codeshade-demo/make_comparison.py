"""Stitch the Cycles and EEVEE frames into one side-by-side PNG.

    blender --background --python make_comparison.py -- \
            renders/plastic_glass_cycles.png renders/plastic_glass_eevee.png \
            renders/comparison.png

Uses Blender's own image API, so the demo still needs no third-party packages.
numpy is used when present -- official Blender builds bundle it, but distro
packages run against a system Python that may not have it, so there is a plain
``array``-based path too.

Images are read as Non-Color so the pixel values pass through untouched: this
is a composite, not a re-grade.
"""

from __future__ import annotations

import os
import sys
from array import array

import bpy

DIVIDER_PX = 4
DIVIDER_RGBA = (0.05, 0.05, 0.06, 1.0)


def load_pixels(path):
    """Return (flat float buffer, width, height) for an image on disk."""
    image = bpy.data.images.load(path, check_existing=False)
    image.colorspace_settings.name = "Non-Color"
    width, height = image.size
    buffer = array("f", [0.0]) * (width * height * 4)
    image.pixels.foreach_get(buffer)
    bpy.data.images.remove(image)
    return buffer, width, height


def stitch(left, right, width, height):
    """Concatenate two equal-sized frames left-to-right with a divider bar.

    Pixels are a flat RGBA float run in bottom-up row order, so joining two
    images side by side is a per-row splice.
    """
    divider = array("f", DIVIDER_RGBA * DIVIDER_PX)
    row_floats = width * 4
    out = array("f")
    for row in range(height):
        start = row * row_floats
        stop = start + row_floats
        out.extend(left[start:stop])
        out.extend(divider)
        out.extend(right[start:stop])
    return out, width * 2 + DIVIDER_PX


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) != 3:
        raise SystemExit("usage: ... -- <left.png> <right.png> <out.png>")
    left_path, right_path, out_path = argv

    left, width, height = load_pixels(left_path)
    right, right_width, right_height = load_pixels(right_path)
    if (width, height) != (right_width, right_height):
        raise SystemExit(
            f"size mismatch: {width}x{height} vs {right_width}x{right_height}"
        )

    combined, out_width = stitch(left, right, width, height)

    result = bpy.data.images.new("comparison", width=out_width, height=height,
                                 alpha=True, float_buffer=False)
    result.colorspace_settings.name = "Non-Color"
    result.pixels.foreach_set(combined)

    result.filepath_raw = os.path.abspath(out_path)
    result.file_format = "PNG"
    result.save()
    print(f"[codeshade] wrote {out_path}  ({out_width}x{height})")


if __name__ == "__main__":
    main()
