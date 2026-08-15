"""Headless entry point. Build a scene, configure Cycles, write a PNG.

    blender --background --factory-startup --python render_demo.py -- --shot all

Everything after the bare ``--`` reaches this script; Blender eats the rest.
The engine plumbing here is deliberately the same shape as the sibling
``blender-codeshade-demo`` -- the interesting differences in this demo are all
in ``meshlib.py`` and ``assets.py``.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Blender puts the *current working directory* on sys.path, not the script's
# directory, so a script run from elsewhere cannot import its siblings.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402  (must follow the sys.path fix-up)

import assets  # noqa: E402
import detail as detail_levels  # noqa: E402
import scene as scene_builder  # noqa: E402
import toolbox  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "renders")
DEFAULT_PROJECT = os.path.join(HERE, "example")
SHOTS = ("ladder", "hero", "toolbox")


def parse_args(argv):
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(
        prog="render_demo.py",
        description="Model a lighthouse in Python and render it, with no GUI.",
    )
    parser.add_argument("--shot", default="all", choices=(*SHOTS, "all"),
                        help="ladder = detail comparison, hero = full scene, "
                             "toolbox = the modelling operations (default: all)")
    parser.add_argument("--detail", default="high",
                        choices=sorted(detail_levels.LEVELS),
                        help="detail level for the hero shot (default: high)")
    parser.add_argument("--samples", type=int, default=160)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="where the rendered PNGs go (default: renders/)")
    parser.add_argument("--project-dir", default=DEFAULT_PROJECT,
                        help="where the .blend projects go (default: example/)")
    parser.add_argument("--no-project", dest="project", action="store_false",
                        help="render only; do not write a .blend project")
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--exposure", type=float, default=0.0)
    parser.add_argument("--stats", action="store_true",
                        help="print the topology table and exit without rendering")
    parser.add_argument("--dump-scatter", action="store_true",
                        help="print the scatter node group as text")
    parser.add_argument("--no-denoise", dest="denoise", action="store_false")
    return parser.parse_args(argv)


def enable_cycles():
    """Cycles ships as an add-on and ``--factory-startup`` leaves it disabled."""
    import addon_utils

    if not any(module.__name__ == "cycles" for module in addon_utils.modules()):
        return False
    addon_utils.enable("cycles", default_set=True, persistent=True)
    return True


def configure_denoising(cycles, enabled=True):
    """Only enable a denoiser that was actually compiled into this build.

    Distro packages are often built without OpenImageDenoise. Assigning it then
    succeeds and fails later, at render time, which reads as a broken render.
    """
    available = [item.identifier
                 for item in cycles.bl_rna.properties["denoiser"].enum_items]
    if not enabled or not available:
        cycles.use_denoising = False
        if enabled and not available:
            print("[procmesh] no denoiser in this build; raise --samples instead")
        return None
    for preferred in ("OPENIMAGEDENOISE", "OPTIX"):
        if preferred in available:
            cycles.denoiser = preferred
            break
    cycles.use_denoising = True
    return cycles.denoiser


def configure_cycles(scene, samples, threads, denoise=True):
    if not enable_cycles():
        raise RuntimeError("Cycles is not available in this Blender build")
    scene.render.engine = "CYCLES"

    cycles = scene.cycles
    cycles.device = "CPU"
    cycles.samples = samples
    cycles.use_adaptive_sampling = True
    cycles.adaptive_threshold = 0.012
    cycles.max_bounces = 8
    cycles.transmission_bounces = 8
    cycles.transparent_max_bounces = 8
    cycles.glossy_bounces = 4
    cycles.diffuse_bounces = 3
    cycles.blur_glossy = 1.0
    configure_denoising(cycles, enabled=denoise)

    if threads:
        scene.render.threads_mode = "FIXED"
        scene.render.threads = threads


def configure_output(scene, width, height, exposure):
    render = scene.render
    render.resolution_x = width
    render.resolution_y = height
    render.resolution_percentage = 100
    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGBA"
    render.image_settings.compression = 15

    view = scene.view_settings
    for transform in ("AgX", "Filmic", "Standard"):
        try:
            view.view_transform = transform
            break
        except TypeError:
            continue
    for look in (f"{view.view_transform} - Medium High Contrast",
                 "Medium High Contrast", "None"):
        try:
            view.look = look
            break
        except TypeError:
            continue
    view.exposure = exposure


def render_to(scene, filepath):
    scene.render.filepath = filepath
    started = time.time()
    bpy.ops.render.render(write_still=True)
    elapsed = time.time() - started
    print(f"[procmesh] wrote {filepath}  ({elapsed:.1f}s)")
    return elapsed


def save_project(shot, image_path, project_dir):
    """Write a .blend for this shot with the finished render packed inside it.

    This runs *after* the render, and has to. Blender's render output lives in
    a special "Render Result" image that is a temporary buffer -- it is never
    written into a .blend, so a project saved before or during the render
    contains the scene but no picture. Loading back the PNG that was just
    written and packing it is what makes the project self-contained: open it on
    another machine, with no ``renders/`` folder next to it, and the finished
    frame is still there in the Image editor beside the scene that produced it.

    ``use_fake_user`` is the other half of that. Nothing in the scene
    references this image, and Blender drops unreferenced datablocks on save
    unless something claims them -- so without it the pack silently achieves
    nothing.
    """
    os.makedirs(project_dir, exist_ok=True)

    image = bpy.data.images.load(image_path, check_existing=True)
    image.name = f"render_{shot}"
    image.pack()
    image.use_fake_user = True

    blend_path = os.path.join(project_dir, f"{shot}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path, compress=True)
    size_mb = os.path.getsize(blend_path) / (1024 * 1024)
    print(f"[procmesh] wrote {blend_path}  ({size_mb:.1f} MB, render packed in)")
    return blend_path


def print_stats():
    """The topology table: one model, three densities, measured not guessed.

    Counts come from the evaluated dependency graph, so modifiers -- the
    scatter in particular -- are included.
    """
    rows = []
    for name in ("low", "mid", "high"):
        level = detail_levels.get(name)
        scene_builder.reset()
        building = assets.lighthouse(level)
        verts, tris = scene_builder.totals(building)
        rows.append((name, len(building), verts, tris))

    width = 62
    print("\n" + "=" * width)
    print("One definition, three densities (lighthouse only, no islet)")
    print("=" * width)
    print(f"{'level':<8}{'objects':>9}{'vertices':>12}{'triangles':>12}{'x low':>10}")
    base = rows[0][3]
    for name, objects, verts, tris in rows:
        print(f"{name:<8}{objects:>9}{verts:>12,}{tris:>12,}{tris / base:>9.1f}x")
    print()


def main():
    args = parse_args(sys.argv)
    os.makedirs(args.out, exist_ok=True)

    if args.stats:
        print_stats()
        return

    if args.dump_scatter:
        import geonodes
        print(geonodes.describe(geonodes.scatter_tree()))
        return

    shots = SHOTS if args.shot == "all" else (args.shot,)
    for shot in shots:
        print(f"[procmesh] building {shot}")
        if shot == "ladder":
            scene, _ = scene_builder.ladder(
                [detail_levels.LOW, detail_levels.MID, detail_levels.HIGH])
        elif shot == "hero":
            scene, objects = scene_builder.hero(detail_levels.get(args.detail))
            verts, tris = scene_builder.totals(objects)
            print(f"[procmesh] hero geometry: {verts:,} verts, {tris:,} tris")
        else:
            scene = toolbox.build()

        configure_output(scene, args.width, args.height, args.exposure)
        configure_cycles(scene, args.samples, args.threads, denoise=args.denoise)

        image_path = os.path.join(args.out, f"{shot}.png")
        render_to(scene, image_path)

        if args.project:
            save_project(shot, image_path, args.project_dir)


if __name__ == "__main__":
    main()
