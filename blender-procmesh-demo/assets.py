"""The models: a lighthouse and the islet it stands on.

Read ``tower_profile`` first. It is eleven lines and it is the entire silhouette
of the building -- plinth, chamfer, tapered shaft with entasis, flared cornice,
gallery seat. Nothing in it mentions vertices, and that is the point: the same
eleven lines produce a 12-sided faceted low-poly tower and a 96-sided one with
bevelled corners and masonry courses, because the caller decides the density.

Everything else in this file is the same idea applied to the parts a lathe
cannot make: openings are booleans, the railing and the lantern posts are
radial arrays, the islet is an icosphere pushed around by a noise function.
"""

from __future__ import annotations

import math

from mathutils import Vector

import materials
import meshlib as ml

# ---------------------------------------------------------------------------
# Dimensions, in metres. Change one and everything downstream follows.
# ---------------------------------------------------------------------------

PLINTH_RADIUS = 1.85
PLINTH_TOP = 0.55
SHAFT_BOTTOM = 0.78
SHAFT_TOP_RADIUS = 1.02
SHAFT_TOP = 6.60
CORNICE_RADIUS = 1.52
GALLERY_Z = 7.62
DECK_RADIUS = 1.66
DECK_TOP = 7.82
RAIL_RADIUS = 1.48
RAIL_TOP = 8.62
LANTERN_RADIUS = 0.92
LANTERN_TOP = 9.72
ROOF_APEX = 10.78

# Openings: (height of the arch base, azimuth in degrees, width, height).
# -90 degrees faces the camera, so the door and one window are always readable.
WINDOWS = [
    (2.30, -68.0, 0.52, 1.05),
    (3.85, 52.0, 0.52, 1.05),
    (5.30, -170.0, 0.52, 1.05),
    (5.30, -20.0, 0.52, 1.05),
]
DOOR = (0.62, -90.0, 0.78, 1.55)

NICHE_DEPTH = 0.30
CUTTER_DEPTH = 0.9
STONE_SEED = 90210


def tower_profile():
    """The lighthouse silhouette, as an outline with no resolution.

    ``bulge=-0.045`` on the shaft is *entasis*: the wall bows very slightly
    inward on its way up instead of tapering in a straight line. It is the
    difference between a lighthouse and a length of pipe, it is invisible until
    you remove it, and here it is one number on one line.
    """
    return (
        ml.Profile(0.0, 0.0)
        .line_to(PLINTH_RADIUS, 0.0)
        .line_to(PLINTH_RADIUS, PLINTH_TOP)
        .line_to(1.60, SHAFT_BOTTOM)
        .curve_to(SHAFT_TOP_RADIUS, SHAFT_TOP, bulge=-0.045, steps=12)
        .line_to(1.00, 6.78)
        .curve_to(CORNICE_RADIUS, 7.18, bulge=0.42, steps=6)
        .line_to(CORNICE_RADIUS, 7.30)
        .line_to(1.06, 7.46)
        .line_to(0.96, GALLERY_Z)
        .line_to(0.0, GALLERY_Z)
    )


def _cutter(name, width, height, azimuth, base_z, wall_radius, arch_steps=10,
            depth=CUTTER_DEPTH, shrink=0.0, niche=NICHE_DEPTH):
    """An arched prism, positioned to bite ``niche`` metres into the wall.

    The prism is built lying in the XZ plane and extruded along Y, so it has to
    be turned to point outward: rotating by ``azimuth - 90`` maps its local +Y
    onto the radial direction. Getting this wrong is the classic scripted
    boolean failure -- the cutter is fine, it is just aimed at nothing.
    """
    outline = ml.arch_outline(width - shrink, height - shrink, steps=arch_steps)
    bm = ml.extrude_outline(outline, depth)
    obj = ml.object_from_bmesh(name, bm)

    angle = math.radians(azimuth)
    radial = wall_radius + depth / 2.0 - niche
    obj.location = Vector((radial * math.cos(angle), radial * math.sin(angle), base_z))
    obj.rotation_euler = (0.0, 0.0, angle - math.pi / 2.0)
    return obj


