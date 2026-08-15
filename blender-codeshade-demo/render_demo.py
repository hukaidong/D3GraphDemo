"""Headless entry point: build the scene, configure an engine, render a PNG.

Run it through Blender, never through a bare python interpreter -- ``bpy`` only
exists inside the Blender process:

    blender --background --python render_demo.py -- --engine cycles --samples 128

Everything after the bare ``--`` is passed to this script; Blender itself eats
the arguments before it.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Blender puts the *current working directory* on sys.path, not the script's
# directory, so a script run from elsewhere cannot import its own siblings.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402  (must follow the sys.path fix-up)

import scene as scene_builder  # noqa: E402
from shadergraph import describe  # noqa: E402


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "renders")
DEFAULT_PROJECT = os.path.join(HERE, "example")


def parse_args(argv):
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser(
        prog="render_demo.py",
        description="Render plastic and glass primitives without a GUI.",
    )
    parser.add_argument("--engine", default="cycles",
                        choices=["cycles", "eevee", "both"],
                        help="cycles = path traced, eevee = rasterised (default: cycles)")
    parser.add_argument("--samples", type=int, default=128,
                        help="Cycles samples / EEVEE TAA samples (default: 128)")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="where the rendered PNGs go (default: renders/)")
    parser.add_argument("--project-dir", default=DEFAULT_PROJECT,
                        help="where the .blend project goes (default: example/)")
    parser.add_argument("--prefix", default="plastic_glass")
    parser.add_argument("--no-project", dest="project", action="store_false",
                        help="render only; do not write a .blend project")
    parser.add_argument("--dump-graphs", action="store_true",
                        help="print every material's node tree as text")
    parser.add_argument("--threads", type=int, default=0,
                        help="CPU threads for Cycles (0 = autodetect)")
    parser.add_argument("--exposure", type=float, default=-0.35,
                        help="view-transform exposure in stops (default: -0.35)")
    parser.add_argument("--no-denoise", dest="denoise", action="store_false",
                        help="skip denoising even if this build supports it")
    return parser.parse_args(argv)


def enable_cycles():
    """Make sure the Cycles engine is registered.

    Cycles ships as an add-on. A desktop install has it enabled in user
    preferences, but distro packages and fresh containers often do not -- and
    with ``--factory-startup`` it is never on. Without this, setting
    ``render.engine = 'CYCLES'`` raises, which is a confusing first failure on
    a headless box.
    """
    import addon_utils

    if not any(m.__name__ == "cycles" for m in addon_utils.modules()):
        return False
    addon_utils.enable("cycles", default_set=True, persistent=True)
    return True


def configure_denoising(cycles, enabled=True):
    """Turn on denoising only if this Blender was built with a denoiser.

    Distro packages are frequently compiled without OpenImageDenoise. The
    ``denoiser`` enum is populated at runtime from what was compiled in, so an
    empty enum means there is nothing to select -- and assigning a denoiser that
    is not there fails at render time, not at assignment, which makes it look
    like the render itself is broken.
    """
    available = [item.identifier
                 for item in cycles.bl_rna.properties["denoiser"].enum_items]
    if not enabled or not available:
        cycles.use_denoising = False
        if enabled and not available:
            print("[codeshade] no denoiser in this build; raise --samples to "
                  "compensate (glass and caustics are the noisy parts)")
        return None

    for preferred in ("OPENIMAGEDENOISE", "OPTIX"):
        if preferred in available:
            cycles.denoiser = preferred
            break
    cycles.use_denoising = True
    print(f"[codeshade] denoising with {cycles.denoiser}")
    return cycles.denoiser


def configure_cycles(scene, samples, threads, denoise=True):
    if not enable_cycles():
        raise RuntimeError("Cycles add-on is not available in this Blender build")
    scene.render.engine = "CYCLES"

    cycles = scene.cycles
    cycles.device = "CPU"
    cycles.samples = samples
    cycles.use_adaptive_sampling = True
    cycles.adaptive_threshold = 0.01

    # Transmission depth is the setting that matters for glass. Each surface a
    # ray passes through costs one transmission bounce, and a hollow-looking
    # object needs several (front face, back face, and whatever is behind it).
    # Too low and glass renders as opaque black.
    cycles.max_bounces = 16
    cycles.transmission_bounces = 16
    cycles.transparent_max_bounces = 16
    cycles.glossy_bounces = 6
    cycles.diffuse_bounces = 4

    # Caustics -- light focused through glass onto the floor. Cheap to leave on
    # here, and their absence is a giveaway that glass is being faked.
    cycles.caustics_reflective = True
    cycles.caustics_refractive = True
    cycles.blur_glossy = 0.5

    configure_denoising(cycles, enabled=denoise)

    if threads:
        scene.render.threads_mode = "FIXED"
        scene.render.threads = threads


def configure_eevee(scene, samples):
    """Configure whichever EEVEE this Blender ships.

    4.2 replaced legacy EEVEE with "EEVEE Next", which has real screen-space
    ray tracing and a different property set, so both spellings are handled.
    """
    engines = {item.identifier
               for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"

    eevee = scene.eevee
    if hasattr(eevee, "taa_render_samples"):
        eevee.taa_render_samples = samples

    if hasattr(eevee, "use_raytracing"):
        # EEVEE Next (4.2+): screen-space ray tracing, opt-in.
        eevee.use_raytracing = True
    else:
        # Legacy EEVEE (<= 4.1): screen-space reflections, and refraction is a
        # sub-option of them. Without use_ssr_refraction every glass object
        # falls back to showing the world texture instead of the scene.
        if hasattr(eevee, "use_ssr"):
            eevee.use_ssr = True
            eevee.use_ssr_refraction = True
            eevee.use_ssr_halfres = False
        if hasattr(eevee, "use_gtao"):
            eevee.use_gtao = True
            eevee.gtao_distance = 0.6

    if hasattr(eevee, "shadow_cube_size"):
        eevee.shadow_cube_size = "2048"
    if hasattr(eevee, "shadow_cascade_size"):
        eevee.shadow_cascade_size = "2048"
    if hasattr(eevee, "use_soft_shadows"):
        eevee.use_soft_shadows = True


def configure_color_management(scene, exposure=-0.35):
    """Pick a filmic view transform and a slightly contrastier look.

    These enums come from the OCIO config, so they cannot be introspected
    reliably -- assigning an unsupported name raises, hence the try/except
    ladder. Blender 4.x defaults to AgX; 2.8-3.x only has Filmic.
    """
    view = scene.view_settings
    for transform in ("AgX", "Filmic", "Standard"):
        try:
            view.view_transform = transform
            break
        except TypeError:
            continue

    # Without a look, AgX desaturates saturated plastics noticeably.
    for look in (f"{view.view_transform} - Punchy", "Punchy", "Medium High Contrast", "None"):
        try:
            view.look = look
            break
        except TypeError:
            continue

    view.exposure = exposure
    print(f"[codeshade] view transform={view.view_transform} look={view.look}")


def configure_output(scene, width, height):
    render = scene.render
    render.resolution_x = width
    render.resolution_y = height
    render.resolution_percentage = 100
    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGBA"
    render.image_settings.compression = 15
    render.film_transparent = False


def render_to(scene, filepath):
    scene.render.filepath = filepath
    started = time.time()
    bpy.ops.render.render(write_still=True)
    elapsed = time.time() - started
    print(f"[codeshade] wrote {filepath}  ({elapsed:.1f}s, engine={scene.render.engine})")
    return elapsed


def save_project(image_paths, project_dir, prefix):
    """Write the .blend once the renders are done, with them packed inside.

    This runs *after* rendering, and has to. Blender's output lives in a
    special "Render Result" image that is a temporary buffer and is never
    written into a .blend, so a project saved before the render contains the
    materials and the lights but no picture. Loading back the PNGs that were
    just written and packing them makes the project self-contained -- open it
    anywhere, with no ``renders/`` folder beside it, and both engine renders
    are in the Image editor next to the node graphs that produced them.

    ``use_fake_user`` is the other half: nothing in the scene references these
    images, and Blender drops unreferenced datablocks on save unless something
    claims them, so without it the pack silently achieves nothing.
    """
    os.makedirs(project_dir, exist_ok=True)

    for path in image_paths:
        image = bpy.data.images.load(path, check_existing=True)
        image.name = f"render_{os.path.splitext(os.path.basename(path))[0]}"
        image.pack()
        image.use_fake_user = True

    blend_path = os.path.join(project_dir, f"{prefix}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path, compress=True)
    size_mb = os.path.getsize(blend_path) / (1024 * 1024)
    print(f"[codeshade] wrote {blend_path}  ({size_mb:.1f} MB, renders packed in)")
    return blend_path


def dump_graphs():
    print("\n" + "=" * 72)
    print("Material node trees (the same data the shader editor would show)")
    print("=" * 72)
    for material in sorted(bpy.data.materials, key=lambda m: m.name):
        if not material.use_nodes:
            continue
        print(f"\n--- {material.name} " + "-" * (66 - len(material.name)))
        print(describe(material.node_tree))
    print()


def main():
    args = parse_args(sys.argv)
    os.makedirs(args.out, exist_ok=True)

    print("[codeshade] building scene")
    scene = scene_builder.build()
    configure_output(scene, args.width, args.height)
    configure_color_management(scene, exposure=args.exposure)

    if args.dump_graphs:
        dump_graphs()

    targets = ["cycles", "eevee"] if args.engine == "both" else [args.engine]
    rendered = []
    for engine in targets:
        if engine == "cycles":
            configure_cycles(scene, args.samples, args.threads, denoise=args.denoise)
        else:
            configure_eevee(scene, args.samples)
        image_path = os.path.join(args.out, f"{args.prefix}_{engine}.png")
        render_to(scene, image_path)
        rendered.append(image_path)

    if args.project:
        save_project(rendered, args.project_dir, args.prefix)


if __name__ == "__main__":
    main()
