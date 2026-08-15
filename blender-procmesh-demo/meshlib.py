"""Mesh construction from Python: the operations, and what they map to in the GUI.

Every function here is the scripted form of something a modeller does by hand.
The mapping is one to one, because it is the same code underneath -- ``bmesh.ops``
*is* what edit mode calls when you press a key:

    edit mode                       this module / bmesh.ops
    ---------------------------------------------------------------
    Screw / Spin (Alt-R)            lathe()            -> bmesh.ops.spin
    Extrude (E)                     extrude()          -> bmesh.ops.extrude_face_region
    Inset (I)                       inset()            -> bmesh.ops.inset_region
    Bevel (Ctrl-B)                  bevel()            -> bmesh.ops.bevel
    Subdivide (right click)         subdivide()        -> bmesh.ops.subdivide_edges
    Merge by Distance (M)           weld()             -> bmesh.ops.remove_doubles
    Shade Auto Smooth               shade()            -> bmesh.ops.split_edges
    Add > Mesh > Ico Sphere         icosphere()        -> bmesh.ops.create_icosphere
    the Modifier stack              modifier(), bake()

Two things are worth knowing before reading further.

**Nothing here needs a window.** ``bmesh`` is a pure data API with no dependency
on the UI. The ``bpy.ops.mesh.*`` operators *do* depend on context (an active
object, the right mode), which is what makes people think headless modelling is
awkward. Going through ``bmesh`` sidesteps that entirely: no context, no mode
switching, no selection state.

**Modifiers are lazy.** ``obj.modifiers.new(...)`` only records intent; the mesh
on disk is unchanged until something evaluates the dependency graph. ``bake()``
below forces that evaluation and writes the result back, which is the scripted
equivalent of Ctrl-A on a modifier -- and is necessary if you want to measure
the real polygon count, or feed the result into a boolean.
"""

from __future__ import annotations

import math
from contextlib import contextmanager

import bmesh
import bpy
from mathutils import Vector, noise

TAU = math.tau


# ---------------------------------------------------------------------------
# Profiles: an outline that has no resolution until you ask for one
# ---------------------------------------------------------------------------


class Profile:
    """A 2-D outline in the (radius, height) plane, stored as segments.

    This is the part a GUI cannot give you. In the shader editor or the 3-D
    viewport you place *vertices*: the moment you draw the tower's silhouette
    you have committed to how many points it has. Here the silhouette is a list
    of segments -- straight or curved -- and the vertex count is decided later,
    by ``sample(density)``. One outline, every level of detail.

    Coordinates are ``(radius, height)``. ``lathe()`` spins the result around
    the Z axis; ``extrude()`` sweeps it along Y.
    """

    def __init__(self, radius, height):
        self.start = (float(radius), float(height))
        self.segments = []

    def line_to(self, radius, height):
        """A straight run. One segment, one edge, at any density."""
        self.segments.append(("line", (float(radius), float(height)), 0.0, 1))
        return self

    def curve_to(self, radius, height, bulge=0.0, steps=6):
        """A curved run, as a quadratic Bezier.

        ``bulge`` offsets the control point perpendicular to the chord, as a
        fraction of the chord length: positive bows outward (away from the
        axis), negative inward. A lighthouse shaft with ``bulge=-0.05`` has
        *entasis* -- the slight concave taper that stops a tall cylinder
        reading as a drainpipe. It costs one number here; by hand it is a
        careful edge-loop nudge repeated up the tower.
        """
        self.segments.append(("curve", (float(radius), float(height)),
                              float(bulge), int(steps)))
        return self

    def sample(self, density=1.0):
        """Realise the outline as points at the requested density."""
        points = [self.start]
        cursor = self.start
        for kind, target, bulge, steps in self.segments:
            if kind == "line":
                points.append(target)
            else:
                count = max(2, int(round(steps * density)))
                points.extend(_bezier_points(cursor, target, bulge, count))
            cursor = target
        return _dedupe(points)