def tower(detail, collection=None):
    """The masonry tower: lathe, then cut, then bevel, then roughen."""
    # Seed the noise before touching it. Without this the stone displacement
    # depends on whatever called mathutils.noise last, which perturbs the
    # dihedral angles just enough to flip a few edges either side of the
    # crease threshold -- so the triangle count changes between runs.
    ml.seed(STONE_SEED)
    profile = tower_profile()
    points = profile.sample(detail.profile_density)
    points = ml.insert_grooves(
        points, spacing=detail.course_spacing, depth=0.015, half_width=0.048,
        z_from=SHAFT_BOTTOM + 0.25, z_to=SHAFT_TOP - 0.1,
    )

    bm = ml.lathe(points, detail.lathe_steps)
    obj = ml.object_from_bmesh("Tower", bm, material=materials.stone(),
                               collection=collection)

    # Openings are booleans against the solid tower, done before any bevelling
    # so the bevel rounds the reveals too.
    # The arch resolution follows the detail level too. A low-poly building
    # with a perfectly smooth arch over its door looks like a mistake.
    arch_steps = max(3, int(round(10 * detail.profile_density)))

    panes = []
    for base_z, azimuth, width, height in WINDOWS:
        wall = ml.radius_at(points, base_z + height * 0.5)
        ml.boolean(obj, _cutter("WinCut", width, height, azimuth, base_z, wall,
                                arch_steps=arch_steps))
        panes.append((base_z, azimuth, width, height, wall, arch_steps))

    door_z, door_azimuth, door_width, door_height = DOOR
    door_wall = ml.radius_at(points, door_z + door_height * 0.5)
    ml.boolean(obj, _cutter("DoorCut", door_width, door_height, door_azimuth,
                            door_z, door_wall, arch_steps=arch_steps))

    with ml.edit(obj) as bm:
        ml.bevel_creases(bm, detail.bevel_width, detail.bevel_segments,
                         angle=detail.bevel_angle)
        if detail.displace_stone > 0.0:
            amplitude = detail.displace_stone
            ml.displace_verts(bm, lambda co, normal: normal * (
                amplitude * ml.fractal_at(co, scale=1.7, octaves=4)))

    ml.shade(obj, detail.shading, detail.crease_angle)

    fittings = [_pane(index, *pane, collection=collection)
                for index, pane in enumerate(panes)]
    fittings.append(_door_slab(door_z, door_azimuth, door_width, door_height,
                               door_wall, arch_steps, collection))
    return [obj] + fittings


def _pane(index, base_z, azimuth, width, height, wall, arch_steps, collection):
    """A dark pane sunk into the back of each window niche."""
    outline = ml.arch_outline(width - 0.09, height - 0.06, steps=arch_steps)
    bm = ml.extrude_outline(outline, 0.05)
    obj = ml.object_from_bmesh(f"Pane{index}", bm, material=materials.metal(),
                               collection=collection)
    angle = math.radians(azimuth)
    radial = wall - NICHE_DEPTH + 0.03
    obj.location = Vector((radial * math.cos(angle), radial * math.sin(angle),
                           base_z + 0.03))
    obj.rotation_euler = (0.0, 0.0, angle - math.pi / 2.0)
    ml.shade(obj, "flat")
    return obj


def _door_slab(base_z, azimuth, width, height, wall, arch_steps, collection):
    outline = ml.arch_outline(width - 0.10, height - 0.07, steps=arch_steps)
    bm = ml.extrude_outline(outline, 0.08)
    obj = ml.object_from_bmesh("Door", bm, material=materials.trim(),
                               collection=collection)
    angle = math.radians(azimuth)
    radial = wall - NICHE_DEPTH + 0.05
    obj.location = Vector((radial * math.cos(angle), radial * math.sin(angle),
                           base_z + 0.035))
    obj.rotation_euler = (0.0, 0.0, angle - math.pi / 2.0)
    ml.shade(obj, "flat")
    return obj


