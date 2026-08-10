"""The operation sheet: twelve tiles, twelve modelling operations, no GUI.

This is the direct answer to "do I need a modeller to carve the detail?" -- it
is the toolbar, in code. Every tile starts from a primitive and applies exactly
one operation, the same operation the corresponding button in Blender calls,
and the caption under each tile is the resulting triangle count.

The two tiles worth staring at are the last pair. ``displace`` is a sphere
pushed around by a noise function -- procedural detail nobody sculpted. Next to
it, ``decimate`` is that same mesh reduced to a fraction of its triangles, which
is the automatic route to a low-poly asset: model dense, then throw geometry
away, rather than placing 300 triangles by hand.
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

import materials
import meshlib as ml
import scene as scene_builder

COLUMNS = 6
COLUMN_GAP = 3.05
ROW_GAP = 4.40
TILE_RADIUS = 0.95
SEED = 4213

# The camera is orthographic and points straight down -Y, so a tile facing it
# square-on shows no depth at all -- an inset panel and a flat square render
# identically. Turning every tile by the same three-quarter angle is what an
# icon sheet does, and it costs one rotation per object.
TILT = (math.radians(-19.0), 0.0, math.radians(34.0))


# ---------------------------------------------------------------------------
# The tiles. Each returns a bmesh, and each is one operation.
# ---------------------------------------------------------------------------


def _lathe():
    profile = (ml.Profile(0.0, -1.25)
               .line_to(0.95, -1.25)
               .line_to(0.80, -1.05)
               .curve_to(0.40, 0.55, bulge=-0.12, steps=8)
               .curve_to(0.72, 1.05, bulge=0.35, steps=5)
               .line_to(0.30, 1.25)
               .line_to(0.0, 1.25))
    return ml.lathe(profile.sample(2.0), 48)


def _extrude():
    """A grid whose faces are each extruded to a different height.

    A single extruded cube is just a taller cube and shows nothing, so this
    extrudes every face of a 4x4 grid separately -- the operation you would use
    to block out a city, driven by a function instead of by dragging.
    """
    bm = ml.box(2.3, 2.3, 0.45)
    top = [face for face in bm.faces if face.normal.z > 0.9]
    # Cut the top face into a 4x4 grid first -- subdividing the four edges of a
    # single face with grid fill is the scripted form of two loop cuts.
    ml.subdivide(bm, cuts=3, edges=top[0].edges[:])

    ml.seed(SEED)
    for face in [face for face in bm.faces if face.normal.z > 0.9]:
        centre = face.calc_center_median()
        height = 0.3 + 1.6 * abs(ml.fractal_at(centre, scale=1.15, octaves=3))
        result = bmesh.ops.extrude_discrete_faces(bm, faces=[face])
        for new_face in result["faces"]:
            bmesh.ops.translate(bm, verts=new_face.verts[:],
                                vec=(0.0, 0.0, height))
    return bm


def _inset():
    bm = ml.box(1.9, 1.9, 1.9)
    bmesh.ops.inset_individual(bm, faces=bm.faces[:], thickness=0.26,
                               depth=-0.16, use_even_offset=True)
    return bm


def _bevel():
    bm = ml.box(1.85, 1.85, 1.85)
    ml.bevel(bm, width=0.28, segments=4)
    return bm


def _subdivide():
    """Two Catmull-Clark levels on a stepped box.

    Subdividing a plain cube just makes a sphere, which is indistinguishable
    from a sphere. Starting from a blocky form shows what the operation is
    actually doing to the corners.
    """
    bm = ml.box(1.7, 1.7, 1.2)
    top = [face for face in bm.faces if face.normal.z > 0.9]
    ml.extrude(bm, ml.inset(bm, top, thickness=0.42), (0.0, 0.0, 1.15))
    for _ in range(2):
        ml.subdivide(bm, cuts=1, smooth=1.0)
    return bm


def _radial_array():
    """Twelve boxes on a circle -- ``create_cube`` takes a placement matrix."""
    bm = bmesh.new()
    for position, angle in ml.radial(12, 1.05):
        matrix = (Matrix.Translation(position)
                  @ Matrix.Rotation(angle, 4, "Z")
                  @ Matrix.Diagonal(Vector((0.34, 0.34, 1.9, 1.0))))
        bmesh.ops.create_cube(bm, size=1.0, matrix=matrix)
    return bm


def _displace():
    ml.seed(SEED)
    bm = ml.icosphere(4, 1.15)
    ml.displace_verts(bm, lambda co, normal: normal * (
        0.42 * ml.fractal_at(co, scale=0.85, octaves=6)))
    return bm


def _decimated():
    """The displace tile, collapsed to 6% of its triangles."""
    return _displace()


# --- tiles that need a real object, because they use modifiers or booleans ---


def _boolean_tile(name):
    target = ml.object_from_bmesh(name, ml.box(1.8, 1.8, 1.8))
    cutter = ml.object_from_bmesh(name + "Cut", ml.icosphere(3, 1.18))
    cutter.location = Vector((0.0, 0.0, 0.95))
    ml.boolean(target, cutter)

    cutter2 = ml.object_from_bmesh(name + "Cut2", ml.cylinder(0.52, 4.0, 24))
    ml.boolean(target, cutter2)
    return target


def _solidify_tile(name):
    profile = (ml.Profile(0.0, 1.3).curve_to(1.25, -1.2, bulge=0.28, steps=10))
    obj = ml.object_from_bmesh(name, ml.lathe(profile.sample(2.0), 40))
    # An open surface given a thickness -- the Solidify modifier. Doing this by
    # hand means selecting the boundary and extruding it, carefully, twice.
    ml.modifier(obj, "SOLIDIFY", thickness=0.11, offset=0.0)
    ml.bake(obj)
    return obj


def _screw_tile(name):
    """A profile swept along a helix: the Screw modifier."""
    bm = bmesh.new()
    ring = []
    for step in range(10):
        angle = math.tau * step / 10
        ring.append(bm.verts.new((0.95 + 0.17 * math.cos(angle), 0.0,
                                  -1.35 + 0.17 * math.sin(angle))))
    for index in range(len(ring)):
        bm.edges.new((ring[index], ring[(index + 1) % len(ring)]))

    obj = ml.object_from_bmesh(name, bm)
    ml.modifier(obj, "SCREW", axis="Z", angle=math.radians(720.0),
                screw_offset=2.7, steps=64, render_steps=64, use_merge_vertices=True)
    ml.bake(obj)
    return obj


def _wireframe_tile(name):
    """The decimated mesh turned into its own wireframe.

    Sits next to ``decimate`` on purpose: this is the topology that survived
    the reduction, and it is the only tile that shows edges rather than
    surface. Blender will happily model the wireframe as solid geometry.
    """
    obj = ml.object_from_bmesh(name, _decimated())
    ml.modifier(obj, "DECIMATE", decimate_type="COLLAPSE", ratio=0.06)
    ml.bake(obj)
    ml.modifier(obj, "WIREFRAME", thickness=0.035, use_replace=True)
    ml.bake(obj)
    return obj


def _decimate_tile(name):
    obj = ml.object_from_bmesh(name, _decimated())
    ml.modifier(obj, "DECIMATE", decimate_type="COLLAPSE", ratio=0.06)
    ml.bake(obj)
    return obj


# (caption, builder, shading) -- builders return either a bmesh or an object.
# Top row builds shape; bottom row refines, thickens, roughens and reduces it.
TILES = [
    ("lathe / spin", _lathe, "smooth"),
    ("extrude", _extrude, "flat"),
    ("inset", _inset, "flat"),
    ("bevel", _bevel, "smooth"),
    ("subdivide", _subdivide, "smooth"),
    ("radial array", _radial_array, "flat"),
    ("boolean", _boolean_tile, "flat"),
    ("solidify", _solidify_tile, "smooth"),
    ("screw", _screw_tile, "smooth"),
    ("displace (noise)", _displace, "smooth"),
    ("wireframe", _wireframe_tile, "flat"),
    ("decimate 6%", _decimate_tile, "flat"),
]


def _normalise(obj, radius=TILE_RADIUS):
    """Centre a tile on its own bounding box and scale it to a common size.

    Without this the tiles are whatever size their construction happened to
    produce -- the screw is three times the height of the cube -- and the sheet
    reads as an accident. Note the mesh is edited rather than the object scaled,
    so the triangle counts printed underneath stay honest.
    """
    coords = [vert.co for vert in obj.data.vertices]
    if not coords:
        return obj

    low = Vector((min(c.x for c in coords), min(c.y for c in coords),
                  min(c.z for c in coords)))
    high = Vector((max(c.x for c in coords), max(c.y for c in coords),
                   max(c.z for c in coords)))
    centre = (low + high) / 2.0
    extent = max((high - low).x, (high - low).y, (high - low).z) / 2.0
    factor = radius / extent if extent > 1e-6 else 1.0

    for vert in obj.data.vertices:
        vert.co = (vert.co - centre) * factor
    obj.data.update()
    return obj


def build():
    """Lay the tiles out in a grid with captions, and return the scene."""
    scene = scene_builder.reset()
    clay = materials.clay()
    text = materials.label_light()

    rows = (len(TILES) + COLUMNS - 1) // COLUMNS
    for index, (caption, builder, shading) in enumerate(TILES):
        column = index % COLUMNS
        row = index // COLUMNS
        x = (column - (COLUMNS - 1) / 2.0) * COLUMN_GAP
        z = ((rows - 1) / 2.0 - row) * ROW_GAP

        name = f"Tile{index:02d}"
        result = builder(name) if _wants_name(builder) else builder()
        obj = (result if isinstance(result, bpy.types.Object)
               else ml.object_from_bmesh(name, result))
        obj.data.materials.clear()
        obj.data.materials.append(clay)
        ml.shade(obj, shading, 34.0)
        _normalise(obj)
        obj.location = Vector((x, 0.0, z + 0.55))
        obj.rotation_euler = TILT

        _, triangles = ml.stats(obj)
        scene_builder.caption(caption, (x, 0.0, z - 1.18), size=0.245,
                              material=text)
        scene_builder.caption(f"{triangles:,} tris", (x, 0.0, z - 1.56),
                              size=0.19, material=text)

    # No sun: a hard key throws the tiles' shadows across the backdrop and the
    # sheet stops being readable. Large soft sources only, and the backdrop is
    # far enough back that what shadow there is falls off before it lands.
    scene.world = materials.sky(strength=0.22)
    scene_builder.area_light("Key", (-8.0, -11.0, 7.0), (0.0, 0.0, 0.0),
                             energy=6400.0, size=11.0)
    scene_builder.area_light("Rim", (9.0, -7.0, -5.0), (0.0, 0.0, 0.0),
                             energy=2600.0, size=12.0, color=(0.60, 0.72, 0.95))

    backdrop = ml.object_from_bmesh("Backdrop", ml.box(90.0, 0.4, 60.0),
                                    material=materials.sheet())
    backdrop.location = Vector((0.0, 16.0, 0.0))
    ml.shade(backdrop, "flat")

    camera = scene_builder.camera(scene, location=(0.0, -26.0, 0.0),
                                  target=(0.0, 0.0, 0.0))
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = COLUMNS * COLUMN_GAP + 1.1
    return scene


def _wants_name(builder):
    return builder.__code__.co_argcount == 1