def _bezier_points(start, end, bulge, count):
    """Points along a quadratic Bezier from ``start`` to ``end``, excluding start."""
    ax, ay = start
    bx, by = end
    mid = Vector(((ax + bx) / 2.0, (ay + by) / 2.0))
    chord = Vector((bx - ax, by - ay))
    # Perpendicular in 2-D: rotate the chord by 90 degrees.
    perpendicular = Vector((-chord.y, chord.x))
    if perpendicular.length > 1e-9:
        perpendicular.normalize()
    control = mid + perpendicular * (bulge * chord.length)

    out = []
    for step in range(1, count + 1):
        t = step / count
        u = 1.0 - t
        x = u * u * ax + 2 * u * t * control.x + t * t * bx
        y = u * u * ay + 2 * u * t * control.y + t * t * by
        out.append((x, y))
    return out


def _dedupe(points, epsilon=1e-6):
    out = [points[0]]
    for point in points[1:]:
        if abs(point[0] - out[-1][0]) > epsilon or abs(point[1] - out[-1][1]) > epsilon:
            out.append(point)
    return out


# ---------------------------------------------------------------------------
# Primitive construction
# ---------------------------------------------------------------------------


def lathe(points, steps, weld_distance=1e-4):
    """Spin a profile around the Z axis. The Screw/Spin tool, in code.

    ``points`` is a list of ``(radius, height)``. A point at radius 0 closes
    the surface into a cap, exactly as it does when you lathe by hand -- the
    ring collapses to a single vertex and the quads there become triangles.
    That collapse is why the weld at the end is not optional: a full 360-degree
    spin also leaves the first and last rings sitting on top of each other.
    """
    bm = bmesh.new()
    verts = [bm.verts.new((radius, 0.0, height)) for radius, height in points]
    edges = [bm.edges.new(pair) for pair in zip(verts, verts[1:])]

    bmesh.ops.spin(
        bm,
        geom=verts + edges,
        axis=(0.0, 0.0, 1.0),
        cent=(0.0, 0.0, 0.0),
        dvec=(0.0, 0.0, 0.0),
        angle=TAU,
        steps=steps,
        use_merge=False,
    )

    weld(bm, weld_distance)
    bmesh.ops.dissolve_degenerate(bm, dist=weld_distance, edges=bm.edges[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def extrude_outline(points, depth, close=True):
    """Sweep a closed 2-D outline along Y into a solid. Extrude, in code.

    ``points`` are ``(x, z)``. Used here for the window and door cutters: an
    arched opening is a rectangle whose top edge is a half circle, which is
    four lines and one curve rather than a mesh anyone has to model.
    """
    bm = bmesh.new()
    verts = [bm.verts.new((x, -depth / 2.0, z)) for x, z in points]
    face = bm.faces.new(verts) if close else None

    result = bmesh.ops.extrude_face_region(bm, geom=[face])
    moved = [element for element in result["geom"] if isinstance(element, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=moved, vec=(0.0, depth, 0.0))

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def arch_outline(width, height, steps=10):
    """A rectangle capped with a semicircle -- a window or door opening."""
    half = width / 2.0
    straight = height - half
    points = [(-half, 0.0), (half, 0.0), (half, straight)]
    for step in range(1, steps):
        angle = math.pi * step / steps
        points.append((half * math.cos(angle), straight + half * math.sin(angle)))
    points.append((-half, straight))
    return points


def radius_at(points, height):
    """Interpolate a profile's radius at a given height.

    Needed to place things *on* a tapered surface -- a window has to be cut at
    whatever radius the wall happens to have at that height, and the wall is a
    curve. By hand you snap to the surface; in code you evaluate it.
    """
    candidates = []
    for (r0, z0), (r1, z1) in zip(points, points[1:]):
        low, high = min(z0, z1), max(z0, z1)
        if low - 1e-9 <= height <= high + 1e-9:
            if abs(z1 - z0) < 1e-9:
                candidates.extend((r0, r1))
            else:
                t = (height - z0) / (z1 - z0)
                candidates.append(r0 + t * (r1 - r0))
    if not candidates:
        return max(r for r, _ in points)
    return max(candidates)


def insert_grooves(points, spacing, depth, half_width, z_from, z_to):
    """Cut horizontal grooves into a sampled profile: masonry courses.

    This is the demo's answer to "do you have to carve the detail by hand?" for
    one specific kind of detail. The mortar lines between stone courses are not
    modelled, sculpted or textured here -- they are three extra points in the
    outline, repeated up the shaft, and the lathe turns them into rings.

    Two properties fall out for free and are the reason to do it this way:
    the grooves follow the taper (the radius is looked up per course, so they
    stay flush on a wall that is narrowing), and their cost is independent of
    the radial resolution.
    """
    if spacing <= 0.0:
        return points

    heights = []
    height = z_from + spacing
    while height < z_to:
        heights.append(height)
        height += spacing

    out = [points[0]]
    for (r0, z0), (r1, z1) in zip(points, points[1:]):
        # Only groove the upward, roughly vertical runs -- not the plinth top
        # or the underside of the cornice.
        upward = z1 > z0 + 1e-9
        for groove in heights:
            if not upward or not (z0 < groove < z1):
                continue
            t = (groove - z0) / (z1 - z0)
            radius = r0 + t * (r1 - r0)
            out.append((radius, groove - half_width))
            out.append((radius - depth, groove))
            out.append((radius, groove + half_width))
        out.append((r1, z1))
    return _dedupe(out)


def icosphere(subdivisions, radius):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=radius)
    return bm


def cylinder(radius, depth, segments, cap=True):
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm,
        cap_ends=cap,
        cap_tris=False,
        segments=segments,
        radius1=radius,
        radius2=radius,
        depth=depth,
    )
    return bm


def cone(radius_bottom, radius_top, depth, segments, cap=True):
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm,
        cap_ends=cap,
        cap_tris=False,
        segments=segments,
        radius1=radius_bottom,
        radius2=radius_top,
        depth=depth,
    )
    return bm


