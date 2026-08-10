"""Build the demo scene: six primitives, a checker floor, camera and lights.

Everything here is ordinary ``bpy`` data-API work. Note that the geometry is
created with ``bpy.ops.mesh.primitive_*``, which are the same operators the Add
menu calls -- they work fine in ``--background`` as long as something sensible
is in the context, which a fresh scene provides.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Vector

import materials


# (label, primitive, material factory, keyword args for the factory)
PRIMITIVES = [
    ("Cube",     "cube",     materials.glossy_plastic,   dict(color=(0.72, 0.10, 0.09, 1.0))),
    ("Cylinder", "cylinder", materials.matte_plastic,    dict(color=(0.92, 0.63, 0.08, 1.0))),
    ("Ico",      "ico",      materials.textured_plastic, dict(color=(0.09, 0.29, 0.68, 1.0))),
    ("Sphere",   "sphere",   materials.clear_glass,      dict()),
    ("Cone",     "cone",     materials.tinted_glass,     dict()),
    ("Torus",    "torus",    materials.frosted_glass,    dict()),
]

# Back row is the three plastics, front row the three glasses -- the glass sits
# between the camera and the checker floor so refraction is actually visible.
GRID_X = (-2.9, 0.0, 2.9)
ROW_Y = (1.7, -1.9)


def reset_scene():
    """Empty the file. ``--background`` still opens the default startup scene."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def _shade_smooth(obj, keep_caps_flat=False):
    """Smooth-shade a mesh without relying on version-specific auto-smooth.

    Blender 4.1 replaced ``mesh.use_auto_smooth`` with a modifier, so instead of
    branching on version this marks polygons directly: caps (normals along Z)
    stay faceted, curved sides go smooth.
    """
    mesh = obj.data
    for polygon in mesh.polygons:
        polygon.use_smooth = (
            abs(polygon.normal.z) < 0.99 if keep_caps_flat else True
        )
    mesh.update()


def _add_primitive(kind, location):
    if kind == "cube":
        bpy.ops.mesh.primitive_cube_add(size=1.9, location=location)
        obj = bpy.context.active_object
        # A perfectly sharp edge never catches a highlight; real moulded plastic
        # always has a small radius, and it is what sells the material.
        bevel = obj.modifiers.new("Bevel", "BEVEL")
        bevel.width = 0.045
        bevel.segments = 3
        bevel.harden_normals = False
    elif kind == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1.05, segments=64, ring_count=32,
                                             location=location)
        obj = bpy.context.active_object
        _shade_smooth(obj)
    elif kind == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(radius=0.85, depth=1.9, vertices=64,
                                            location=location)
        obj = bpy.context.active_object
        _shade_smooth(obj, keep_caps_flat=True)
    elif kind == "cone":
        bpy.ops.mesh.primitive_cone_add(radius1=1.0, depth=2.1, vertices=64,
                                        location=location)
        obj = bpy.context.active_object
        _shade_smooth(obj, keep_caps_flat=True)
    elif kind == "torus":
        bpy.ops.mesh.primitive_torus_add(major_radius=0.78, minor_radius=0.3,
                                         major_segments=64, minor_segments=32,
                                         location=location)
        obj = bpy.context.active_object
        _shade_smooth(obj)
    elif kind == "ico":
        bpy.ops.mesh.primitive_ico_sphere_add(radius=1.05, subdivisions=4,
                                              location=location)
        obj = bpy.context.active_object
        _shade_smooth(obj)
    else:
        raise ValueError(f"unknown primitive {kind!r}")
    return obj


def _assign(obj, material):
    obj.data.materials.clear()
    obj.data.materials.append(material)


def add_objects():
    """Create the primitives, resting on z=0, and assign their materials."""
    created = []
    for index, (label, kind, factory, kwargs) in enumerate(PRIMITIVES):
        x = GRID_X[index % 3]
        y = ROW_Y[index // 3]
        obj = _add_primitive(kind, location=(x, y, 0.0))
        obj.name = label

        # Drop each object so its lowest vertex sits on the floor plane.
        lowest = min((obj.matrix_world @ v.co).z for v in obj.data.vertices)
        obj.location.z -= lowest

        _assign(obj, factory(name=f"M_{label}", **kwargs))
        created.append(obj)
    return created


def add_floor(size=60.0):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0.0, 0.0, 0.0))
    floor = bpy.context.active_object
    floor.name = "Floor"
    # The plane's object coordinates span its full size, so the checker scale is
    # in "squares per unit", not squares across the plane -- 1.2 gives roughly
    # 0.8-unit squares, big enough to read clearly through the glass.
    _assign(floor, materials.checker_floor("M_Floor", scale=1.2))
    return floor


def add_camera(scene, location=(0.0, -13.8, 5.0), target=(0.0, -0.1, 1.0), lens=42.0):
    """Add a camera aimed at ``target``.

    ``to_track_quat`` is the scripted version of a Track To constraint: point
    the camera's -Z down the view direction, keep +Y up.
    """
    data = bpy.data.cameras.new("Camera")
    data.lens = lens
    camera = bpy.data.objects.new("Camera", data)
    camera.location = Vector(location)
    camera.rotation_euler = (Vector(target) - Vector(location)).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(camera)
    scene.camera = camera
    return camera


def _area_light(name, location, target, energy, size, color=(1.0, 1.0, 1.0)):
    data = bpy.data.lights.new(name, type="AREA")
    data.energy = energy
    data.size = size
    data.color = color
    light = bpy.data.objects.new(name, data)
    light.location = Vector(location)
    light.rotation_euler = (Vector(target) - Vector(location)).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(light)
    return light


def add_lights():
    """Three-point-ish rig.

    Large area lights on purpose: the shape and softness of the highlight is
    most of what makes plastic read as plastic, and a big source gives glass a
    bright edge to catch.
    """
    lights = [
        _area_light("Key", (-5.2, -5.6, 6.4), (0, 0, 1), energy=650.0, size=6.0),
        _area_light("Fill", (6.0, -3.4, 3.2), (0, 0, 1), energy=200.0, size=7.0,
                    color=(0.78, 0.85, 1.0)),
        _area_light("Rim", (2.0, 6.6, 4.6), (0, 0, 1), energy=450.0, size=5.0,
                    color=(1.0, 0.93, 0.82)),
    ]

    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 1.1
    sun_data.angle = math.radians(3.0)
    sun = bpy.data.objects.new("Sun", sun_data)
    sun.rotation_euler = (math.radians(48.0), 0.0, math.radians(35.0))
    bpy.context.scene.collection.objects.link(sun)
    lights.append(sun)
    return lights


def build():
    """Assemble the whole scene and return it."""
    scene = reset_scene()
    scene.world = materials.studio_world(strength=1.0)
    add_floor()
    add_objects()
    add_camera(scene)
    add_lights()
    return scene
