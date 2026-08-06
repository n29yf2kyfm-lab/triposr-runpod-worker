"""Blender as a rendering tool, held at arm's length.

preview.py draws the model with flat shading and a painter's sort. It is
honest, it is fast, it caught four real geometry bugs — and it looks like a
diagram, because that is what it is. Cycles gives the thing a client sees:
real materials, a real sun, soft shadows, ambient occlusion in the reveals,
glass that behaves like glass.

TWO RULES THIS MODULE EXISTS TO ENFORCE.

1. BLENDER RUNS IN A SEPARATE PROCESS. Never `import bpy` from the worker.
   Blender is GPL; importing it into our Python would link our code to it and
   raise a question about the whole codebase. Calling it as a tool over a
   process boundary does not — a program that runs another program is not a
   derivative of it. Everything here goes through subprocess, and the only
   thing crossing the boundary is a .glb going in and a .png coming out.

2. THE GEOMETRY IS NOT NEGOTIABLE. Blender is handed the exact GLB the job
   exported and told to light it. It does not rebuild, simplify, decimate or
   "clean up" anything. This is the same rule that made the Gemini photoreal
   pass rejectable: the measured model is the drawing, and a renderer that
   improves the geometry has destroyed the product.

WHAT IT COSTS, HONESTLY. The bpy wheel is ~370MB and pins numpy<2, which
conflicts with opencv and imagecodecs in this image. On a worker it belongs
in its own virtualenv or its own container stage, not mixed into the one
that reads GeoTIFFs. render() therefore takes the interpreter to use, so the
caller can point it at that separate environment.
"""
import os
import subprocess
import sys
import textwrap


# Cycles on CPU, because a serverless worker may have no display and EEVEE
# wants a GL context. Samples are low deliberately: this is architectural
# massing under a soft sky, not a car advert, and the denoiser carries it.
DEFAULT_SAMPLES = 48

# A render that has not finished by now is not going to, and a job must not
# hang on a nice-to-have.
RENDER_TIMEOUT_S = 900

# Lighting, balanced against each other rather than picked separately. The
# sky is fill; the lamp is the key; the exposure trim stops a pale render
# clipping. Changing one without the others is how the first attempt came
# back as a white rectangle.
SUN_ENERGY = 3.0
SKY_STRENGTH = 0.10
EXPOSURE = -2.4

# THE BACKDROP IS COMPOSITED BY US, NOT RENDERED. A Nishita sky is
# physically bright, so the single exposure that makes brick look like brick
# crushes the sky to night — measured across three tone-mapping sweeps, all
# of which traded a correct building for a correct sky or the reverse.
# Rendering on transparent film and dropping a gradient in behind decouples
# them, and it matches preview.py so the fast and slow renders are siblings.
SKY_TOP = (150, 178, 210)
SKY_BOTTOM = (226, 234, 240)


class BlendError(RuntimeError):
    """Blender could not produce the render."""


def available(python=None):
    """Is a Blender we can drive actually installed? Returns (ok, reason)."""
    exe = python or sys.executable
    try:
        r = subprocess.run(
            [exe, "-c", "import bpy;print(bpy.app.version_string)"],
            capture_output=True, text=True, timeout=180)
    except Exception as e:
        return False, f"could not start {exe}: {e}"
    if r.returncode != 0:
        return False, ("bpy is not importable in that interpreter — install "
                       "the bpy wheel into its own virtualenv, or point "
                       "`python` at one that has it")
    return True, r.stdout.strip()


# Materials by the names model3d's exporter writes. Keyed on those names so
# the two files stay in step; anything unmatched keeps its glTF colour.
_MATERIALS = {
    # Albedos are LOW on purpose. Cycles works in linear light and AgX rolls
    # the top end off hard, so a "brick red" picked by eye in sRGB renders as
    # pale pink — which is exactly what the first three attempts produced.
    # These are the values that come back looking like brick.
    "brick":   dict(base=(0.30, 0.085, 0.055, 1.0), rough=0.93, spec=0.15),
    "plaster": dict(base=(0.62, 0.60, 0.55, 1.0), rough=0.90, spec=0.20),
    "tile":    dict(base=(0.030, 0.030, 0.034, 1.0), rough=0.68, spec=0.25),
    "glass":   dict(base=(0.14, 0.24, 0.33, 1.0), rough=0.04, spec=1.00,
                    transmission=0.85),
    "door":    dict(base=(0.11, 0.075, 0.055, 1.0), rough=0.42, spec=0.35),
    "slab":    dict(base=(0.34, 0.33, 0.31, 1.0), rough=0.95, spec=0.10),
    "floor":   dict(base=(0.26, 0.19, 0.12, 1.0), rough=0.80, spec=0.15),
}


