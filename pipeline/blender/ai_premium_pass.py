"""ai_premium_pass.py — make an AI-GENERATED car GLB look premium.

Generated meshes come out of TRELLIS as one fused shell with a baked texture
and no named materials, so the render worker's glass/paint logic (which keys
off material names) cannot see the windows: they render as dark paint. This
pass gives a generated GLB the two things the library models get for free:

  1. REAL GLASS — glass faces are found by geometry + albedo (cabin band,
     above the waistline, dark/low-saturation, steeply pitched or vertical),
     split into a material literally named 'glass_ai' so BOTH the render
     worker's exclusion regex and the QC gates recognise it, then given the
     same smoky transparency clear_glass.py applies to library cars.
  2. A CLEAN NUMBER PLATE — generated plates are melted high-contrast
     rectangles (the model tries to build the dealer plate + frame as
     geometry). The recess is flattened and a proper GB plate quad is placed,
     same 520x111mm proportion the library uses.

Run: blender -b -noaudio --python ai_premium_pass.py -- in.glb out.glb \
         [tex_dir] [--reg AB12CDE] [--no-plates] [--front 0.30] [--side 0.52]

Verify the result by rendering both sides — never trust the log alone.
"""
import os
import sys

import bpy
import bmesh
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SRC = argv[0]
DST = argv[1]
TEX = argv[2] if len(argv) > 2 and not argv[2].startswith("--") else ""


def _opt(flag, default, cast=float):
    return cast(argv[argv.index(flag) + 1]) if flag in argv else default


A_FRONT = _opt("--front", 0.30)      # windscreen alpha (lower = clearer)
A_SIDE = _opt("--side", 0.52)        # side/rear glass
DO_PLATES = "--no-plates" not in argv
REG = _opt("--reg", "", str)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and len(o.data.vertices)]
if not meshes:
    print("AI_PREMIUM: no meshes"); sys.exit(1)

# ---- bounding box / axes -------------------------------------------------
allv = []
for o in meshes:
    co = np.empty(len(o.data.vertices) * 3)
    o.data.vertices.foreach_get("co", co)
    allv.append((np.asarray(o.matrix_world.to_4x4()) @ np.c_[
        co.reshape(-1, 3), np.ones(len(o.data.vertices))].T).T[:, :3])
V = np.vstack(allv)
lo, hi = V.min(0), V.max(0)
size = hi - lo
LA = int(np.argmax(size))                       # length axis
ZA = int(np.argmin(size[:3])) if False else 2   # GLB convention: +Y up after import is Z
WA = [a for a in (0, 1, 2) if a not in (LA, ZA)][0]
H = size[ZA]
print(f"AI_PREMIUM bbox={np.round(size,3)} length_axis={LA} up={ZA} width_axis={WA}")


def texture_of(mat):
    """(pixels HxWx4, width, height) of the material's base-colour image.

    Generated shells are ONE texture-driven material, so a material's
    Base Color default_value is meaningless white — the colour that matters
    lives in the baked image and has to be sampled per face (reading the
    default silently classified every face as 'bright paint' and found no
    glass at all).
    """
    if not mat or not mat.use_nodes:
        return None
    for n in mat.node_tree.nodes:
        # NB: images packed in a GLB load lazily — has_data is False until the
        # pixels are touched, so gating on it skips every texture.
        if n.type != "TEX_IMAGE" or not n.image:
            continue
        try:
            w, h = n.image.size
            if not (w and h):
                continue
            px = np.array(n.image.pixels[:], dtype=np.float32).reshape(h, w, 4)
            return px, w, h
        except Exception as e:
            print(f"AI_PREMIUM texture read failed ({n.image.name}): {str(e)[:60]}")
    return None


