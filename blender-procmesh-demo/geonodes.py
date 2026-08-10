"""A Geometry Nodes tree, built from Python.

Geometry Nodes is the other procedural modelling system in Blender, and the one
people assume needs the GUI, because the GUI is where the node editor lives.
It does not. A node tree is ``bpy.data.node_groups`` -- nodes in a collection,
links in another collection -- exactly like the shader trees in the sibling
demo, and a modifier of type ``NODES`` points an object at one.

This module builds one small tree: scatter grass over the islet, but only on
ground that faces roughly upward and sits above the waterline. Written out, the
graph is

    Group Input ---> Distribute Points on Faces ---> Instance on Points --->
                          ^          ^                     ^   ^
        (selection) ------+          |          Object Info|   |Random Value
                                     +-- Density           (tuft)  (scale)

    ---> Realize Instances ---> Group Output

and the selection is the interesting part, because it is a *field*: an
expression evaluated per face rather than a value. ``normal . Z > 0.62`` and
``position.z > waterline``, combined with a boolean AND. Fields are why
Geometry Nodes is worth reaching for over a Python loop -- the same graph
re-evaluates when the islet changes, at any detail level, with no rebuild.

One version note: Blender 4.0 moved group interface sockets from
``tree.inputs`` / ``tree.outputs`` to ``tree.interface.new_socket(...)``. Both
spellings are handled below, because a script that only knows one of them fails
on half the Blender versions in the wild.
"""

from __future__ import annotations

import bpy


def _new_socket(tree, name, in_out, socket_type="NodeSocketGeometry"):
    """Add a group input/output socket, on 4.0+ and on 3.x."""
    if hasattr(tree, "interface"):
        return tree.interface.new_socket(name, in_out=in_out, socket_type=socket_type)
    collection = tree.inputs if in_out == "INPUT" else tree.outputs
    return collection.new(socket_type, name)


def scatter_tree(name="GN_Scatter", instance=None, density=1.2, seed=7,
                 min_slope=0.62, waterline=0.35, scale_range=(0.55, 1.35)):
    """Build (or rebuild) the scatter node group and return it."""
    existing = bpy.data.node_groups.get(name)
    if existing is not None:
        bpy.data.node_groups.remove(existing)

    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _new_socket(tree, "Geometry", "INPUT")
    _new_socket(tree, "Geometry", "OUTPUT")

    nodes, links = tree.nodes, tree.links
    group_in = nodes.new("NodeGroupInput")
    group_out = nodes.new("NodeGroupOutput")

    distribute = nodes.new("GeometryNodeDistributePointsOnFaces")
    distribute.distribute_method = "POISSON"
    distribute.inputs["Density Max"].default_value = density
    distribute.inputs["Distance Min"].default_value = 0.22
    distribute.inputs["Seed"].default_value = seed

    # --- the selection field ------------------------------------------------
    normal = nodes.new("GeometryNodeInputNormal")
    upward = nodes.new("ShaderNodeVectorMath")
    upward.operation = "DOT_PRODUCT"
    upward.inputs[1].default_value = (0.0, 0.0, 1.0)

    flat_enough = nodes.new("ShaderNodeMath")
    flat_enough.operation = "GREATER_THAN"
    flat_enough.inputs[1].default_value = min_slope

    position = nodes.new("GeometryNodeInputPosition")
    split = nodes.new("ShaderNodeSeparateXYZ")
    above_water = nodes.new("ShaderNodeMath")
    above_water.operation = "GREATER_THAN"
    above_water.inputs[1].default_value = waterline

    both = nodes.new("FunctionNodeBooleanMath")
    both.operation = "AND"

    links.new(normal.outputs["Normal"], upward.inputs[0])
    links.new(upward.outputs["Value"], flat_enough.inputs[0])
    links.new(position.outputs["Position"], split.inputs["Vector"])
    links.new(split.outputs["Z"], above_water.inputs[0])
    links.new(flat_enough.outputs["Value"], both.inputs[0])
    links.new(above_water.outputs["Value"], both.inputs[1])
    links.new(both.outputs["Boolean"], distribute.inputs["Selection"])

    # --- instancing ---------------------------------------------------------
    instance_on = nodes.new("GeometryNodeInstanceOnPoints")
    source = nodes.new("GeometryNodeObjectInfo")
    if instance is not None:
        source.inputs["Object"].default_value = instance

    random_scale = nodes.new("FunctionNodeRandomValue")
    random_scale.data_type = "FLOAT"
    random_scale.inputs[2].default_value = scale_range[0]
    random_scale.inputs[3].default_value = scale_range[1]
    random_scale.inputs["Seed"].default_value = seed + 1

    realize = nodes.new("GeometryNodeRealizeInstances")

    # Join the scattered instances back onto the surface they were scattered
    # over. Without this the group outputs the instances *alone*, and since a
    # Geometry Nodes modifier replaces the object's geometry with whatever the
    # group returns, the island silently vanishes and leaves its grass floating
    # in mid-air. The node graph looks completely correct while doing it.
    join = nodes.new("GeometryNodeJoinGeometry")

    links.new(group_in.outputs[0], distribute.inputs["Mesh"])
    links.new(distribute.outputs["Points"], instance_on.inputs["Points"])
    links.new(distribute.outputs["Rotation"], instance_on.inputs["Rotation"])
    links.new(source.outputs["Geometry"], instance_on.inputs["Instance"])
    links.new(random_scale.outputs[1], instance_on.inputs["Scale"])
    links.new(instance_on.outputs["Instances"], realize.inputs["Geometry"])
    links.new(realize.outputs["Geometry"], join.inputs["Geometry"])
    links.new(group_in.outputs[0], join.inputs["Geometry"])
    links.new(join.outputs["Geometry"], group_out.inputs[0])

    _layout(tree)
    return tree