def _script(glb, out, yaw, pitch, samples, width, height, sun_deg,
            sun_energy, sky_strength, exposure, mask_out):
    """The Blender-side program. Runs inside the child process only."""
    return textwrap.dedent(f"""
        import bpy, math, sys
        from mathutils import Vector

        # Empty the startup scene — the default cube would be in every render.
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath={glb!r})

        objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
        if not objs:
            print('NO_MESH'); sys.exit(3)

        # World bounds, for framing and for sizing the ground.
        lo = Vector(( 1e9,  1e9,  1e9))
        hi = Vector((-1e9, -1e9, -1e9))
        for o in objs:
            for c in o.bound_box:
                w = o.matrix_world @ Vector(c)
                for i in range(3):
                    lo[i] = min(lo[i], w[i]); hi[i] = max(hi[i], w[i])
        ctr = (lo + hi) / 2.0
        span = max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z) or 1.0

        MATS = {_MATERIALS!r}
        for o in objs:
            for slot in o.material_slots:
                m = slot.material
                if not m:
                    continue
                key = m.name.split('.')[0].lower()
                spec = MATS.get(key)
                if not spec:
                    continue
                m.use_nodes = True
                bsdf = m.node_tree.nodes.get('Principled BSDF')
                if not bsdf:
                    continue
                bsdf.inputs['Base Color'].default_value = spec['base']
                bsdf.inputs['Roughness'].default_value = spec['rough']
                if 'Specular IOR Level' in bsdf.inputs:
                    bsdf.inputs['Specular IOR Level'].default_value = spec['spec']
                t = spec.get('transmission')
                if t and 'Transmission Weight' in bsdf.inputs:
                    bsdf.inputs['Transmission Weight'].default_value = t
                    m.blend_method = 'BLEND'

        # Ground, so the building casts onto something and is not floating.
        bpy.ops.mesh.primitive_plane_add(size=span * 12,
                                         location=(ctr.x, ctr.y, lo.z))
        g = bpy.context.active_object
        gm = bpy.data.materials.new('ground')
        gm.use_nodes = True
        gb = gm.node_tree.nodes['Principled BSDF']
        gb.inputs['Base Color'].default_value = (0.075, 0.105, 0.045, 1.0)
        gb.inputs['Roughness'].default_value = 1.0
        g.data.materials.append(gm)

        # Sky. A real sky texture is what puts light into the shadows and
        # stops the north elevations reading as black holes.
        world = bpy.data.worlds.new('sky')
        bpy.context.scene.world = world
        world.use_nodes = True
        nt = world.node_tree
        bg = nt.nodes['Background']
        sky = nt.nodes.new('ShaderNodeTexSky')
        sky.sky_type = 'NISHITA'
        sky.sun_elevation = math.radians(42)
        sky.sun_rotation = math.radians({sun_deg})
        nt.links.new(sky.outputs[0], bg.inputs[0])
        # A NISHITA SKY ALREADY CONTAINS A SUN. Adding a full-strength sun
        # lamp on top of it doubles the key and blows the whole render to
        # white — first attempt came back with a cream house on a white
        # ground, materials correct and completely invisible. The sky is
        # dialled back to fill, and the lamp does the keying.
        bg.inputs[1].default_value = {sky_strength}

        # Key sun, matched to the sky's own sun so shadows agree with it.
        bpy.ops.object.light_add(type='SUN', location=(ctr.x, ctr.y,
                                                       hi.z + span))
        sun = bpy.context.active_object
        sun.data.energy = {sun_energy}
        sun.data.angle = math.radians(1.8)      # soft-edged shadows
        sun.rotation_euler = (math.radians(48), 0.0,
                              math.radians({sun_deg}))

        # Camera: orbit at yaw/pitch, framed on the building.
        yaw = math.radians({yaw}); pitch = math.radians({pitch})
        dist = span * 1.95
        eye = Vector((ctr.x + dist * math.cos(pitch) * math.sin(yaw),
                      ctr.y - dist * math.cos(pitch) * math.cos(yaw),
                      ctr.z + dist * math.sin(pitch)))
        bpy.ops.object.camera_add(location=eye)
        cam = bpy.context.active_object
        cam.data.lens = 40
        aim = Vector((ctr.x, ctr.y, ctr.z - span * 0.04))
        d = aim - eye
        cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
        bpy.context.scene.camera = cam

        sc = bpy.context.scene
        sc.render.engine = 'CYCLES'
        sc.cycles.device = 'CPU'
        sc.cycles.samples = {samples}
        sc.cycles.use_denoising = True
        sc.render.resolution_x = {width}
        sc.render.resolution_y = {height}
        sc.render.film_transparent = True
        sc.render.image_settings.file_format = 'PNG'
        sc.render.image_settings.color_mode = 'RGBA'
        sc.render.filepath = {out!r}
        # AgX rolls highlights off far more gracefully than Filmic, which
        # matters on a white-rendered roof under a bright sky.
        sc.view_settings.view_transform = 'AgX'
        sc.view_settings.look = 'AgX - Medium High Contrast'
        sc.view_settings.exposure = {exposure}
        bpy.ops.render.render(write_still=True)

        # THE MASK MUST BE THE BUILDING, NOT THE SCENE. Rendering on
        # transparent film puts the GROUND PLANE in the alpha too, which
        # measured out at 80.7% of the frame and 100% of the lower half — so
        # compositing through it clipped only the sky and left an image model
        # free to invent a whole extra wing below the horizon, which it did.
        # Hiding the ground and re-rendering at one sample gives the
        # silhouette of the building alone, which is the thing worth locking.
        if {mask_out!r}:
            g.hide_render = True
            sc.cycles.samples = 1
            sc.cycles.use_denoising = False
            sc.render.filepath = {mask_out!r}
            bpy.ops.render.render(write_still=True)
        print('RENDER_OK')
    """)