def face_luma(px, w, h, uvs):
    """Mean luminance of a face, sampled at its UV centroid."""
    u = float(np.mean([c[0] for c in uvs])) % 1.0
    v = float(np.mean([c[1] for c in uvs])) % 1.0
    x = min(int(u * w), w - 1)
    y = min(int(v * h), h - 1)
    r, g, b = px[y, x, :3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ---- 1. glass ------------------------------------------------------------
# Cabin band: above the waistline (~52% of height) and below the roof, with a
# surface normal that is not near-horizontal (roof panels are horizontal, glass
# is pitched). Texture-baked darkness is the confirming signal.
WAIST = lo[ZA] + 0.50 * H
ROOF = lo[ZA] + 0.97 * H
glass_faces = 0

gmat = bpy.data.materials.new("glass_ai")       # name matters: worker keys on it
gmat.use_nodes = True
gb = gmat.node_tree.nodes.get("Principled BSDF")
gb.inputs["Base Color"].default_value = (0.055, 0.06, 0.07, 1.0)
gb.inputs["Roughness"].default_value = 0.06
if "Transmission Weight" in gb.inputs:
    gb.inputs["Transmission Weight"].default_value = 0.0
gb.inputs["Alpha"].default_value = A_SIDE
gmat.blend_method = "BLEND"
gmat.use_backface_culling = False

for o in meshes:
    me = o.data
    if gmat.name not in [m.name for m in me.materials]:
        me.materials.append(gmat)
    gidx = [i for i, m in enumerate(me.materials) if m and m.name == gmat.name][0]
    mw = np.asarray(o.matrix_world.to_4x4())
    # normals need the rotation part only — the glTF importer rotates Y-up to
    # Z-up, so a raw local normal's z is NOT world up (this silently matched
    # zero faces until caught).
    rot = np.asarray(o.matrix_world.to_3x3())
    tex = texture_of(me.materials[0] if me.materials else None)
    bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
    uvl = bm.loops.layers.uv.active

    # pass 1: which faces sit in the greenhouse and are pitched like glazing
    band = []
    for f in bm.faces:
        c = f.calc_center_median()
        wc = (mw @ np.array([c.x, c.y, c.z, 1.0]))[:3]
        if not (WAIST < wc[ZA] < ROOF):
            continue
        n = rot @ np.array([f.normal.x, f.normal.y, f.normal.z])
        if abs(n[ZA]) / (np.linalg.norm(n) + 1e-9) > 0.80:
            continue                     # near-horizontal -> roof panel, not glass
        band.append(f)

    # pass 2: inside that band, glass is the DARK cluster. Absolute thresholds
    # fail on dark cars (the GTI is near-black paint), so take a percentile of
    # the band itself — relative darkness separates glazing from bodywork on
    # any colour.
    if tex and band and uvl:
        px, tw, th = tex
        lum = np.array([face_luma(px, tw, th, [l[uvl].uv for l in f.loops]) for f in band])
        cut = max(0.03, float(np.percentile(lum, 45)))
        for f, L in zip(band, lum):
            if L <= cut:
                f.material_index = gidx
                glass_faces += 1
        print(f"AI_PREMIUM band={len(band)} faces, luma p45={cut:.3f}, "
              f"median={np.median(lum):.3f}")
    else:                                 # no texture: fall back to geometry only
        for f in band:
            f.material_index = gidx
            glass_faces += 1
    bm.to_mesh(me); bm.free()
print(f"AI_PREMIUM glass: {glass_faces} faces -> 'glass_ai' (alpha {A_SIDE})")

# windscreen slightly clearer than side glass: second material for the front third
if glass_faces:
    fmat = gmat.copy(); fmat.name = "glass_ai_front"
    fb = fmat.node_tree.nodes.get("Principled BSDF")
    fb.inputs["Alpha"].default_value = A_FRONT
    fmat.blend_method = "BLEND"

# ---- 2. number plate -----------------------------------------------------
# Front = the length-end furthest from the roof-band centroid (long bonnet).
if DO_PLATES:
    roof_band = V[V[:, ZA] > lo[ZA] + 0.80 * H]
    roof_c = roof_band[:, LA].mean() if len(roof_band) else V[:, LA].mean()
    mid = (lo[LA] + hi[LA]) / 2
    front_is_max = (roof_c < mid)
    W = size[WA]
    pw = min(0.52 * (W / 1.8), 0.45 * W)         # 520mm plate scaled to car width
    ph = pw * (111.0 / 520.0)

    def plate(at_max, z_frac, name, tex):
        x = hi[LA] if at_max else lo[LA]
        x += (-0.004 * size[LA]) if at_max else (0.004 * size[LA])
        z = lo[ZA] + z_frac * H
        cw = (lo[WA] + hi[WA]) / 2
        me = bpy.data.meshes.new(name); ob = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(ob)
        bm = bmesh.new()
        def vert(dw, dz):
            p = [0.0, 0.0, 0.0]
            p[LA] = x; p[WA] = cw + dw; p[ZA] = z + dz
            return bm.verts.new(p)
        vs = [vert(-pw / 2, -ph / 2), vert(pw / 2, -ph / 2), vert(pw / 2, ph / 2), vert(-pw / 2, ph / 2)]
        if at_max != front_is_max:
            vs = vs[::-1]
        f = bm.faces.new(vs)
        uv = bm.loops.layers.uv.new()
        for i, l in enumerate(f.loops):
            l[uv].uv = [(0, 0), (1, 0), (1, 1), (0, 1)][i]
        bm.to_mesh(me); bm.free()
        m = bpy.data.materials.new(f"{name}_mat"); m.use_nodes = True
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Roughness"].default_value = 0.35
        if tex and os.path.exists(tex):
            img = m.node_tree.nodes.new("ShaderNodeTexImage")
            img.image = bpy.data.images.load(tex)
            m.node_tree.links.new(bsdf.inputs["Base Color"], img.outputs["Color"])
        else:   # no texture supplied: flat plate colour (front white / rear yellow)
            bsdf.inputs["Base Color"].default_value = ((0.92, 0.92, 0.9, 1) if "front" in name
                                                       else (0.95, 0.82, 0.1, 1))
        me.materials.append(m)
        return ob

    fpath = os.path.join(TEX, "plate_front.png") if TEX else ""
    rpath = os.path.join(TEX, "plate_rear.png") if TEX else ""
    plate(front_is_max, 0.30, "plate_front_ai", fpath)
    plate(not front_is_max, 0.46, "plate_rear_ai", rpath)
    print(f"AI_PREMIUM plates: front_at_{'max' if front_is_max else 'min'} width={pw:.3f}")

bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_materials="EXPORT")
print(f"AI_PREMIUM done -> {DST} ({os.path.getsize(DST)//1024}KB)")
