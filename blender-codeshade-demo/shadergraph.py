"""Thin helpers for authoring Blender shader node trees from Python.

The Blender shader editor is a *view* onto a node tree. Everything you do by
dragging in that window -- creating a node, setting a value, dropping a link --
is a mutation of ``material.node_tree``. This module wraps those mutations in a
few functions so the demo scripts read like a description of the graph instead
of a pile of ``nodes.new`` / ``links.new`` calls.

Two things the GUI does for you that Python does not:

1. **Placement.** ``nodes.new()`` puts every node at (0, 0), so a graph built in
   a script opens as a stack of overlapping boxes. ``auto_layout`` below fixes
   that by laying nodes out in columns by distance from the output node.
2. **Socket naming.** In the GUI you drag to a socket you can see. In Python you
   address it by name, and those names change between Blender versions
   (``"Transmission"`` became ``"Transmission Weight"`` in 4.0). ``set_inputs``
   resolves aliases so the same script runs on 3.x and 4.x.

Neither affects the rendered image -- only how the graph looks when a human
opens the .blend.
"""

from __future__ import annotations

import bpy


# Canonical key -> socket names to try, newest Blender naming first.
# Blender 4.0 renamed several Principled BSDF sockets; keeping both spellings
# means one script covers 3.x and 4.x.
SOCKET_ALIASES = {
    "base_color": ("Base Color",),
    "metallic": ("Metallic",),
    "roughness": ("Roughness",),
    "ior": ("IOR",),
    "alpha": ("Alpha",),
    "normal": ("Normal",),
    "transmission": ("Transmission Weight", "Transmission"),
    "coat_weight": ("Coat Weight", "Clearcoat"),
    "coat_roughness": ("Coat Roughness", "Clearcoat Roughness"),
    "specular": ("Specular IOR Level", "Specular"),
    "sheen": ("Sheen Weight", "Sheen"),
    "emission_color": ("Emission Color", "Emission"),
    "emission_strength": ("Emission Strength",),
    "color": ("Color",),
    "density": ("Density",),
    "scale": ("Scale",),
    "detail": ("Detail",),
    "distortion": ("Distortion",),
    "strength": ("Strength",),
    "height": ("Height",),
    "fac": ("Fac",),
}


class MissingSocket(KeyError):
    """Raised when no alias for a requested socket exists on a node."""


def find_input(node, key):
    """Return the input socket for ``key``, trying every known alias.

    ``key`` may also be a literal socket name that is not in SOCKET_ALIASES.
    """
    for name in SOCKET_ALIASES.get(key, (key,)):
        socket = node.inputs.get(name)
        if socket is not None:
            return socket
    raise MissingSocket(
        f"{node.bl_idname} has no socket for {key!r}; "
        f"available: {[s.name for s in node.inputs]}"
    )


def set_inputs(node, **values):
    """Set default values on a node's input sockets by canonical key.

    ``set_inputs(bsdf, base_color=(1, 0, 0, 1), roughness=0.3)`` is the scripted
    equivalent of typing those numbers into the node's widgets.
    """
    for key, value in values.items():
        find_input(node, key).default_value = value
    return node


class ShaderGraph:
    """A small builder around one material's (or world's) node tree."""

    def __init__(self, tree):
        self.tree = tree
        self.nodes = tree.nodes
        self.links = tree.links

    @classmethod
    def for_material(cls, name, clear=True):
        """Create (or reset) a material and return a builder for its tree."""
        material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        material.use_nodes = True
        graph = cls(material.node_tree)
        if clear:
            graph.nodes.clear()
        graph.material = material
        return graph

    @classmethod
    def for_world(cls, name, clear=True):
        world = bpy.data.worlds.get(name) or bpy.data.worlds.new(name)
        world.use_nodes = True
        graph = cls(world.node_tree)
        if clear:
            graph.nodes.clear()
        graph.world = world
        return graph

    def add(self, bl_idname, label=None, inputs=None, **properties):
        """Add a node.

        ``bl_idname`` is the type, e.g. ``"ShaderNodeBsdfPrincipled"``.
        ``properties`` sets node-level attributes (``noise_dimensions``,
        ``operation``, ...); ``inputs`` sets socket default values.
        """
        node = self.nodes.new(bl_idname)
        if label:
            node.label = label
            node.name = label
        for key, value in properties.items():
            setattr(node, key, value)
        if inputs:
            set_inputs(node, **inputs)
        return node

    def link(self, from_node, from_socket, to_node, to_socket):
        """Wire one socket to another. Sockets are named, or indexed by int."""
        source = from_node.outputs[from_socket]
        target = (
            to_node.inputs[to_socket]
            if isinstance(to_socket, int)
            else find_input(to_node, to_socket)
        )
        return self.links.new(source, target)

    def layout(self):
        auto_layout(self.tree)
        return self


def auto_layout(tree, x_gap=280, y_gap=300):
    """Arrange nodes in columns by their distance from the output node.

    Purely cosmetic -- it exists so the saved .blend opens with a readable
    graph instead of every node stacked at the origin.
    """
    outputs = [n for n in tree.nodes if n.type in {"OUTPUT_MATERIAL", "OUTPUT_WORLD"}]
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
        column.sort(key=lambda n: n.name)
        offset = (len(column) - 1) * y_gap / 2.0
        for row, node in enumerate(column):
            node.location = (-level * x_gap, offset - row * y_gap)


_PRISTINE_TREE = "__codeshade_pristine__"


def _factory_defaults(bl_idname):
    """Socket defaults of a freshly created node of this type.

    Used to filter the dump down to what the script actually changed. A
    Principled BSDF has ~30 inputs and printing all of them buries the four
    that matter.
    """
    tree = bpy.data.node_groups.get(_PRISTINE_TREE)
    if tree is None:
        tree = bpy.data.node_groups.new(_PRISTINE_TREE, "ShaderNodeTree")
        tree.use_fake_user = False

    try:
        node = tree.nodes.new(bl_idname)
    except RuntimeError:
        return {}

    defaults = {}
    for socket in node.inputs:
        value = getattr(socket, "default_value", None)
        if value is not None:
            defaults[socket.name] = tuple(value) if hasattr(value, "__len__") else value
    tree.nodes.remove(node)
    return defaults


def describe(tree, indent="  ", show_defaults=False):
    """Return a text rendering of a node tree, for printing to a terminal.

    Useful when there is no GUI to look at: it shows the same information the
    shader editor would, as nodes plus the links between them.
    """
    lines = []
    for node in sorted(tree.nodes, key=lambda n: n.name):
        lines.append(f"{node.name}  [{node.bl_idname}]  at {tuple(round(v) for v in node.location)}")
        defaults = {} if show_defaults else _factory_defaults(node.bl_idname)
        for socket in node.inputs:
            if socket.links:
                continue
            value = getattr(socket, "default_value", None)
            if value is None:
                continue
            raw = tuple(value) if hasattr(value, "__len__") else value
            if not show_defaults and socket.name in defaults and raw == defaults[socket.name]:
                continue
            if hasattr(value, "__len__"):
                shown = tuple(round(v, 3) for v in value)
            else:
                shown = round(value, 3) if isinstance(value, float) else value
            lines.append(f"{indent}{socket.name} = {shown}")
    lines.append("links:")
    for link in tree.links:
        lines.append(
            f"{indent}{link.from_node.name}.{link.from_socket.name}"
            f" -> {link.to_node.name}.{link.to_socket.name}"
        )
    return "\n".join(lines)