def box(size_x, size_y, size_z):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(size_x, size_y, size_z), verts=bm.verts[:])
    return bm


def torus(major_radius, minor_radius, major_steps, minor_steps):
    """Built by lathing a circle -- there is no create_torus in bmesh.ops.

    A worked example of the general principle: when a primitive is missing,
    a profile plus a spin is usually the whole answer.
    """
    circle = []
    for step in range(minor_steps):
        angle = TAU * step / minor_steps
        circle.append((major_radius + minor_radius * math.cos(angle),
                       minor_radius * math.sin(angle)))
    circle.append(circle[0])

    bm = bmesh.new()
    verts = [bm.verts.new((r, 0.0, z)) for r, z in circle[:-1]]
    edges = [bm.edges.new((verts[i], verts[(i + 1) % len(verts)]))
             for i in range(len(verts))]
    bmesh.ops.spin(bm, geom=verts + edges, axis=(0.0, 0.0, 1.0), cent=(0.0, 0.0, 0.0),
                   dvec=(0.0, 0.0, 0.0), angle=TAU, steps=major_steps, use_merge=False)
    weld(bm, 1e-4)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


# ---------------------------------------------------------------------------
# Edit-mode operations
# ---------------------------------------------------------------------------


def weld(bm, distance=1e-4):
    """Merge by Distance."""
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=distance)
    return bm


def inset(bm, faces, thickness, depth=0.0):
    """Inset Faces. Returns the new inner faces."""
    result = bmesh.ops.inset_region(
        bm, faces=faces, thickness=thickness, depth=depth,
        use_even_offset=True, use_interpolate=True,
    )
    return result["faces"]


def extrude(bm, faces, offset):
    """Extrude Region along a vector. Returns the moved faces."""
    result = bmesh.ops.extrude_face_region(bm, geom=faces)
    verts = [e for e in result["geom"] if isinstance(e, bmesh.types.BMVert)]
    new_faces = [e for e in result["geom"] if isinstance(e, bmesh.types.BMFace)]
    bmesh.ops.translate(bm, verts=verts, vec=Vector(offset))
    # extrude_face_region leaves the original faces in place, facing inward.
    bmesh.ops.delete(bm, geom=faces, context="FACES")
    return new_faces


def bevel(bm, width, segments, edges=None, harden=True):
    """Bevel edges. Skipped entirely when width is 0, which is the low-poly case."""
    if width <= 0.0 or segments <= 0:
        return bm
    target = edges if edges is not None else bm.edges[:]
    bmesh.ops.bevel(
        bm, geom=target, offset=width, offset_type="OFFSET",
        segments=segments, profile=0.5, affect="EDGES",
        clamp_overlap=True, miter_outer="ARC" if harden else "SHARP",
    )
    return bm


