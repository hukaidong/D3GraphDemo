"""Print every material's node tree as text, without rendering anything.

    blender --background --python dump_graphs.py

This is the "what does the shader editor show me?" answer for a machine with no
GUI. The output lists each node, its unconnected socket values, and every link
-- which is all the shader editor is drawing, minus the boxes and noodles.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

import scene as scene_builder  # noqa: E402
from shadergraph import describe  # noqa: E402


def main():
    scene_builder.build()

    trees = [(m.name, m.node_tree) for m in bpy.data.materials if m.use_nodes]
    trees += [(f"{w.name} (world)", w.node_tree) for w in bpy.data.worlds if w.use_nodes]

    for name, tree in sorted(trees):
        print(f"\n=== {name} " + "=" * max(0, 68 - len(name)))
        print(describe(tree))


if __name__ == "__main__":
    main()
