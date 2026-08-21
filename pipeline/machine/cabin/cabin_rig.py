#!/usr/bin/env python3
"""cabin_rig.py — LOCKED camera rig for the cabin gate (beauty + label passes).

Two passes, same absolute camera transforms, so before/after is comparable by
construction:

  mode=beauty : Cycles, Standard view transform (NEVER AgX), no denoising
                (this Blender has no OIDN; use_denoising=True dies AFTER
                "Blender quit" prints). Reports clipped-pixel fraction.
  mode=label  : flat emission, one colour per node, BOX filter width 0.01,
                1 sample -> deterministic one-label-per-pixel. Used to MEASURE
                pixel shares. Sub-mode `hideglass` deletes the glazing nodes so
                the label behind the glass is what is recorded.

AXIS CONVENTION, written as code not prose. glTF is Y-up; Blender's importer
maps (x,y,z)_gltf -> (x,-z,y)_blender. This car is length-on-X, so in BLENDER
the car length lies on X and up is Z. Azimuth is measured in the Blender XY
plane: az=0 looks at the car from +X (the car's +X end), az=180 from -X.
The nose end must be confirmed by looking at a render, never assumed.

Run: blender -b --python cabin_rig.py -- <in.glb> <outdir> <cfg.json>
        mode=beauty|label [hideglass] [views=az_el,az_el,...] [tag=NAME]
"""
import bpy
import json
import math
import os
import sys

argv = sys.argv[sys.argv.index("--") + 1:]
GLB, OUTD, CFG = argv[0], argv[1], argv[2]
MODE = "beauty"
HIDEGLASS = False
VIEWS = None
TAG = ""
HIDE_EXTRA = []
ONLY = None
for a in argv[3:]:
    if a.startswith("mode="):
        MODE = a.split("=", 1)[1]
    elif a == "hideglass":
        HIDEGLASS = True
    elif a.startswith("views="):
        VIEWS = a.split("=", 1)[1]
    elif a.startswith("tag="):
        TAG = a.split("=", 1)[1]
    elif a.startswith("only="):
        ONLY = a.split("=", 1)[1].split(",")
    elif a.startswith("hide="):
        HIDE_EXTRA = a.split("=", 1)[1].split(",")
os.makedirs(OUTD, exist_ok=True)

# ---------------------------------------------------------------- scene reset
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
# NO DENOISING — this container's Blender has no OpenImageDenoiser and
# use_denoising=True raises RuntimeError after "Blender quit" prints.
sc.cycles.use_denoising = False
sc.view_settings.view_transform = "Standard"   # never AgX
sc.view_settings.look = "None"
sc.view_settings.exposure = 0.0
sc.view_settings.gamma = 1.0
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_depth = "8"
# Blender dithers 8-bit output by default (dither_intensity 1.0), which moves
# every label colour by +-1 and makes exact-code matching impossible.
sc.render.dither_intensity = 0.0
sc.render.film_transparent = False
if sc.world is None:                       # use_empty=True gives no world
    sc.world = bpy.data.worlds.new("World")

bpy.ops.import_scene.gltf(filepath=GLB)
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
print(f"[rig] imported {len(objs)} mesh objects")

GLASS_NODES = {"Glass_Rear", "Glass_Windscreen", "Glass_Side_L", "Glass_Side_R"}


def basename(o):
    """Blender appends .001 on name collisions; strip it."""
    n = o.name
    if len(n) > 4 and n[-4] == "." and n[-3:].isdigit():
        n = n[:-4]
    return n


_hide = set(HIDE_EXTRA) | (GLASS_NODES if HIDEGLASS else set())
if _hide:
    _removed = []
    for o in list(objs):
        if basename(o) in _hide:
            _removed.append(basename(o))
            bpy.data.objects.remove(o, do_unlink=True)
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    print(f"[rig] hid {sorted(_removed)}: {len(objs)} objects remain")
    _missing = _hide - set(_removed)
    assert not _missing, f"hide= named nodes that do not exist: {_missing}"

# ------------------------------------------------------------------- car bbox
xs = []
ys = []
zs = []
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ __import__("mathutils").Vector(c)
        xs.append(w.x)
        ys.append(w.y)
        zs.append(w.z)
BB = [(min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))]
CTR = [(a + b) / 2 for a, b in BB]
DIAG = math.sqrt(sum((b - a) ** 2 for a, b in BB))
print(f"[rig] blender bbox x{BB[0]} y{BB[1]} z{BB[2]} diag={DIAG:.4f}")

# --------------------------------------------------------------------- config
DEFAULT = {
    "resolution": [1400, 900],
    "beauty_samples": 96,
    "world_rgb": [0.22, 0.22, 0.23],
    "sun": {"energy": 3.2, "euler_deg": [52, 0, 150], "angle_deg": 1.5},
    "fill": {"energy": 1.1, "euler_deg": [62, 0, -40]},
    # camera: perspective at product-viewer distance
    "lens_mm": 62.0,
    "dist_mult": 2.35,
    # az,el in degrees. az=0 is +X of the car, measured CCW in blender XY.
    "views": {"az000_e08": [0, 8], "az045_e08": [45, 8], "az090_e08": [90, 8],
              "az135_e08": [135, 8], "az180_e08": [180, 8],
              "az215_e12": [215, 12], "az270_e08": [270, 8],
              "az305_e12": [305, 12]},
    "cameras": {},
}
if os.path.exists(CFG):
    cfg = json.load(open(CFG))
else:
    cfg = DEFAULT

if VIEWS:
    vv = {}
    for tok in VIEWS.split(","):
        az, el = tok.split("_")
        vv[f"az{int(az):03d}_e{int(el):02d}"] = [float(az), float(el)]
    cfg["views"] = vv