def apply_scatter(obj, instance, density, seed=7, name="GN_Scatter"):
    """Attach a scatter modifier to ``obj``. Returns the modifier, or None."""
    if density <= 0.0:
        return None
    tree = scatter_tree(name=name, instance=instance, density=density, seed=seed)
    modifier = obj.modifiers.new("Scatter", "NODES")
    modifier.node_group = tree
    return modifier


def _layout(tree, x_gap=260, y_gap=190):
    """Columns by distance from the output, so a saved .blend opens readable.

    Same reason as the shader demo: ``nodes.new()`` stacks everything at the
    origin, which is only a problem for the human who opens the file later.
    """
    outputs = [node for node in tree.nodes if node.bl_idname == "NodeGroupOutput"]
    depth = {}
    stack = [(node, 0) for node in outputs]
    while stack:
        node, level = stack.pop()
        if depth.get(node, -1) >= level:
            continue
        depth[node] = level
        for socket in node.inputs:
            for link in socket.links:
                stack.append((link.from_node, level + 1))

    for node in tree.nodes:
        depth.setdefault(node, 0)

    columns = {}
    for node, level in depth.items():
        columns.setdefault(level, []).append(node)
    for level, column in columns.items():
        column.sort(key=lambda node: node.name)
        offset = (len(column) - 1) * y_gap / 2.0
        for row, node in enumerate(column):
            node.location = (-level * x_gap, offset - row * y_gap)


def describe(tree, indent="  "):
    """Text rendering of a node tree, for terminals with no node editor."""
    lines = []
    for node in sorted(tree.nodes, key=lambda n: n.name):
        location = tuple(round(value) for value in node.location)
        lines.append(f"{node.name}  [{node.bl_idname}]  at {location}")
        for key in ("operation", "data_type", "distribute_method"):
            if hasattr(node, key):
                lines.append(f"{indent}{key} = {getattr(node, key)}")
        for socket in node.inputs:
            if socket.links or not hasattr(socket, "default_value"):
                continue
            value = socket.default_value
            if hasattr(value, "__len__") and not isinstance(value, str):
                value = tuple(round(component, 3) for component in value)
            elif isinstance(value, float):
                value = round(value, 3)
            lines.append(f"{indent}{socket.name} = {value}")
    lines.append("links:")
    for link in tree.links:
        lines.append(f"{indent}{link.from_node.name}.{link.from_socket.name}"
                     f" -> {link.to_node.name}.{link.to_socket.name}")
    return "\n".join(lines)