def render(glb_path, out_path, yaw_deg=35.0, pitch_deg=18.0,
           samples=DEFAULT_SAMPLES, width=1200, height=900, sun_deg=210.0,
           sun_energy=SUN_ENERGY, sky_strength=SKY_STRENGTH,
           exposure=EXPOSURE, python=None, timeout=RENDER_TIMEOUT_S,
           keep_mask=None):
    """Render a GLB with Cycles. Returns the output path.

    `python` is the interpreter that has bpy — deliberately separate, both
    for the licence boundary and because bpy pins numpy<2 and the rest of
    this worker needs numpy>=2 for GeoTIFFs.
    """
    if not os.path.exists(glb_path):
        raise BlendError(f"no such model: {glb_path}")
    exe = python or sys.executable
    ok, why = available(exe)
    if not ok:
        raise BlendError(
            f"cannot render with Blender: {why}. The measured model, its "
            f"exports and the built-in preview do not depend on this.")

    raw_mask = (out_path + ".rawmask.png") if keep_mask else ""
    script = _script(glb_path, out_path, yaw_deg, pitch_deg, samples,
                     width, height, sun_deg, sun_energy, sky_strength,
                     exposure, raw_mask)
    try:
        r = subprocess.run([exe, "-c", script], capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise BlendError(
            f"the render did not finish in {timeout}s. Lower `samples`, or "
            f"give the job a GPU — Cycles on CPU is the slow path.")
    if "RENDER_OK" not in r.stdout or not os.path.exists(out_path):
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-6:]
        raise BlendError("Blender did not produce an image: "
                         + " | ".join(tail)[:400])
    if keep_mask:
        # The building-only pass's alpha IS the measured silhouette, exact to
        # the pixel — what lets an AI restyle be forced back onto the
        # geometry rather than trusted to respect it.
        src_for_mask = raw_mask if os.path.exists(raw_mask) else out_path
        _save_mask(src_for_mask, keep_mask)
        if os.path.exists(raw_mask):
            os.remove(raw_mask)
    _drop_in_sky(out_path)
    return out_path


def _save_mask(rendered, mask_path):
    """Write the render's alpha as a black-and-white mask."""
    try:
        from PIL import Image
    except ImportError:
        return None
    img = Image.open(rendered).convert("RGBA")
    img.getchannel("A").save(mask_path)
    return mask_path


def views(glb_path, directory, scan, angles=((35, 18), (215, 20), (0, 6)),
          **kw):
    """The same three standard views preview.py produces, in Cycles.

    Named to match, so a caller can swap one for the other. A failed view
    never takes down the ones that worked, or the job that made them.
    """
    out = []
    names = ("corner", "rear-corner", "front")
    if len(angles) == 2:
        names = ("rear-corner", "front")
    for (yaw, pitch), name in zip(angles, names):
        p = os.path.join(directory, f"{scan}.{name}.cycles.png")
        try:
            render(glb_path, p, yaw_deg=yaw, pitch_deg=pitch, **kw)
            out.append((p, f"renders/{scan}.{name}.cycles.png", None))
        except BlendError as e:
            print(f"cycles {name} failed: {e}", file=sys.stderr)
    return out


def _drop_in_sky(path):
    """Composite the transparent render over a sky gradient.

    Kept on THIS side of the process boundary deliberately: it is a few lines
    of PIL, it needs no Blender, and it means the backdrop can be restyled
    without re-rendering anything.
    """
    try:
        from PIL import Image
    except ImportError:
        return path
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    grad = Image.new("RGB", (1, h))
    px = grad.load()
    for y in range(h):
        t = y / float(max(h - 1, 1))
        px[0, y] = tuple(int(SKY_TOP[k] + (SKY_BOTTOM[k] - SKY_TOP[k]) * t)
                         for k in range(3))
    back = grad.resize((w, h)).convert("RGBA")
    Image.alpha_composite(back, img).convert("RGB").save(path)
    return path
