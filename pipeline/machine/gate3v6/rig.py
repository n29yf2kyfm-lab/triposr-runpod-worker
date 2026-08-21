"""GATE 3 v6 render rig — Blender-side.

Run:  blender -b --python rig.py -- job.json

One Blender process executes a LIST of render jobs against one GLB so the BVH
and the imported scene are paid for once (`use_persistent_data`).

AXIS / AZIMUTH CONTRACT  (measured on GOLF_V5_SOURCE_LOCKED.glb, 2026-08-20)
---------------------------------------------------------------------------
glTF frame: length on X, Y up, width on Z.  **NOSE AT -X** (grille, headlamps,
badge and plate all sit at x ~ -2.0).  This is the INVERSE of the nose-at-+X
assumption in canon_dims.py, which does not warn.

Camera azimuth is defined in glTF coords as
        cam_x = R*sin(az)      cam_z = R*cos(az)
which the glTF->Blender importer (x,y,z)->(x,-z,y) turns into
        cam_x = R*sin(az)      cam_y = -R*cos(az)      up = +Z

Therefore, FOR THIS FILE:
        az 270 -> camera at -X ....... STRAIGHT FRONT
        az 090 -> camera at +X ....... STRAIGHT REAR
        az 000 -> camera at +Z(glTF) . LEFT side      (car faces -X, so +Z is its left)
        az 180 -> camera at -Z(glTF) . RIGHT side
        az 305 / 315 ................. FRONT-LEFT three-quarter
        az 215 / 225 ................. FRONT-RIGHT three-quarter
        az 045 ....................... REAR-LEFT three-quarter
        az 135 ....................... REAR-RIGHT three-quarter

CONTAINER FACTS (paid for, do not rediscover)
  * Blender 4.0.2, CYCLES only (EEVEE cannot initialise, no EGL).
  * NO OpenImageDenoiser: use_denoising=True raises RuntimeError and the render
    dies AFTER "Blender quit" prints, silently leaving STALE frames. Every
    output path is unlinked before rendering and a DONE marker is written by
    this script - grep for the marker, never for Blender's exit.
  * View transform is Standard, never AgX/Filmic (AgX has produced three false
    verdicts in this project by clipping).
"""
import bpy, bmesh, json, math, os, sys, time
import numpy as np
from mathutils import Vector, Matrix

# ---------------------------------------------------------------- utilities

def log(*a):
    print("[rig]", *a, flush=True)


def argv_after_dashes():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


def wipe_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(path):
    bpy.ops.import_scene.gltf(filepath=path)
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    log("imported %d mesh objects from %s" % (len(objs), os.path.basename(path)))
    return objs


# --------------------------------------------------------------- geometry

