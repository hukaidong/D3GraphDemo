"""Scene assembly: the hero shot, the detail ladder, camera, lights, captions.

Nothing here is modelling. It is the part of a GUI session that is pure
clicking -- placing a camera, aiming a sun, arranging three copies of a thing
side by side -- and it is worth seeing written down, because it is the part
that gets tedious by hand and disappears entirely in a script.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Vector

import assets
import geonodes
import materials
import meshlib as ml


def reset():
    """``--background`` still opens the default startup scene; empty it."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.world = materials.sky()
    return scene


def offset(objects, delta):
    for obj in objects:
        obj.location = obj.location + Vector(delta)
    return objects


def look_at(obj, target):
    """The scripted form of a Track To constraint."""
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return obj


def camera(scene, location, target, lens=50.0, name="Camera"):
    data = bpy.data.cameras.new(name)
    data.lens = lens
    obj = bpy.data.objects.new(name, data)
    obj.location = Vector(location)
    scene.collection.objects.link(obj)
    look_at(obj, target)
    scene.camera = obj
    return obj


def sun(rotation=(math.radians(52.0), 0.0, math.radians(28.0)), energy=3.4,
        angle=2.2, color=(1.0, 0.94, 0.84)):
    data = bpy.data.lights.new("Sun", type="SUN")
    data.energy = energy
    data.angle = math.radians(angle)
    data.color = color
    obj = bpy.data.objects.new("Sun", data)
    obj.rotation_euler = rotation
    bpy.context.scene.collection.objects.link(obj)
    return obj


def area_light(name, location, target, energy, size, color=(1.0, 1.0, 1.0)):
    data = bpy.data.lights.new(name, type="AREA")
    data.energy = energy
    data.size = size
    data.color = color
    obj = bpy.data.objects.new(name, data)
    obj.location = Vector(location)
    bpy.context.scene.collection.objects.link(obj)
    look_at(obj, target)
    return obj


def caption(body, location, size=0.62, name=None, material=None):
    """A 3-D text object, used to label the comparison renders.

    Blender ships a built-in font (``Bfont``), so captions need no font file on
    disk and no image editor afterwards -- the labels are part of the render.
    """
    curve = bpy.data.curves.new(name or body, type="FONT")
    curve.body = body
    curve.size = size
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.extrude = 0.008

    obj = bpy.data.objects.new(name or body, curve)
    obj.data.materials.append(material or materials.label())
    obj.location = Vector(location)
    obj.rotation_euler = (math.pi / 2.0, 0.0, 0.0)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def totals(objects):
    """Summed (vertices, triangles) over a group of objects."""
    verts = tris = 0
    for obj in objects:
        if obj.type != "MESH":
            continue
        vertex_count, triangle_count = ml.stats(obj)
        verts += vertex_count
        tris += triangle_count
    return verts, tris


# ---------------------------------------------------------------------------
# The two scenes
# ---------------------------------------------------------------------------


def hero(detail):
    """The full shot: lighthouse, islet, scatter, sea."""
    scene = reset()

    rock = assets.islet(detail)
    tuft = assets.grass_tuft(detail)
    geonodes.apply_scatter(rock, tuft, detail.scatter_density)

    building = assets.lighthouse(detail)
    offset(building, (0.0, 0.0, assets.PLATEAU_Z - 0.12))

    assets.sea()

    sun()
    area_light("Bounce", (-16.0, -18.0, 4.0), (0.0, 0.0, 6.0),
               energy=2600.0, size=14.0, color=(0.62, 0.74, 0.92))

    # The lantern is emissive geometry; a real light inside makes it cast.
    lamp = bpy.data.lights.new("Beacon", type="POINT")
    lamp.energy = 900.0
    lamp.color = (1.0, 0.84, 0.55)
    lamp.shadow_soft_size = 0.3
    beacon = bpy.data.objects.new("Beacon", lamp)
    beacon.location = Vector((0.0, 0.0, assets.PLATEAU_Z + 8.6))
    scene.collection.objects.link(beacon)

    camera(scene, location=(-28.0, -35.0, 11.0), target=(0.0, 0.0, 6.6), lens=50.0)
    return scene, building + [rock]


def ladder(levels, spacing=8.8):
    """The same lighthouse at several detail levels, in one frame.

    Rendering them side by side in a single image rather than stitching three
    renders means they share a camera, a sun and a horizon, so any difference
    you can see is a difference in the mesh.

    The captions sit *above* the towers rather than below them. Below is where
    they belong and where they were first put -- but below is also the ground
    plane, and a text object at negative Z is simply buried in it. Sky is the
    only empty part of this frame.
    """
    scene = reset()
    scene.world = materials.sky(strength=0.55)

    groups = {}
    span = spacing * (len(levels) - 1)
    label_top = assets.ROOF_APEX + 2.6
    for index, level in enumerate(levels):
        x = -span / 2.0 + index * spacing
        building = assets.lighthouse(level)
        offset(building, (x, 0.0, 0.0))
        groups[level.name] = building

        verts, tris = totals(building)
        caption(level.name.upper(), (x, 0.0, label_top), size=0.70)
        caption(f"{tris:,} tris   {verts:,} verts", (x, 0.0, label_top - 0.72),
                size=0.42)
        caption(f"{level.lathe_steps} sides   "
                f"{'bevelled' if level.bevel_width else 'no bevel'}   "
                f"{'courses' if level.course_spacing else 'plain wall'}",
                (x, 0.0, label_top - 1.28), size=0.34)

    ground = ml.object_from_bmesh("Ground", ml.box(400.0, 400.0, 0.4),
                                  material=materials.ground())
    ground.location = Vector((0.0, 0.0, -0.2))
    ml.shade(ground, "flat")

    sun(rotation=(math.radians(58.0), 0.0, math.radians(36.0)), energy=3.2)
    area_light("Fill", (-20.0, -28.0, 10.0), (0.0, 0.0, 5.0),
               energy=2400.0, size=20.0, color=(0.66, 0.76, 0.92))

    camera(scene, location=(0.0, -50.0, 6.2), target=(0.0, 0.0, 5.6), lens=58.0)
    return scene, groups