# ABSOLUTE camera transforms are computed once and frozen into the config, so a
# later edit to the car can never move the cameras (qc_rig.py pattern).
if not cfg.get("cameras"):
    cfg["cameras"] = {}
    for name, (az, el) in cfg["views"].items():
        r = DIAG * cfg["dist_mult"]
        a, e = math.radians(az), math.radians(el)
        loc = [CTR[0] + r * math.cos(a) * math.cos(e),
               CTR[1] + r * math.sin(a) * math.cos(e),
               CTR[2] + r * math.sin(e) + DIAG * 0.055]
        cfg["cameras"][name] = {"loc": loc, "look": list(CTR)}
    json.dump(cfg, open(CFG, "w"), indent=1)
    print(f"[rig] froze {len(cfg['cameras'])} absolute cameras -> {CFG}")
else:
    print(f"[rig] reusing {len(cfg['cameras'])} frozen cameras from {CFG}")

sc.render.resolution_x, sc.render.resolution_y = cfg["resolution"]
sc.render.resolution_percentage = 100

# ------------------------------------------------------------------ materials
LABELS = {}
if MODE == "label":
    sc.cycles.samples = 1
    sc.cycles.pixel_filter_type = "BOX"
    sc.cycles.filter_width = 0.01
    sc.cycles.max_bounces = 0
    sc.cycles.transparent_max_bounces = 0
    sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0, 0, 0, 1)
    sc.world.node_tree.nodes["Background"].inputs[1].default_value = 0.0
    # Deterministic colour PER NAME via a hash — must NOT depend on which
    # nodes are present, or a hideglass pass would recolour everything and the
    # two passes could not be compared pixel-for-pixel.
    import hashlib
    # The palette is built over a FIXED name UNIVERSE (labels_universe.json
    # next to the config) so that hiding nodes cannot shuffle any colour.
    _uni = os.path.join(os.path.dirname(os.path.abspath(CFG)),
                        "labels_universe.json")
    names = sorted({basename(o) for o in objs})
    if os.path.exists(_uni):
        names = sorted(set(names) | set(json.load(open(_uni))))
    else:
        json.dump(names, open(_uni, "w"), indent=1)
    cube = [(40 + i * 43, 40 + j * 43, 40 + k * 43)
            for i in range(6) for j in range(6) for k in range(6)][1:]
    palette = []
    used = {}
    for n in names:
        h = int(hashlib.md5(n.encode()).hexdigest(), 16)
        for probe in range(len(cube)):
            c = cube[(h + probe) % len(cube)]
            if c not in used:
                used[c] = n
                break
        palette.append((n, c))
    LABELS = dict(palette)
    assert len(set(LABELS.values())) == len(LABELS), "label colour collision"
    for o in objs:
        n = basename(o)
        r, g, b = LABELS[n]
        m = bpy.data.materials.new(f"LBL_{n}_{o.name}")
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs[0].default_value = (r / 255.0, g / 255.0, b / 255.0, 1.0)
        em.inputs[1].default_value = 1.0
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(em.outputs[0], out.inputs[0])
        o.data.materials.clear()
        o.data.materials.append(m)
    json.dump(LABELS, open(os.path.join(OUTD, f"labels{TAG}.json"), "w"),
              indent=1)
else:
    sc.cycles.samples = cfg["beauty_samples"]
    sc.world.use_nodes = True
    wr = cfg["world_rgb"]
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = \
        (wr[0], wr[1], wr[2], 1.0)
    sc.world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    for key in ("sun", "fill"):
        s = cfg[key]
        ld = bpy.data.lights.new(key, type="SUN")
        ld.energy = s["energy"]
        if "angle_deg" in s:
            ld.angle = math.radians(s["angle_deg"])
        lo = bpy.data.objects.new(key, ld)
        lo.rotation_euler = [math.radians(v) for v in s["euler_deg"]]
        sc.collection.objects.link(lo)
    # ground plane so the car does not float in void
    bpy.ops.mesh.primitive_plane_add(size=DIAG * 6,
                                     location=(CTR[0], CTR[1], BB[2][0]))
    gp = bpy.context.active_object
    gm = bpy.data.materials.new("ground")
    gm.use_nodes = True
    bs = gm.node_tree.nodes["Principled BSDF"]
    bs.inputs["Base Color"].default_value = (0.30, 0.30, 0.31, 1)
    bs.inputs["Roughness"].default_value = 0.55
    gp.data.materials.append(gm)

# --------------------------------------------------------------------- render
cam_d = bpy.data.cameras.new("cam")
cam_d.lens = cfg["lens_mm"]
cam = bpy.data.objects.new("cam", cam_d)
sc.collection.objects.link(cam)
sc.camera = cam
tgt = bpy.data.objects.new("tgt", None)
sc.collection.objects.link(tgt)
tc = cam.constraints.new("TRACK_TO")
tc.target = tgt
tc.track_axis = "TRACK_NEGATIVE_Z"
tc.up_axis = "UP_Y"

suffix = ("_hideglass" if HIDEGLASS else "") + (f"_{TAG}" if TAG else "")
done = []
for name, c in cfg["cameras"].items():
    if ONLY and name not in ONLY:
        continue
    cam.location = c["loc"]
    tgt.location = c["look"]
    bpy.context.view_layer.update()
    out = os.path.join(OUTD, f"{MODE}{suffix}_{name}.png")
    if os.path.exists(out):
        os.remove(out)          # stale-frame guard: a died render must not lie
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
    done.append(out)
    print(f"[rig] rendered {out}")

print("CABIN_RIG_DONE " + json.dumps({"mode": MODE, "hideglass": HIDEGLASS,
                                      "files": done}))