def bevel_creases(bm, width, segments, angle=30.0):
    """Bevel only the edges that are actually corners.

    Bevelling every edge of a lathed surface is the classic scripted mistake:
    the longitudinal edges running up a smooth tower are not corners, and
    rounding them wastes geometry and pinches the silhouette. Selecting by
    dihedral angle first is what a modeller does by eye with Select Sharp
    Edges, and on the tower it is the difference between 170k triangles and
    30k for the same visible result.
    """
    if width <= 0.0 or segments <= 0:
        return bm
    return bevel(bm, width, segments, edges=sharp_edges(bm, angle))


def subdivide(bm, cuts=1, edges=None, smooth=0.0):
    """Subdivide edges. ``smooth=1.0`` is Catmull-Clark, the Subdivision
    Surface modifier's algorithm applied straight to the mesh."""
    bmesh.ops.subdivide_edges(
        bm, edges=edges if edges is not None else bm.edges[:],
        cuts=cuts, smooth=smooth, smooth_falloff="LINEAR", use_grid_fill=True,
    )
    return bm


def sharp_edges(bm, angle_degrees):
    """Edges whose two faces meet at more than ``angle_degrees``."""
    threshold = math.radians(angle_degrees)
    out = []
    for edge in bm.edges:
        if len(edge.link_faces) != 2:
            out.append(edge)
            continue
        if edge.calc_face_angle(0.0) > threshold:
            out.append(edge)
    return out


def displace_verts(bm, function):
    """Move every vertex by ``function(position, normal) -> Vector``.

    The Displace modifier with a procedural texture, except the "texture" is
    a Python function and can be anything -- including something that reads
    the vertex's own position, which is how the rock gets more erosion low
    down than at the peak.
    """
    bm.normal_update()
    for vert in bm.verts:
        vert.co += function(vert.co.copy(), vert.normal.copy())
    bm.normal_update()
    return bm


# ---------------------------------------------------------------------------
# Objects, modifiers, shading
# ---------------------------------------------------------------------------


def object_from_bmesh(name, bm, material=None, collection=None, free=True):
    """Turn a bmesh into a real scene object."""
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    if free:
        bm.free()
    obj = bpy.data.objects.new(name, mesh)
    if material is not None:
        obj.data.materials.append(material)
    (collection or bpy.context.scene.collection).objects.link(obj)
    return obj


@contextmanager
def edit(obj):
    """Enter and leave "edit mode" on an object, without a mode or a window.

    ``with edit(obj) as bm:`` reads like Tab in the viewport and does the same
    job, but it is a plain data round-trip: read the mesh into a bmesh, run
    operators, write it back. No active object, no selection, no context.
    """
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        yield bm
    finally:
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()


def modifier(obj, kind, name=None, **properties):
    modifier_ = obj.modifiers.new(name or kind.title(), kind)
    for key, value in properties.items():
        setattr(modifier_, key, value)
    return modifier_


