"""Materials for the demo.

Deliberately thin. The sibling ``blender-codeshade-demo`` is the one about
shader node graphs; here the shading exists to let you read the *geometry*, so
almost everything is a plain Principled BSDF with a colour and a roughness.

Two exceptions earn their nodes: the sea, which needs a bump to stop reading as
a mirror, and the lamp, which is emissive so the lantern actually glows.
"""

from __future__ import annotations

import bpy


def _principled(name, color, roughness=0.6, metallic=0.0, **extra):
    material = bpy.data.materials.get(name)
    if material is not None:
        return material

    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    for socket, value in extra.items():
        bsdf.inputs[socket].default_value = value
    return material


def stone():
    return _principled("M_Stone", (0.74, 0.72, 0.66), roughness=0.74)


def trim():
    """The red of the lantern housing and the door."""
    return _principled("M_Trim", (0.48, 0.07, 0.06), roughness=0.42)


def metal():
    return _principled("M_Metal", (0.09, 0.10, 0.11), roughness=0.38, metallic=1.0)


def glass():
    return _principled(
        "M_Glass", (0.85, 0.90, 0.92), roughness=0.03,
        **{"Transmission Weight": 1.0, "IOR": 1.45},
    )


def lamp():
    material = bpy.data.materials.get("M_Lamp")
    if material is not None:
        return material
    material = bpy.data.materials.new("M_Lamp")
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    emission = tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (1.0, 0.86, 0.55, 1.0)
    emission.inputs["Strength"].default_value = 14.0
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def rock():
    return _principled("M_Rock", (0.105, 0.093, 0.078), roughness=0.88)


def grass():
    return _principled("M_Grass", (0.115, 0.205, 0.075), roughness=0.85)


def sea():
    """Glossy water with a noise bump.

    A perfectly flat plane with roughness 0 mirrors the sky and reads as glass,
    not water. The bump breaks the reflection up; it is the only place in this
    demo where surface detail is faked rather than modelled, and it is faked
    because open water has no silhouette to get wrong.
    """
    material = bpy.data.materials.get("M_Sea")
    if material is not None:
        return material

    material = bpy.data.materials.new("M_Sea")
    material.use_nodes = True
    tree = material.node_tree
    bsdf = tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.015, 0.055, 0.085, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.06
    bsdf.inputs["IOR"].default_value = 1.33

    noise = tree.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.35
    noise.inputs["Detail"].default_value = 8.0
    noise.inputs["Roughness"].default_value = 0.55

    stretch = tree.nodes.new("ShaderNodeMapping")
    # The sea plane is 400 units across, so its object coordinates span +/-200
    # and a noise scale of 6.5 would give 15 cm ripples -- invisible at this
    # distance and just a sheen. 0.35 gives swells a few metres across.
    stretch.inputs["Scale"].default_value = (1.0, 3.2, 1.0)
    coords = tree.nodes.new("ShaderNodeTexCoord")

    bump = tree.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.30
    bump.inputs["Distance"].default_value = 0.35

    tree.links.new(coords.outputs["Object"], stretch.inputs["Vector"])
    tree.links.new(stretch.outputs["Vector"], noise.inputs["Vector"])
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return material


def clay():
    """One neutral material for the whole operation sheet.

    Studio clay on purpose: colour would compete with the only thing those
    tiles are there to show, which is shape.
    """
    return _principled("M_Clay", (0.62, 0.60, 0.58), roughness=0.52)


def label():
    """Flat dark grey for the 3-D text used to caption the comparison renders."""
    return _principled("M_Label", (0.02, 0.02, 0.025), roughness=0.9)


def label_light():
    """The same captions, for use against the dark operation sheet."""
    return _principled("M_LabelLight", (0.80, 0.81, 0.83), roughness=0.9)


def backdrop():
    return _principled("M_Backdrop", (0.52, 0.55, 0.58), roughness=0.95)


def ground():
    """Dark plane under the detail ladder, so the pale stone has something to
    read against and the captions above the towers stay legible."""
    return _principled("M_Ground", (0.085, 0.095, 0.110), roughness=0.94)


def sheet():
    """Dark backing for the operation sheet.

    A light backdrop behind light clay leaves the silhouettes with nothing to
    read against -- which is the whole job of that render.
    """
    return _principled("M_Sheet", (0.055, 0.060, 0.070), roughness=0.96)


def sky(strength=1.0, horizon=(0.55, 0.66, 0.80), zenith=(0.16, 0.31, 0.58)):
    """A gradient world, so the demo downloads no HDRI at run time."""
    world = bpy.data.worlds.get("W_Sky") or bpy.data.worlds.new("W_Sky")
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()

    coords = tree.nodes.new("ShaderNodeTexCoord")
    separate = tree.nodes.new("ShaderNodeSeparateXYZ")
    ramp = tree.nodes.new("ShaderNodeMapRange")
    ramp.inputs["From Min"].default_value = -0.25
    ramp.inputs["From Max"].default_value = 0.55

    mix = tree.nodes.new("ShaderNodeMixRGB")
    mix.inputs["Color1"].default_value = (*horizon, 1.0)
    mix.inputs["Color2"].default_value = (*zenith, 1.0)

    background = tree.nodes.new("ShaderNodeBackground")
    background.inputs["Strength"].default_value = strength
    output = tree.nodes.new("ShaderNodeOutputWorld")

    tree.links.new(coords.outputs["Generated"], separate.inputs["Vector"])
    tree.links.new(separate.outputs["Z"], ramp.inputs["Value"])
    tree.links.new(ramp.outputs["Result"], mix.inputs["Fac"])
    tree.links.new(mix.outputs["Color"], background.inputs["Color"])
    tree.links.new(background.outputs["Background"], output.inputs["Surface"])
    return world
