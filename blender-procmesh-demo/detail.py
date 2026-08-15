"""Detail levels.

The whole point of the demo lives in this file. A GUI modeller authors a *mesh*:
a fixed set of vertices, at one density, decided once. A script authors a
*definition* -- profiles, counts, radii, noise amplitudes -- and the mesh is a
function of that definition and a target density.

So "low poly or refined?" is not two models here. It is one model and one
argument. ``Detail`` is that argument: every builder in ``assets.py`` takes one
and asks it how finely to sample, how many segments to spin, whether to bevel,
whether to displace, and how to shade the result.

The three presets are chosen to be *stylistically* distinct, not merely denser:

``LOW``   deliberate low-poly. Flat shaded, visible facets, no bevels, no
         displacement. The facets are the look, not an artefact -- so the
         segment counts are picked to read well faceted (8 and 12 sided),
         not to approximate a circle.
``MID``   a game-ready middle: smooth shading with split creases, small bevels,
         no displacement.
``HIGH``  refined. Dense sampling, bevelled edges, subdivision where it helps,
         and real geometric displacement on the stone and rock -- not a bump
         map, actual vertices moved.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Detail:
    """How densely to realise a model, and which refinements to apply."""

    name: str

    # --- sampling density -------------------------------------------------
    lathe_steps: int
    """Radial segments for a surface of revolution (the tower, the deck)."""

    profile_density: float
    """Multiplier on the sample count of every curved profile segment."""

    ring_steps: int
    """Segments for small round parts: handrail, balusters, finial."""

    lantern_sides: int
    """Sides of the lantern room. Also drives its posts and panes."""

    rock_subdivisions: int
    """Icosphere subdivision level for the islet before displacement."""

    prop_subdivisions: int
    """Icosphere subdivision for small round props: the finial, the lamp bulb.

    Deliberately separate from ``rock_subdivisions``. They were briefly the same
    setting, and raising the islet's density to 6 quietly spent a third of the
    refined model's triangle budget on a light bulb the size of a football.
    Detail settings should be per-thing, not global.
    """

    # --- refinements ------------------------------------------------------
    bevel_width: float
    """Edge bevel in metres. 0 disables bevelling entirely."""

    bevel_segments: int

    course_spacing: float
    """Metres between masonry courses on the shaft. 0 leaves the wall smooth.

    These are real geometry -- three extra points in the tower's outline per
    course -- not a texture. See ``meshlib.insert_grooves``.
    """

    displace_stone: float
    """Amplitude, in metres, of geometric noise roughening the stone."""

    rock_octaves: int
    """Noise octaves on the islet. More octaves = finer rock detail."""

    subsurf: int
    """Catmull-Clark levels applied to the parts that are meant to be smooth."""

    shading: str
    """``"flat"`` for faceted low poly, ``"smooth"`` for split-crease smooth."""

    crease_angle: float = 40.0
    """Dihedral angle, in degrees, above which an edge stays hard when shading."""

    bevel_angle: float = 70.0
    """Dihedral angle above which an edge gets bevelled.

    Deliberately much stricter than ``crease_angle``. Only true corners -- the
    plinth, the cornice, the window reveals, all near 90 degrees -- should be
    rounded. The masonry courses meet at about 44 degrees and must not be:
    rounding them costs geometry, gains nothing visible, and the bevel operator
    slows down catastrophically as the selected edge set grows. See the README.
    """

    scatter_density: float = 0.0
    """Grass tufts per square metre on the islet. 0 disables the scatter."""


LOW = Detail(
    name="low",
    lathe_steps=12,
    profile_density=0.34,
    ring_steps=6,
    lantern_sides=8,
    rock_subdivisions=2,
    prop_subdivisions=1,
    bevel_width=0.0,
    bevel_segments=0,
    course_spacing=0.0,
    displace_stone=0.0,
    rock_octaves=3,
    subsurf=0,
    shading="flat",
    scatter_density=0.0,
)

MID = Detail(
    name="mid",
    lathe_steps=24,
    profile_density=1.0,
    ring_steps=10,
    lantern_sides=12,
    rock_subdivisions=4,
    prop_subdivisions=2,
    bevel_width=0.014,
    bevel_segments=1,
    course_spacing=0.62,
    displace_stone=0.0,
    rock_octaves=5,
    subsurf=0,
    shading="smooth",
    scatter_density=0.9,
)

HIGH = Detail(
    name="high",
    lathe_steps=48,
    profile_density=3.0,
    ring_steps=24,
    lantern_sides=16,
    rock_subdivisions=6,
    prop_subdivisions=3,
    bevel_width=0.018,
    bevel_segments=3,
    course_spacing=0.44,
    displace_stone=0.010,
    rock_octaves=9,
    subsurf=1,
    shading="smooth",
    scatter_density=2.6,
)

LEVELS = {level.name: level for level in (LOW, MID, HIGH)}


def get(name):
    try:
        return LEVELS[name]
    except KeyError:
        raise SystemExit(
            f"unknown detail level {name!r}; choose from {', '.join(LEVELS)}"
        ) from None