def world_verts(obj):
    """Transformed vertices (never a node translation - downstream stages bake
    transforms and a translation read returns 0)."""
    me = obj.data
    n = len(me.vertices)
    if n == 0:
        return np.zeros((0, 3))
    co = np.empty(n * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    M = np.array(obj.matrix_world)
    return co @ M[:3, :3].T + M[:3, 3]


def scene_points(objs, stride=1):
    pts = []
    for o in objs:
        v = world_verts(o)
        if len(v) == 0:
            continue
        if stride > 1 and len(v) > stride * 4:
            v = v[::stride]
        pts.append(v)
    return np.vstack(pts) if pts else np.zeros((0, 3))


def bbox_of(objs):
    p = scene_points(objs)
    return p.min(0), p.max(0)


# --------------------------------------------------------------- materials

NEUTRAL_MATTE = dict(base=(0.62, 0.62, 0.62), rough=0.45, metal=0.0, spec=0.30)
CLAY = dict(base=(0.55, 0.55, 0.55), rough=0.90, metal=0.0, spec=0.05)
ZEBRA_SURF = dict(base=(0.42, 0.42, 0.42), rough=0.055, metal=0.0, spec=0.85)


def make_principled(name, base, rough, metal, spec, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*base, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = spec
    elif "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = spec
    if coat and "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = coat
    elif coat and "Clearcoat" in bsdf.inputs:
        bsdf.inputs["Clearcoat"].default_value = coat
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    m.blend_method = "OPAQUE"
    return m


def make_emission(name, colour, strength=1.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*colour, 1.0)
    em.inputs["Strength"].default_value = strength
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def make_normal_mat(name="NORMALS"):
    """World-space normal -> RGB (n*0.5+0.5), flat emission."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 1.0
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    mul = nt.nodes.new("ShaderNodeVectorMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = (0.5, 0.5, 0.5)
    add = nt.nodes.new("ShaderNodeVectorMath")
    add.operation = "ADD"
    add.inputs[1].default_value = (0.5, 0.5, 0.5)
    nt.links.new(geo.outputs["Normal"], mul.inputs[0])
    nt.links.new(mul.outputs[0], add.inputs[0])
    nt.links.new(add.outputs[0], em.inputs["Color"])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def make_wire_mat(name, wire_px=1.0, base=(0.86, 0.86, 0.86), wire=(0.02, 0.02, 0.02)):
    """Cycles Wireframe node - pixel-sized wires, no geometry explosion."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    mix = nt.nodes.new("ShaderNodeMixShader")
    base_sh = nt.nodes.new("ShaderNodeEmission")
    base_sh.inputs["Color"].default_value = (*base, 1.0)
    wire_sh = nt.nodes.new("ShaderNodeEmission")
    wire_sh.inputs["Color"].default_value = (*wire, 1.0)
    wf = nt.nodes.new("ShaderNodeWireframe")
    wf.use_pixel_size = True
    wf.inputs["Size"].default_value = wire_px
    nt.links.new(wf.outputs["Fact"], mix.inputs["Fac"])
    nt.links.new(base_sh.outputs[0], mix.inputs[1])
    nt.links.new(wire_sh.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return m


def make_mask_mat():
    m = bpy.data.materials.new("MASK")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1, 1, 1, 1)
    em.inputs["Strength"].default_value = 1.0
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


# Deterministic, well-separated, LIGHT palette for material-ID / exploded
# (never dark - the spec forbids hiding faults behind dark materials).
def id_palette(n):
    out = []
    for i in range(n):
        h = (i * 0.6180339887) % 1.0
        s = 0.55 + 0.30 * ((i * 7) % 3) / 2.0
        v = 0.80 + 0.18 * ((i * 5) % 2)
        import colorsys
        out.append(colorsys.hsv_to_rgb(h, s, min(v, 0.98)))
    return out


def assign_all(objs, mat):
    for o in objs:
        o.data.materials.clear()
        o.data.materials.append(mat)


def assign_per_object(objs, mats):
    for o, m in zip(objs, mats):
        o.data.materials.clear()
        o.data.materials.append(m)


# --------------------------------------------------------------- lighting

def clear_lights():
    for o in list(bpy.context.scene.objects):
        if o.type == "LIGHT":
            bpy.data.objects.remove(o, do_unlink=True)


def set_world(grey):
    w = bpy.data.worlds.get("W") or bpy.data.worlds.new("W")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (grey, grey, grey, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    nt.links.new(bg.outputs[0], out.inputs["Surface"])


def set_stripe_world(n_stripes=26, dark=0.10, bright=1.00):
    """ZEBRA / reflection-line environment: evenly spaced horizontal light bands
    over the whole sky, so any surface curvature shows as a bend in a line and a
    surface WAVE shows as a kink.

    Rendered with film_transparent so the striped sky never becomes the picture's
    background - compose.py flattens the alpha onto neutral grey. The owner's
    spec forbids hiding faults behind dark backgrounds; a striped backdrop would
    read as one.
    """
    w = bpy.data.worlds.get("W") or bpy.data.worlds.new("W")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    asin = nt.nodes.new("ShaderNodeMath"); asin.operation = "ARCSINE"
    mul = nt.nodes.new("ShaderNodeMath"); mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = float(n_stripes)
    sine = nt.nodes.new("ShaderNodeMath"); sine.operation = "SINE"
    step = nt.nodes.new("ShaderNodeMath"); step.operation = "GREATER_THAN"
    step.inputs[1].default_value = 0.0
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.inputs["Color1"].default_value = (dark, dark, dark, 1.0)
    mix.inputs["Color2"].default_value = (bright, bright, bright, 1.0)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 1.0
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    nt.links.new(sep.outputs["Z"], asin.inputs[0])
    nt.links.new(asin.outputs[0], mul.inputs[0])
    nt.links.new(mul.outputs[0], sine.inputs[0])
    nt.links.new(sine.outputs[0], step.inputs[0])
    nt.links.new(step.outputs[0], mix.inputs["Fac"])
    nt.links.new(mix.outputs[0], bg.inputs["Color"])
    nt.links.new(bg.outputs[0], out.inputs["Surface"])


def add_area(name, loc, rot, size, power, colour=(1, 1, 1)):
    d = bpy.data.lights.new(name, type="AREA")
    d.shape = "RECTANGLE"
    d.size = size[0]
    d.size_y = size[1]
    d.energy = power
    d.color = colour
    o = bpy.data.objects.new(name, d)
    o.location = loc
    o.rotation_euler = rot
    bpy.context.scene.collection.objects.link(o)
    return o


def studio_lights(centre, diag, bright=1.0):
    """Soft, even, high-key studio. No harsh shadows, no bloom, no dark side -
    the spec forbids hiding faults behind shadow."""
    clear_lights()
    cx, cy, cz = centre
    R = diag * 1.4
    # Calibrated 2026-08-21 against a 0.62-albedo matte car: the first rig ran
    # ~5x hot and clipped the car to pure white (3.67% of frame clipped). Base
    # power is now deliberately conservative and auto_exposure() finishes the job.
    P = bright * 190.0 * (diag / 4.6) ** 2
    # overhead softbox
    add_area("key_top", (cx, cy, cz + R * 0.95), (0, 0, 0), (diag * 1.5, diag * 1.5), P * 2.2)
    # four flanking softboxes at 45 deg, equal power => no dark side
    for i, (ax, ay) in enumerate([(1, 1), (1, -1), (-1, 1), (-1, -1)]):
        add_area("fill_%d" % i,
                 (cx + ax * R * 0.85, cy + ay * R * 0.85, cz + R * 0.35),
                 (math.radians(62), 0, math.atan2(-ay, -ax) + math.pi / 2),
                 (diag * 1.1, diag * 0.8), P * 1.15)
    # low bounce so the underbody / lower fascia is not lost to shadow
    add_area("bounce_low", (cx, cy, cz - diag * 0.55), (math.radians(180), 0, 0),
             (diag * 2.0, diag * 2.0), P * 0.35)


def strip_lights(centre, diag, n_strips=22, arc_deg=150.0, up_deg=62.0):
    """Zebra / reflection-line rig: long thin emissive strips on a dome.
    Fine enough that a surface wave shows as a kink in a line."""
    clear_lights()
    cx, cy, cz = centre
    R = diag * 1.55
    P = 900.0 * (diag / 4.6) ** 2
    for i in range(n_strips):
        t = (i + 0.5) / n_strips
        el = math.radians(-arc_deg / 2 + arc_deg * t) * 0.5 + math.radians(up_deg) * 0.0
        # sweep strips over the dome from front-low to back-high in elevation
        elev = math.radians(8.0 + (up_deg - 8.0) * t)
        # strips run ACROSS the car (along its length) so a lateral wave kinks them
        lx = cx
        ly = cy
        lz = cz + R * math.sin(elev)
        rad = R * math.cos(elev)
        # place the strip in front of the car (-X) since the zebra pass is a front view
        px = cx - rad
        d = bpy.data.lights.new("strip_%02d" % i, type="AREA")
        d.shape = "RECTANGLE"
        d.size = diag * 0.012          # thin
        d.size_y = diag * 2.6          # long
        d.energy = P
        o = bpy.data.objects.new("strip_%02d" % i, d)
        o.location = (px, ly, lz)
        # aim at the car centre
        dvec = Vector((cx, cy, cz)) - Vector((px, ly, lz))
        o.rotation_euler = dvec.to_track_quat("-Z", "Y").to_euler()
        bpy.context.scene.collection.objects.link(o)
    # a small ambient so the body is not black between stripes
    add_area("amb", (cx, cy, cz + R), (0, 0, 0), (diag * 2, diag * 2), 90.0 * (diag / 4.6) ** 2)


def add_ground(centre, diag, z, grey=0.34):
    m = make_principled("GROUND", (grey, grey, grey), 0.72, 0.0, 0.10)
    bpy.ops.mesh.primitive_plane_add(size=diag * 7.0, location=(centre[0], centre[1], z))
    g = bpy.context.active_object
    g.name = "GROUND"
    g.data.materials.clear()
    g.data.materials.append(m)
    return g


# ----------------------------------------------------------------- camera

def cam_position(az_deg, elev_deg, target, radius):
    """glTF-space azimuth -> Blender-space camera location. See module docstring."""
    a = math.radians(az_deg)
    e = math.radians(elev_deg)
    hx = math.sin(a) * math.cos(e)
    hy = -math.cos(a) * math.cos(e)
    hz = math.sin(e)
    return Vector((target[0] + radius * hx,
                   target[1] + radius * hy,
                   target[2] + radius * hz))


def make_camera(name, az, elev, target, radius, ortho_scale=None, lens=None, shift=(0, 0)):
    cd = bpy.data.cameras.new(name)
    if ortho_scale is not None:
        cd.type = "ORTHO"
        cd.ortho_scale = ortho_scale
        cd.clip_start = 0.001
        cd.clip_end = radius * 6 + 50
    else:
        cd.type = "PERSP"
        cd.lens = lens or 85.0
        cd.clip_start = 0.01
        cd.clip_end = radius * 6 + 50
    cd.shift_x, cd.shift_y = shift
    o = bpy.data.objects.new(name, cd)
    loc = cam_position(az, elev, target, radius)
    o.location = loc
    d = Vector(target) - loc
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(o)
    bpy.context.scene.camera = o
    # MANDATORY: matrix_world is stale until the depsgraph updates. Without this
    # every fit_ortho() call projected against the IDENTITY matrix and returned
    # the same ortho_scale for every azimuth (found in the smoke test, 2026-08-21).
    bpy.context.view_layer.update()
    return o


def project_extent(cam, pts, res_x, res_y):
    """True projected extent of a point cloud in normalised camera space.
    Returns (u0,v0,u1,v1) in [0,1] NDC-ish (may exceed for offscreen points)."""
    from bpy_extras.object_utils import world_to_camera_view
    scn = bpy.context.scene
    M = np.array(cam.matrix_world.inverted())
    P = pts @ M[:3, :3].T + M[:3, 3]          # camera space, -Z forward
    cd = cam.data
    aspect = res_x / float(res_y)
    if cd.type == "ORTHO":
        s = cd.ortho_scale
        if aspect >= 1.0:
            sx, sy = s, s / aspect
        else:
            sx, sy = s * aspect, s
        u = P[:, 0] / sx + 0.5
        v = P[:, 1] / sy + 0.5
    else:
        f = cd.lens
        sw = cd.sensor_width
        z = np.clip(-P[:, 2], 1e-6, None)
        if aspect >= 1.0:
            sx, sy = sw, sw / aspect
        else:
            sx, sy = sw * aspect, sw
        u = (P[:, 0] * f / z) / sx + 0.5
        v = (P[:, 1] * f / z) / sy + 0.5
    return float(u.min()), float(v.min()), float(u.max()), float(v.max())


def fit_ortho(cam, pts, res_x, res_y, target_occ):
    """Set ortho_scale so the projected silhouette bbox fills target_occ of the
    frame in its LARGER normalised dimension. Analytic, exact for ortho."""
    cd = cam.data
    cd.ortho_scale = 10.0
    u0, v0, u1, v1 = project_extent(cam, pts, res_x, res_y)
    aspect = res_x / float(res_y)
    if aspect >= 1.0:
        w_m = (u1 - u0) * 10.0
        h_m = (v1 - v0) * (10.0 / aspect)
        need = max(w_m / 1.0, h_m / (1.0 / aspect))
    else:
        w_m = (u1 - u0) * (10.0 * aspect)
        h_m = (v1 - v0) * 10.0
        need = max(w_m / aspect, h_m)
    cd.ortho_scale = need / target_occ
    # recentre via camera shift so the silhouette is centred in frame
    u0, v0, u1, v1 = project_extent(cam, pts, res_x, res_y)
    cd.shift_x += (0.5 - (u0 + u1) / 2.0) * (1.0 if aspect >= 1 else aspect)
    cd.shift_y += (0.5 - (v0 + v1) / 2.0) * (1.0 / aspect if aspect >= 1 else 1.0)
    return cd.ortho_scale


# ------------------------------------------------------------------ render

def render_settings(res_x, res_y, samples, flat=False, world_grey=0.22,
                    transparent=False, exposure=0.0):
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = samples
    scn.cycles.use_adaptive_sampling = not flat
    scn.cycles.adaptive_threshold = 0.02
    # NO OpenImageDenoiser in this container - True raises RuntimeError and the
    # render dies after "Blender quit" prints, leaving stale frames.
    scn.cycles.use_denoising = False
    scn.cycles.max_bounces = 2 if not flat else 0
    scn.cycles.diffuse_bounces = 2 if not flat else 0
    scn.cycles.glossy_bounces = 2 if not flat else 0
    scn.cycles.transmission_bounces = 2 if not flat else 0
    scn.cycles.transparent_max_bounces = 2 if not flat else 0
    scn.cycles.volume_bounces = 0
    scn.cycles.caustics_reflective = False
    scn.cycles.caustics_refractive = False
    scn.render.use_persistent_data = True
    scn.render.resolution_x = res_x
    scn.render.resolution_y = res_y
    scn.render.resolution_percentage = 100
    scn.render.image_settings.file_format = "PNG"
    scn.render.image_settings.color_mode = "RGBA" if transparent else "RGB"
    scn.render.image_settings.color_depth = "8"
    scn.render.image_settings.compression = 15
    scn.render.film_transparent = transparent
    scn.render.filter_size = 0.01 if flat else 1.5   # AA off for flat label passes
    # STANDARD view transform. NEVER AgX - it has produced three false verdicts here.
    scn.view_settings.view_transform = "Standard"
    scn.view_settings.look = "None"
    scn.view_settings.exposure = exposure
    scn.view_settings.gamma = 1.0
    scn.display_settings.display_device = "sRGB"
    set_world(world_grey)


def srgb_to_linear(a01):
    """a01 already in 0..1 sRGB-encoded units."""
    a = np.asarray(a01, dtype=np.float64)
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def read_png_rgba(path):
    """Read a PNG as an (H,W,4) float array of the RAW STORED values (0..1,
    sRGB-encoded for colour channels).

    Blender's bundled Python has NO PIL - found the hard way on 2026-08-21 when
    the first auto_exposure probe silently fell back to 0 stops for every view.
    Loading as Non-Color is what stops Blender from linearising behind our back.
    """
    img = bpy.data.images.load(path, check_existing=False)
    try:
        img.colorspace_settings.name = "Non-Color"
        w, h = img.size
        buf = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)
        a = buf.reshape(h, w, 4).astype(np.float64)
        return a[::-1]                       # Blender stores bottom-up
    finally:
        bpy.data.images.remove(img)


def auto_exposure(tmp_path, res_x, res_y, target_lin=0.85, pct=99.8,
                  probe_px=320, samples=8, lo=-5.0, hi=2.0):
    """Render a small ALPHA-MASKED probe of the CURRENT scene, measure the p99.8
    linear luminance of CAR pixels only, and set scene.view_settings.exposure so
    the brightest car surfaces land just under clipping.

    Why a probe and not a fixed light power: this project has produced three
    false verdicts from clipped renders. Exposure is MEASURED here, never assumed.
    Returns (stops, measured_p, predicted_p).
    """
    scn = bpy.context.scene
    keep = (scn.render.resolution_x, scn.render.resolution_y,
            scn.cycles.samples, scn.render.film_transparent,
            scn.render.image_settings.color_mode, scn.view_settings.exposure,
            scn.render.filepath, scn.cycles.use_adaptive_sampling)
    ar = res_x / float(res_y)
    scn.render.resolution_x = probe_px
    scn.render.resolution_y = max(8, int(round(probe_px / ar)))
    scn.cycles.samples = samples
    scn.cycles.use_adaptive_sampling = True
    scn.render.film_transparent = True
    scn.render.image_settings.color_mode = "RGBA"
    scn.view_settings.exposure = 0.0
    ground = bpy.data.objects.get("GROUND")
    gh = None
    if ground is not None:
        gh = ground.hide_render
        ground.hide_render = True
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    scn.render.filepath = tmp_path
    bpy.ops.render.render(write_still=True)
    if ground is not None:
        ground.hide_render = gh
    stops, meas = 0.0, None
    sil = {}
    try:
        im = read_png_rgba(tmp_path)
        a = im[..., 3]
        sel = a > 0.90
        # SILHOUETTE METRICS off the same alpha probe: this is the authority for
        # "is this tile populated" and for occupancy. Measured on the actual
        # rendered frame, never asserted from the fit maths.
        cov = a > 0.5
        sil["silhouette_px_frac"] = float(cov.mean())
        if cov.any():
            ys, xs = np.nonzero(cov)
            sil["silhouette_occ_x"] = float((xs.max() - xs.min() + 1) / cov.shape[1])
            sil["silhouette_occ_y"] = float((ys.max() - ys.min() + 1) / cov.shape[0])
            sil["silhouette_occ_max"] = max(sil["silhouette_occ_x"], sil["silhouette_occ_y"])
        sil["probe_res"] = [int(cov.shape[1]), int(cov.shape[0])]
        if sel.sum() >= 40:
            lin = srgb_to_linear(im[..., :3])
            lum = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
            meas = float(np.percentile(lum[sel], pct))
            if meas > 1e-6:
                stops = float(np.clip(math.log2(target_lin / meas), lo, hi))
    except Exception as e:                                    # pragma: no cover
        log("auto_exposure probe unreadable (%s) - exposure left at 0" % e)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    (scn.render.resolution_x, scn.render.resolution_y, scn.cycles.samples,
     scn.render.film_transparent, scn.render.image_settings.color_mode,
     _, scn.render.filepath, scn.cycles.use_adaptive_sampling) = keep
    scn.view_settings.exposure = stops
    pred = None if meas is None else meas * (2.0 ** stops)
    log("auto_exposure: p%.1f=%s -> %+.2f stops -> predicted %s  sil_px=%.4f occ=%.3f"
        % (pct, "n/a" if meas is None else "%.4f" % meas, stops,
           "n/a" if pred is None else "%.4f" % pred,
           sil.get("silhouette_px_frac", -1), sil.get("silhouette_occ_max", -1)))
    r = {"exposure_stops": stops, "probe_p%.1f_linear" % pct: meas,
         "predicted_peak_linear": pred, "target_linear": target_lin}
    r.update(sil)
    return r


def measure_render(path, bg_srgb=None):
    """Post-hoc measurement of a written frame: clipped fraction and, when a
    background grey is given, the silhouette bbox occupancy. Never a claim -
    always read back off the actual file."""
    raw = read_png_rgba(path)
    im = np.rint(raw[..., :3] * 255.0).astype(np.int32)
    out = {"res": [im.shape[1], im.shape[0]]}
    mx = im.max(2)
    out["clipped_frac_frame"] = float((mx >= 255).mean())
    out["bg_corner_srgb"] = [int(x) for x in im[2, 2]]
    a = raw[..., 3]
    if a.min() < 0.99:                      # RGBA render: alpha IS the silhouette
        cov = a > 0.5
        out["silhouette_px_frac"] = float(cov.mean())
        if cov.any():
            ys, xs = np.nonzero(cov)
            out["silhouette_occ_x"] = float((xs.max() - xs.min() + 1) / cov.shape[1])
            out["silhouette_occ_y"] = float((ys.max() - ys.min() + 1) / cov.shape[0])
            out["silhouette_occ_max"] = max(out["silhouette_occ_x"], out["silhouette_occ_y"])
            out["clipped_frac_car"] = float((mx[cov] >= 255).mean())
    if bg_srgb is not None:
        d = np.abs(im - np.array(bg_srgb)[None, None, :]).sum(2) > 18
        ys, xs = np.nonzero(d)
        if len(xs):
            out["nonbg_frac"] = float(d.mean())
            out["clipped_frac_nonbg"] = float((mx[d] >= 255).mean())
            out["bbox_px"] = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
            out["occ_x"] = float((xs.max() - xs.min() + 1) / im.shape[1])
            out["occ_y"] = float((ys.max() - ys.min() + 1) / im.shape[0])
    return out


def render_to(path):
    if os.path.exists(path):
        os.remove(path)          # a stale frame must never read as a fresh one
    bpy.context.scene.render.filepath = path
    t = time.time()
    bpy.ops.render.render(write_still=True)
    if not os.path.exists(path):
        raise RuntimeError("RENDER PRODUCED NO FILE: %s" % path)
    log("wrote %s  (%.1fs, %.1fMB)" % (os.path.basename(path), time.time() - t,
                                       os.path.getsize(path) / 1e6))
    return path
