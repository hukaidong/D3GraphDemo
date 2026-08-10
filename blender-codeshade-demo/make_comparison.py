"""Stitch the Cycles and EEVEE frames into one side-by-side PNG.

    blender --background --python make_comparison.py -- \
            renders/plastic_glass_cycles.png renders/plastic_glass_eevee.png \
            renders/comparison.png

Uses Blender's own image API and its bundled numpy, so the demo still needs no
third-party packages. Images are read as Non-Color so the pixel values pass
through untouched -- this is a composite, not a re-grade.
"""

from __future__ import annotations

import os
import sys

import bpy
import numpy as np

DIVIDER_PX = 4
DIVIDER_RGBA = (0.05, 0.05, 0.06, 1.0)


def load_pixels(path):
    image = bpy.data.images.load(path, check_existing=False)
    image.colorspace_settings.name = "Non-Color"
    width, height = image.size
    buffer = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(buffer)
    bpy.data.images.remove(image)
    return buffer.reshape(height, width, 4)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) != 3:
        raise SystemExit("usage: ... -- <left.png> <right.png> <out.png>")
    left_path, right_path, out_path = argv

    left = load_pixels(left_path)
    right = load_pixels(right_path)
    if left.shape != right.shape:
        raise SystemExit(f"size mismatch: {left.shape} vs {right.shape}")

    height = left.shape[0]
    divider = np.tile(np.array(DIVIDER_RGBA, dtype=np.float32), (height, DIVIDER_PX, 1))
    combined = np.concatenate([left, divider, right], axis=1)

    out_height, out_width = combined.shape[:2]
    result = bpy.data.images.new("comparison", width=out_width, height=out_height,
                                 alpha=True, float_buffer=False)
    result.colorspace_settings.name = "Non-Color"
    result.pixels.foreach_set(combined.reshape(-1))

    result.filepath_raw = os.path.abspath(out_path)
    result.file_format = "PNG"
    result.save()
    print(f"[codeshade] wrote {out_path}  ({out_width}x{out_height})")


if __name__ == "__main__":
    main()
