"""Plastic and glass materials, built entirely from Python.

Each factory returns a ``bpy.types.Material``. Two families are covered:

* **Plastic** -- an opaque dielectric. Principled BSDF with ``metallic=0``,
  mid roughness, and optionally a clear coat. Renders correctly in any engine;
  no ray tracing required.
* **Glass** -- a transmissive dielectric. Principled BSDF with
  ``transmission=1`` and an IOR around 1.45-1.52. This is the material that
  *needs* traced rays to look right, because the pixel behind the surface is
  determined by refracting through it.

The last plastic (``textured_plastic``) wires a procedural noise chain into
bump and roughness. It is there to show what an actual multi-node graph looks
like in script form, rather than just setting sockets on one node.
"""

from __future__ import annotations

import bpy

from shadergraph import ShaderGraph, set_inputs


def _finish(graph, surface, viewport_color, refractive=False):
    """Attach a shader to the material output and set viewport/EEVEE hints."""
    output = graph.add("ShaderNodeOutputMaterial", label="Output")
    graph.link(surface, "BSDF", output, "Surface")
    graph.layout()

    material = graph.material
    material.diffuse_color = viewport_color
    if refractive:
        _enable_eevee_refraction(material)
    return material, output


def _enable_eevee_refraction(material):
    """Opt a material into legacy EEVEE's screen-space refraction.

    Ignored by Cycles and by EEVEE Next (4.2+), which trace rays instead.
    ``hasattr`` guards keep this working across Blender versions where these
    properties come and go.
    """
    if hasattr(material, "use_screen_refraction"):
        material.use_screen_refraction = True
    if hasattr(material, "blend_method"):
        material.blend_method = "HASHED"
    if hasattr(material, "shadow_method"):
        material.shadow_method = "HASHED"
    if hasattr(material, "use_raytrace_refraction"):
        material.use_raytrace_refraction = True


# --------------------------------------------------------------------------
# Plastics
# --------------------------------------------------------------------------

def glossy_plastic(name, color, roughness=0.22, coat=0.6):
    """Injection-moulded look: saturated base, tight highlight, clear coat.

    The coat layer is what separates "plastic" from "matte paint" -- it adds a
    second, sharper specular lobe on top of the diffuse body.
    """
    graph = ShaderGraph.for_material(name)
    bsdf = graph.add("ShaderNodeBsdfPrincipled", label="Plastic")
    set_inputs(
        bsdf,
        base_color=color,
        metallic=0.0,
        roughness=roughness,
        ior=1.46,
        coat_weight=coat,
        coat_roughness=0.03,
    )
    material, _ = _finish(graph, bsdf, color)
    return material


def matte_plastic(name, color, roughness=0.62):
    """Sandblasted / ABS look: broad, soft highlight, no coat."""
    graph = ShaderGraph.for_material(name)
    bsdf = graph.add("ShaderNodeBsdfPrincipled", label="Plastic")
    set_inputs(
        bsdf,
        base_color=color,
        metallic=0.0,
        roughness=roughness,
        ior=1.46,
        coat_weight=0.0,
    )
    material, _ = _finish(graph, bsdf, color)
    return material


def textured_plastic(name, color, noise_scale=18.0, bump_strength=0.25):
    """Plastic with a procedural grain driving both bump and roughness.

    Graph shape:

        TexCoord.Object -> Noise.Vector
        Noise.Fac -> Bump.Height    -> Plastic.Normal
        Noise.Fac -> Ramp.Fac       -> Plastic.Roughness

    One noise feeding two destinations is the sort of thing that is a couple of
    drags in the editor and a couple of ``link`` calls here.
    """
    graph = ShaderGraph.for_material(name)

    coords = graph.add("ShaderNodeTexCoord", label="TexCoord")
    noise = graph.add(
        "ShaderNodeTexNoise",
        label="Noise",
        inputs={"scale": noise_scale, "detail": 6.0, "distortion": 0.2},
    )
    bump = graph.add("ShaderNodeBump", label="Bump", inputs={"strength": bump_strength})
    ramp = graph.add("ShaderNodeValToRGB", label="RoughnessRamp")
    # Remap the noise into a narrow roughness band so the surface reads as one
    # material with grain, not two different materials.
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = (0.18, 0.18, 0.18, 1.0)
    ramp.color_ramp.elements[1].position = 0.75
    ramp.color_ramp.elements[1].color = (0.45, 0.45, 0.45, 1.0)

    bsdf = graph.add("ShaderNodeBsdfPrincipled", label="Plastic")
    set_inputs(bsdf, base_color=color, metallic=0.0, ior=1.46, coat_weight=0.35)

    graph.link(coords, "Object", noise, "Vector")
    graph.link(noise, "Fac", bump, "Height")
    graph.link(noise, "Fac", ramp, "Fac")
    graph.link(bump, "Normal", bsdf, "Normal")
    graph.link(ramp, "Color", bsdf, "Roughness")

    material, _ = _finish(graph, bsdf, color)
    return material


# --------------------------------------------------------------------------
# Glasses
# --------------------------------------------------------------------------

def clear_glass(name, ior=1.45):
    """Optical glass: full transmission, mirror-smooth surface."""
    graph = ShaderGraph.for_material(name)
    bsdf = graph.add("ShaderNodeBsdfPrincipled", label="Glass")
    set_inputs(
        bsdf,
        base_color=(1.0, 1.0, 1.0, 1.0),
        metallic=0.0,
        roughness=0.0,
        ior=ior,
        transmission=1.0,
    )
    material, _ = _finish(graph, bsdf, (0.8, 0.9, 1.0, 1.0), refractive=True)
    return material