def gallery(detail, collection=None):
    """Deck, balusters and handrails -- radial arrays, not modelled repeats."""
    parts = []

    deck_points = [(0.0, 7.58), (DECK_RADIUS, 7.58), (DECK_RADIUS, DECK_TOP),
                   (0.0, DECK_TOP)]
    bm = ml.lathe(deck_points, detail.lathe_steps)
    ml.bevel_creases(bm, detail.bevel_width, detail.bevel_segments,
                     angle=detail.bevel_angle)
    deck = ml.object_from_bmesh("Deck", bm, material=materials.stone(),
                                collection=collection)
    ml.shade(deck, detail.shading, detail.crease_angle)
    parts.append(deck)

    # One baluster mesh, instanced around the deck. Changing the count is a
    # one-character edit; by hand it is a rebuild of the whole railing.
    baluster_count = max(8, detail.lantern_sides * 2)
    for index, (position, angle) in enumerate(
            ml.radial(baluster_count, RAIL_RADIUS, DECK_TOP)):
        bm = ml.cylinder(0.032, RAIL_TOP - DECK_TOP, detail.ring_steps)
        post = ml.object_from_bmesh(f"Baluster{index}", bm,
                                    material=materials.metal(),
                                    collection=collection)
        post.location = position + Vector((0.0, 0.0, (RAIL_TOP - DECK_TOP) / 2.0))
        ml.shade(post, detail.shading, detail.crease_angle)
        parts.append(post)

    for name, height, minor in (("HandRail", RAIL_TOP, 0.055),
                                ("MidRail", DECK_TOP + 0.42, 0.032)):
        bm = ml.torus(RAIL_RADIUS, minor, detail.lathe_steps, detail.ring_steps)
        rail = ml.object_from_bmesh(name, bm, material=materials.metal(),
                                    collection=collection)
        rail.location = Vector((0.0, 0.0, height))
        ml.shade(rail, detail.shading, detail.crease_angle)
        parts.append(rail)

    return parts


def lantern(detail, collection=None):
    """The glazed room, its roof, and the light itself."""
    parts = []
    sides = detail.lantern_sides

    base_points = [(0.0, DECK_TOP), (1.02, DECK_TOP), (1.02, DECK_TOP + 0.16),
                   (0.0, DECK_TOP + 0.16)]
    bm = ml.lathe(base_points, sides)
    ring = ml.object_from_bmesh("LanternBase", bm, material=materials.trim(),
                                collection=collection)
    ml.shade(ring, detail.shading, detail.crease_angle)
    parts.append(ring)

    glass_bottom = DECK_TOP + 0.16
    glass_height = LANTERN_TOP - glass_bottom
    bm = ml.cylinder(LANTERN_RADIUS - 0.04, glass_height, sides, cap=False)
    glazing = ml.object_from_bmesh("Glazing", bm, material=materials.glass(),
                                   collection=collection)
    glazing.location = Vector((0.0, 0.0, glass_bottom + glass_height / 2.0))
    ml.shade(glazing, "flat")
    parts.append(glazing)

    # Mullions between the panes: one box per side, turned to face outward.
    for index, (position, angle) in enumerate(
            ml.radial(sides, LANTERN_RADIUS, glass_bottom + glass_height / 2.0,
                      phase=math.pi / sides)):
        bm = ml.box(0.075, 0.075, glass_height)
        ml.bevel_creases(bm, detail.bevel_width, detail.bevel_segments,
                         angle=detail.bevel_angle)
        post = ml.object_from_bmesh(f"Mullion{index}", bm,
                                    material=materials.trim(),
                                    collection=collection)
        post.location = position
        post.rotation_euler = (0.0, 0.0, angle)
        ml.shade(post, detail.shading, detail.crease_angle)
        parts.append(post)

    cap_points = [(0.0, LANTERN_TOP), (1.10, LANTERN_TOP),
                  (1.10, LANTERN_TOP + 0.14), (0.0, LANTERN_TOP + 0.14)]
    bm = ml.lathe(cap_points, sides)
    cap = ml.object_from_bmesh("LanternCap", bm, material=materials.trim(),
                               collection=collection)
    ml.shade(cap, detail.shading, detail.crease_angle)
    parts.append(cap)

    roof_bottom = LANTERN_TOP + 0.14
    bm = ml.cone(1.16, 0.06, ROOF_APEX - roof_bottom, sides)
    roof = ml.object_from_bmesh("Roof", bm, material=materials.trim(),
                                collection=collection)
    roof.location = Vector((0.0, 0.0, (roof_bottom + ROOF_APEX) / 2.0))
    ml.shade(roof, detail.shading, detail.crease_angle)
    parts.append(roof)

    bm = ml.icosphere(detail.prop_subdivisions, 0.11)
    finial = ml.object_from_bmesh("Finial", bm, material=materials.metal(),
                                  collection=collection)
    finial.location = Vector((0.0, 0.0, ROOF_APEX + 0.06))
    ml.shade(finial, detail.shading, detail.crease_angle)
    parts.append(finial)

    bm = ml.icosphere(detail.prop_subdivisions, 0.34)
    bulb = ml.object_from_bmesh("Lamp", bm, material=materials.lamp(),
                                collection=collection)
    bulb.location = Vector((0.0, 0.0, glass_bottom + glass_height * 0.45))
    ml.shade(bulb, detail.shading, detail.crease_angle)
    parts.append(bulb)

    return parts