def bake(obj):
    """Evaluate the modifier stack and write the result into the object's mesh.

    Modifiers are a *description* of geometry, not geometry. Until the
    dependency graph is evaluated, ``len(obj.data.polygons)`` still reports the
    pre-modifier count -- which is the usual reason a scripted poly-count table
    comes out wrong. Booleans also need real geometry to cut against, so
    anything feeding a boolean has to be baked first.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    baked = bpy.data.meshes.new_from_object(evaluated)

    obj.modifiers.clear()
    old = obj.data
    obj.data = baked
    baked.name = old.name
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return obj


def boolean(target, cutter, operation="DIFFERENCE", remove_cutter=True):
    """Cut one object out of another, and bake the result immediately.

    ``use_self`` is not optional here, and finding that out costs an afternoon.
    Without it the EXACT solver assumes neither operand intersects itself and
    takes a faster path; a lathed surface breaks that assumption at its poles,
    where a whole ring of faces collapses onto a single vertex. When the
    assumption fails the modifier does not raise -- it evaluates to an **empty
    mesh**, so the object silently disappears from the render while every
    surrounding part is still there.

    Worse, it is density-dependent: the same code cut the same door correctly
    at 24 lathe segments and produced nothing at 96, which makes it look like a
    problem with the detail level rather than with the boolean. Hence the
    verify-and-retry below: if EXACT yields nothing, fall back to the FAST
    solver rather than shipping a hole in the model.
    """
    backup = target.data.copy()
    succeeded = False

    for solver in ("EXACT", "FAST"):
        cut = modifier(target, "BOOLEAN", "Cut", operation=operation,
                       object=cutter, solver=solver)
        if hasattr(cut, "use_self"):
            cut.use_self = True
        bake(target)

        if len(target.data.vertices):
            succeeded = True
            break

        print(f"[meshlib] boolean on {target.name!r} came back empty with the "
              f"{solver} solver; retrying")
        stale = target.data
        target.data = backup.copy()
        if stale.users == 0:
            bpy.data.meshes.remove(stale)

    if backup.users == 0:
        bpy.data.meshes.remove(backup)
    if not succeeded:
        raise RuntimeError(
            f"boolean {operation} produced an empty mesh for {target.name!r}"
        )

    if remove_cutter:
        mesh = cutter.data
        bpy.data.objects.remove(cutter, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    return target


def shade(obj, mode="smooth", crease_angle=34.0):
    """Flat facets, or smooth shading with hard creases preserved.

    Blender 4.1 removed ``mesh.use_auto_smooth`` in favour of a modifier, so
    neither spelling works on every version. Splitting the sharp edges
    geometrically does: duplicate the vertices along any crease steeper than
    ``crease_angle``, then mark every face smooth. The normals then break
    exactly where they should on 3.x, 4.0 and 4.2 alike, at the cost of a few
    duplicated vertices along the creases -- which is what auto-smooth was
    doing behind the scenes anyway.
    """
    mesh = obj.data
    if mode == "flat":
        for polygon in mesh.polygons:
            polygon.use_smooth = False
        mesh.update()
        return obj

    bm = bmesh.new()
    bm.from_mesh(mesh)
    creases = sharp_edges(bm, crease_angle)
    if creases:
        bmesh.ops.split_edges(bm, edges=creases)
    bm.to_mesh(mesh)
    bm.free()

    for polygon in mesh.polygons:
        polygon.use_smooth = True
    mesh.update()
    return obj


def transform(obj, location=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1)):
    obj.location = Vector(location)
    obj.rotation_euler = rotation
    obj.scale = Vector(scale)
    return obj


def stats(obj):
    """(vertices, triangles) after evaluating modifiers.

    ``to_mesh`` hands back a temporary mesh owned by the evaluated object, and
    ``to_mesh_clear`` is what releases it. Skipping that leaks one mesh per
    call, which adds up quickly when this is used to total a whole scene.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    triangles = sum(len(polygon.vertices) - 2 for polygon in mesh.polygons)
    counts = (len(mesh.vertices), triangles)
    evaluated.to_mesh_clear()
    return counts


def radial(count, radius, height=0.0, phase=0.0):
    """Positions and angles evenly spaced around the Z axis.

    The scripted form of an Array modifier with an empty rotating it, and the
    reason the railing takes one line: change ``count`` and the balusters
    redistribute themselves, which by hand is a rebuild.
    """
    for index in range(count):
        angle = phase + TAU * index / count
        yield Vector((radius * math.cos(angle), radius * math.sin(angle), height)), angle


# ---------------------------------------------------------------------------
# Noise
# ---------------------------------------------------------------------------


def seed(value):
    """Make every noise call below deterministic, so renders are reproducible."""
    noise.seed_set(value)


def fractal_at(position, scale=1.0, octaves=5, lacunarity=2.0, h=1.0, offset=(0, 0, 0)):
    """Multi-octave Perlin noise, from ``mathutils`` -- no dependency to install.

    Blender ships the same noise basis functions its procedural textures use,
    exposed to Python. So "procedural detail" does not mean wiring a texture
    into a Displace modifier and hoping: it can be an ordinary function of
    position, evaluated per vertex, with the rest of Python available to shape
    it.
    """
    point = (Vector(position) + Vector(offset)) * scale
    return noise.fractal(point, h, lacunarity, octaves)