def frosted_glass(name, roughness=0.22, ior=1.45):
    """Etched glass: transmission plus surface scatter.

    Rough transmission is expensive -- every ray leaving the surface goes in a
    slightly different direction, so this is the material that decides how many
    samples the render needs.
    """
    graph = ShaderGraph.for_material(name)
    bsdf = graph.add("ShaderNodeBsdfPrincipled", label="Glass")
    set_inputs(
        bsdf,
        base_color=(1.0, 1.0, 1.0, 1.0),
        metallic=0.0,
        roughness=roughness,
        ior=ior,
        transmission=1.0,
    )
    material, _ = _finish(graph, bsdf, (0.85, 0.88, 0.92, 1.0), refractive=True)
    return material


def tinted_glass(name, absorption=(0.22, 0.62, 0.50), density=0.85, ior=1.5):
    """Coloured glass done properly: clear surface + Volume Absorption inside.

    Tinting the *base colour* of a transmissive BSDF colours the surface, so a
    thick part and a thin part of the object look the same. Real glass gets its
    colour from light being absorbed along the path through it, which means the
    tint belongs in the Volume socket, not the Surface socket.

        Glass  -> Output.Surface
        Absorb -> Output.Volume

    Cycles integrates that volume. Legacy EEVEE ignores object volumes on
    refractive surfaces, so this object comes out near-colourless there -- a
    concrete example of what the rasteriser cannot fake.
    """
    graph = ShaderGraph.for_material(name)

    bsdf = graph.add("ShaderNodeBsdfPrincipled", label="Glass")
    set_inputs(
        bsdf,
        base_color=(1.0, 1.0, 1.0, 1.0),
        metallic=0.0,
        roughness=0.02,
        ior=ior,
        transmission=1.0,
    )
    volume = graph.add(
        "ShaderNodeVolumeAbsorption",
        label="Absorb",
        inputs={"color": (*absorption, 1.0), "density": density},
    )

    material, output = _finish(
        graph, bsdf, (*absorption, 1.0), refractive=True
    )
    graph.link(volume, "Volume", output, "Volume")
    graph.layout()

    # The base colour stays white on purpose: all of the tint comes from the
    # volume. In EEVEE that volume is ignored and this object renders
    # colourless, which is exactly the difference the demo is pointing at.
    return material


# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------

def checker_floor(name, scale=9.0):
    """A checkerboard floor.

    Not decoration: refraction is invisible against a flat background. Straight
    lines seen through glass bend and flip, which is the clearest read on
    whether transmission is actually being traced.
    """
    graph = ShaderGraph.for_material(name)

    coords = graph.add("ShaderNodeTexCoord", label="TexCoord")
    checker = graph.add(
        "ShaderNodeTexChecker",
        label="Checker",
        inputs={"scale": scale, "Color1": (0.82, 0.82, 0.84, 1.0),
                "Color2": (0.09, 0.10, 0.12, 1.0)},
    )
    bsdf = graph.add("ShaderNodeBsdfPrincipled", label="Floor")
    set_inputs(bsdf, metallic=0.0, roughness=0.32, ior=1.45)

    graph.link(coords, "Object", checker, "Vector")
    graph.link(checker, "Color", bsdf, "Base Color")

    material, _ = _finish(graph, bsdf, (0.5, 0.5, 0.5, 1.0))
    return material


def studio_world(name="CodeShadeWorld", strength=1.0):
    """A vertical gradient environment, so the demo needs no HDRI file.

    Graph shape:

        TexCoord.Generated -> SeparateXYZ.Z -> MapRange -> Ramp -> Background

    For a world shader the Generated coordinate is the view direction, so its Z
    component is "how far up am I looking". Remapping that -1..1 into a colour
    ramp gives ground, horizon and sky bands.

    The bright band at the horizon is deliberate. Glass and clear coat are
    mirrors at grazing angles, so what they actually show is the environment --
    with a flat grey world both read as dead grey plastic. This is the cheapest
    substitute for an HDRI and keeps the demo self-contained.
    """
    graph = ShaderGraph.for_world(name)

    coords = graph.add("ShaderNodeTexCoord", label="TexCoord")
    split = graph.add("ShaderNodeSeparateXYZ", label="SplitDirection")
    remap = graph.add("ShaderNodeMapRange", label="UpAxisTo01")
    set_inputs(remap, **{"From Min": -1.0, "From Max": 1.0, "To Min": 0.0, "To Max": 1.0})

    ramp = graph.add("ShaderNodeValToRGB", label="SkyRamp")
    elements = ramp.color_ramp.elements
    elements[0].position = 0.0
    elements[0].color = (0.035, 0.038, 0.048, 1.0)   # ground
    elements[1].position = 0.46
    elements[1].color = (0.20, 0.22, 0.26, 1.0)      # just below horizon
    horizon = elements.new(0.54)
    horizon.color = (0.62, 0.66, 0.74, 1.0)          # bright horizon band
    zenith = elements.new(1.0)
    zenith.color = (0.30, 0.38, 0.52, 1.0)           # sky

    background = graph.add(
        "ShaderNodeBackground", label="Background", inputs={"strength": strength}
    )
    output = graph.add("ShaderNodeOutputWorld", label="Output")

    graph.link(coords, "Generated", split, "Vector")
    graph.link(split, "Z", remap, "Value")
    graph.link(remap, "Result", ramp, "Fac")
    graph.link(ramp, "Color", background, "Color")
    graph.link(background, "Background", output, "Surface")
    graph.layout()
    return graph.world