def lighthouse(detail, collection=None):
    """Every part of the building, at one detail level."""
    return (tower(detail, collection)
            + gallery(detail, collection)
            + lantern(detail, collection))


# ---------------------------------------------------------------------------
# The islet
# ---------------------------------------------------------------------------

ISLET_RADIUS = 8.5
ISLET_SQUASH = 0.55
PLATEAU_RADIUS = 3.4
PLATEAU_Z = 2.90


def islet(detail, collection=None, seed=20240817):
    """A rock, as a sphere pushed around by a function.

    The shape is an icosphere squashed on Z and then displaced along its own
    normals by fractal noise. Two things shape the noise rather than the mesh:

    * the amplitude falls off near the middle, which flattens a plateau for the
      lighthouse to stand on -- so the building always has ground under it, at
      any detail level, without anyone levelling it by hand;
    * the amplitude rises near the waterline, so the sides are eroded and
      broken while the top stays walkable.

    Both are three lines of arithmetic. Sculpting the same thing by hand is a
    brush, a tablet and an afternoon -- but it is also *art directable* in a way
    this is not, which is the honest limit of the technique.
    """
    ml.seed(seed)
    bm = ml.icosphere(detail.rock_subdivisions, ISLET_RADIUS)

    for vert in bm.verts:
        vert.co.z *= ISLET_SQUASH
    bm.normal_update()

    def displacement(co, normal):
        horizontal = math.hypot(co.x, co.y)
        plateau = _smoothstep(PLATEAU_RADIUS - 0.9, PLATEAU_RADIUS + 1.8, horizontal)
        # Two frequencies: a broad one that decides where the headlands and
        # inlets are, and a finer one that breaks the surface into facets. A
        # single octave band gives a smooth blob that reads as a sand dune.
        erosion = 1.0 - _smoothstep(-1.0, 3.4, co.z)
        broad = ml.fractal_at(co, scale=0.16, octaves=max(3, detail.rock_octaves - 3))
        fine = ml.fractal_at(co, scale=0.62, octaves=detail.rock_octaves,
                             offset=(31.7, -12.4, 5.9))
        amount = broad * 1.15 + fine * 0.55
        return normal * (amount * (1.0 + 2.6 * erosion) * (0.18 + 0.82 * plateau))

    ml.displace_verts(bm, displacement)

    # Flatten the top of the plateau so the tower is not standing on a slope.
    for vert in bm.verts:
        horizontal = math.hypot(vert.co.x, vert.co.y)
        if vert.co.z > 0.0 and horizontal < PLATEAU_RADIUS + 1.6:
            blend = 1.0 - _smoothstep(PLATEAU_RADIUS - 0.6, PLATEAU_RADIUS + 1.6,
                                      horizontal)
            vert.co.z += (PLATEAU_Z - vert.co.z) * blend

    ml.weld(bm, 1e-4)
    obj = ml.object_from_bmesh("Islet", bm, material=materials.rock(),
                               collection=collection)
    ml.shade(obj, detail.shading, detail.crease_angle)
    return obj


def _smoothstep(edge0, edge1, x):
    if edge1 <= edge0:
        return 0.0 if x < edge0 else 1.0
    t = min(1.0, max(0.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def grass_tuft(detail, collection=None):
    """The mesh that gets instanced over the islet by the scatter node group."""
    bm = ml.cone(0.085, 0.0, 0.52, max(3, detail.ring_steps // 3))
    obj = ml.object_from_bmesh("GrassTuft", bm, material=materials.grass(),
                               collection=collection)
    # The instance source itself should not be visible in the render; only the
    # instances the modifier generates are.
    obj.hide_render = True
    obj.location = Vector((0.0, 0.0, -50.0))
    ml.shade(obj, "flat")
    return obj


def sea(size=400.0, collection=None):
    bm = ml.box(size, size, 0.2)
    obj = ml.object_from_bmesh("Sea", bm, material=materials.sea(),
                               collection=collection)
    obj.location = Vector((0.0, 0.0, -0.1))
    ml.shade(obj, "flat")
    return obj
