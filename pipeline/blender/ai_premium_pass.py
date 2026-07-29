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


A_FRONT = _opt("--front", 0.42)      # windscreen alpha (lower = clearer)
A_SIDE = _opt("--side", 0.66)        # side/rear glass
DO_PLATES = "--no-plates" not in argv
DO_SYMMETRY = "--no-symmetry" not in argv
GLASS_PCT = _opt("--glass-pct", 25.0)
DO_MATERIALS = "--no-materials" not in argv
DO_SMOOTH = "--no-smooth" not in argv
SHARP_ANGLE = _opt("--sharp-angle", 34.0)      # keep creases above this
SMOOTH_ITERS = int(_opt("--smooth-iters", 2))
SMOOTH_LAMBDA = _opt("--smooth-lambda", 0.35)
TRUE_LENGTH_MM = _opt("--length-mm", 0.0)
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


# ---- 0. symmetry --------------------------------------------------------
# The generator builds left and right independently, so a front-LEFT render
# shows a different headlight from a front-RIGHT render. That is the single
# biggest "AI tell" — it reads as geometry changing between views when it is
# really two mismatched halves. Bisect at the centreline, keep the better half
# (more faces in the nose region = more resolved detail), mirror it back.
if DO_SYMMETRY:
    import mathutils
    cw = (lo[WA] + hi[WA]) / 2
    for o in meshes:
        mw = np.asarray(o.matrix_world.to_4x4())
        me = o.data
        bm = bmesh.new(); bm.from_mesh(me)
        nose = lo[LA] + 0.25 * size[LA]
        cnt = {"+": 0, "-": 0}
        for f in bm.faces:
            c = f.calc_center_median()
            wc = (mw @ np.array([c.x, c.y, c.z, 1.0]))[:3]
            if wc[LA] < nose or wc[LA] > hi[LA] - 0.25 * size[LA]:
                cnt["+" if wc[WA] >= cw else "-"] += 1
        keep_positive = cnt["+"] >= cnt["-"]
        print(f"AI_PREMIUM symmetry: end-detail faces +{cnt['+']} / -{cnt['-']} "
              f"-> keeping {'+' if keep_positive else '-'} side")
        # world-space cut plane -> local space for bmesh.bisect_plane
        inv = np.linalg.inv(mw)
        p_w = np.zeros(3); p_w[WA] = cw
        p_l = (inv @ np.array([p_w[0], p_w[1], p_w[2], 1.0]))[:3]
        n_w = np.zeros(3); n_w[WA] = 1.0 if keep_positive else -1.0
        n_l = (inv[:3, :3] @ n_w)
        res = bmesh.ops.bisect_plane(bm, geom=list(bm.faces) + list(bm.edges) + list(bm.verts),
                                     plane_co=mathutils.Vector(p_l),
                                     plane_no=mathutils.Vector(n_l),
                                     clear_inner=True, clear_outer=False)
        bmesh.ops.delete(bm, geom=[g for g in res.get("geom_cut", []) if isinstance(g, bmesh.types.BMFace)],
                         context="FACES_ONLY")
        bm.to_mesh(me); bm.free()
        m = o.modifiers.new("mirror", "MIRROR")
        m.use_axis = tuple(i == WA for i in range(3))
        m.use_clip = True
        m.use_mirror_merge = True
        m.merge_threshold = 0.0008
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.modifier_apply(modifier=m.name)
    print("AI_PREMIUM symmetry: mirrored — headlights/lights/bumper now identical L/R")

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
        nz = abs(n[ZA]) / (np.linalg.norm(n) + 1e-9)
        if nz > 0.80:
            continue                     # near-horizontal -> roof panel, not glass
        band.append((f, wc[ZA], nz))

    # pass 2: inside that band, glass is the DARK cluster. Absolute thresholds
    # fail on dark cars (the GTI is near-black paint), so take a percentile of
    # the band itself — relative darkness separates glazing from bodywork on
    # any colour.
    if tex and band and uvl:
        px, tw, th = tex
        lum = np.array([face_luma(px, tw, th, [l[uvl].uv for l in f.loops]) for f, _, _ in band])
        # 45% was too generous on a black car (paint and glass luminance nearly
        # match) and bled into pillars/quarter panels; 25% keeps the glazing core
        cut = max(0.02, float(np.percentile(lum, GLASS_PCT)))
        for (f, _, _), L in zip(band, lum):
            if L <= cut:
                f.material_index = gidx
                glass_faces += 1
        print(f"AI_PREMIUM band={len(band)} faces, luma p45={cut:.3f}, "
              f"median={np.median(lum):.3f}")
    else:
        # no texture: geometry only. Marking the WHOLE band as glass turned the
        # d3s2 Golf's doors, wings and cowl into glazing — the band includes
        # every side panel above half height. Real glazing is TILTED: the
        # windscreen/backlight slope hard and side glass has tumblehome, while
        # door and quarter panels are near-vertical. Keep only pitched faces,
        # and start the band at the actual beltline, not half height.
        WAIST_NT = lo[ZA] + 0.60 * H
        for f, wz, nz in band:
            if wz > WAIST_NT and 0.18 < nz <= 0.80:
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

# ---- 1b. automotive materials + glass thickness --------------------------
# Generated shells arrive as one flat texture-lit material: no clearcoat, tyres
# as shiny as the paint, no glass thickness. Assign real automotive shading so
# the render worker's studio lighting has something to work with.
if DO_MATERIALS:
    ARCH = lo[ZA] + 0.34 * H          # below this, wheels/tyres/sills live
    rubber = bpy.data.materials.new("tyre_rubber_ai")
    rubber.use_nodes = True
    rb = rubber.node_tree.nodes.get("Principled BSDF")
    rb.inputs["Base Color"].default_value = (0.022, 0.022, 0.024, 1.0)
    rb.inputs["Roughness"].default_value = 0.92
    if "Specular IOR Level" in rb.inputs:
        rb.inputs["Specular IOR Level"].default_value = 0.18

    tyre_faces = 0
    for o in meshes:
        me = o.data
        if rubber.name not in [m.name for m in me.materials]:
            me.materials.append(rubber)
        ridx = [i for i, m in enumerate(me.materials) if m and m.name == rubber.name][0]
        gset = {i for i, m in enumerate(me.materials) if m and m.name.startswith("glass_ai")}
        mw = np.asarray(o.matrix_world.to_4x4())
        tex = texture_of(me.materials[0] if me.materials else None)
        bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
        uvl = bm.loops.layers.uv.active
        centers = []
        for f in bm.faces:
            c = f.calc_center_median()
            centers.append((mw @ np.array([c.x, c.y, c.z, 1.0]))[:3])
        centers = np.array(centers)
        # Without a texture there is no bright-luma escape hatch, so a plain
        # height band paints bumpers and sills black (the d3s2 Golf wore a
        # black belt to mid-door). Find the axles instead — the two densest
        # clusters of near-ground faces along the length axis — and keep the
        # rubber inside the wheel-arch zones around them.
        axles = None
        if not (tex and uvl):
            low = centers[centers[:, ZA] < lo[ZA] + 0.12 * H]
            if len(low) > 100:
                bl = hi[LA] - lo[LA]
                hist, edges = np.histogram(low[:, LA], bins=40)
                mid = (edges[:-1] + edges[1:]) / 2
                front_half = mid < lo[LA] + 0.5 * bl
                # both halves must actually contain ground faces: a mesh whose
                # low geometry sits entirely in one half (vans, odd pivots)
                # crashed argmax on the empty other half (2026-07-29)
                if hist[front_half].any() and hist[~front_half].any():
                    a1 = mid[front_half][np.argmax(hist[front_half])]
                    a2 = mid[~front_half][np.argmax(hist[~front_half])]
                    axles = (a1, a2, 0.125 * bl)
                    print(f"AI_PREMIUM axles at {a1:.2f}/{a2:.2f} (len axis), "
                          f"arch half-width {axles[2]:.2f}")
                else:
                    print("AI_PREMIUM axles: ground faces all in one half - "
                          "falling back to plain height band")
        for i, f in enumerate(bm.faces):
            if f.material_index in gset:
                continue
            wc = centers[i]
            if wc[ZA] > ARCH:
                continue                      # only the wheel band
            if tex and uvl:
                px, tw, th = tex
                if face_luma(px, tw, th, [l[uvl].uv for l in f.loops]) > 0.10:
                    continue                  # bright = alloy spoke or sill, not tyre
            elif axles is not None:
                a1, a2, hw = axles
                near_wheel = min(abs(wc[LA] - a1), abs(wc[LA] - a2)) < hw
                if not near_wheel and wc[ZA] > lo[ZA] + 0.06 * H:
                    continue                  # sill/bumper between axles: stays paint
            f.material_index = ridx
            tyre_faces += 1
        bm.to_mesh(me); bm.free()

        # body paint: clearcoat over the baked texture (keeps the car's colour)
        for m in me.materials:
            if not m or m.name.startswith(("glass_ai", "tyre_rubber_ai", "plate_")):
                continue
            b = m.node_tree.nodes.get("Principled BSDF") if m.use_nodes else None
            if not b:
                continue
            b.inputs["Roughness"].default_value = 0.28
            if "Metallic" in b.inputs:
                b.inputs["Metallic"].default_value = 0.15
            for coat in ("Coat Weight", "Clearcoat"):
                if coat in b.inputs:
                    b.inputs[coat].default_value = 1.0
            for cr in ("Coat Roughness", "Clearcoat Roughness"):
                if cr in b.inputs:
                    b.inputs[cr].default_value = 0.04
    print(f"AI_PREMIUM materials: {tyre_faces} tyre faces -> rubber; clearcoat paint applied")

    # island cleanup: heuristic classification leaves confetti — a dozen glass
    # faces stranded on the bonnet render as dark specks, a dozen paint faces
    # inside a window as white specks. Absorb any connected same-material patch
    # smaller than MIN_ISLAND into whichever material surrounds it most.
    MIN_ISLAND = int(_opt("--min-island", 0))
    for o in meshes:
        me = o.data
        n_faces = len(me.polygons)
        min_isl = MIN_ISLAND or max(50, n_faces // 400)
        bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
        mat_of = [f.material_index for f in bm.faces]
        adj = [[] for _ in range(len(mat_of))]
        for e in bm.edges:
            lf = e.link_faces
            if len(lf) == 2:
                adj[lf[0].index].append(lf[1].index)
                adj[lf[1].index].append(lf[0].index)
        comp = [-1] * len(mat_of)
        cid = 0
        sizes, members = [], []
        for s in range(len(mat_of)):
            if comp[s] != -1:
                continue
            stack = [s]; comp[s] = cid; mem = [s]
            while stack:
                u = stack.pop()
                for v in adj[u]:
                    if comp[v] == -1 and mat_of[v] == mat_of[u]:
                        comp[v] = cid; stack.append(v); mem.append(v)
            sizes.append(len(mem)); members.append(mem)
            cid += 1
        absorbed = 0
        for k in range(cid):
            if sizes[k] >= min_isl:
                continue
            votes = {}
            for u in members[k]:
                for v in adj[u]:
                    if comp[v] != k:
                        votes[mat_of[v]] = votes.get(mat_of[v], 0) + 1
            if votes:
                new_mat = max(votes, key=votes.get)
                for u in members[k]:
                    mat_of[u] = new_mat
                absorbed += sizes[k]
        for f in bm.faces:
            f.material_index = mat_of[f.index]
        bm.to_mesh(me); bm.free()
        print(f"AI_PREMIUM island cleanup: absorbed {absorbed} faces in patches "
              f"<{min_isl} (of {n_faces})")

    # glass thickness: a single-surface window renders like a decal; give it
    # real depth so edges catch light at grazing angles.
    # SOLIDIFY MUST ONLY SEE GLASS FACES. On a fused AI shell the glass shares
    # one mesh with the body, and solidifying that object duplicates the WHOLE
    # car into two shells ±thickness/2 apart — the coincident surfaces render
    # as salt-and-pepper "popcorn" over every panel (root-caused on the d3s2
    # Golf, 2026-07-28). Separate the glass faces into their own object first
    # and solidify only that.
    for o in list(meshes):
        gset = {i for i, m in enumerate(o.data.materials)
                if m and m.name.startswith("glass_ai")}
        if not gset:
            continue
        n_glass = sum(1 for p in o.data.polygons if p.material_index in gset)
        if n_glass == 0:
            continue
        if n_glass == len(o.data.polygons):
            gobj = o                      # already a pure glass object
        else:
            for p in o.data.polygons:
                p.select = p.material_index in gset
            before = set(bpy.data.objects)
            bpy.context.view_layer.objects.active = o
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.separate(type="SELECTED")
            bpy.ops.object.mode_set(mode="OBJECT")
            new = [x for x in set(bpy.data.objects) - before if x.type == "MESH"]
            if not new:
                print("AI_PREMIUM solidify skipped: glass separate produced no object")
                continue
            gobj = new[0]
        sol = gobj.modifiers.new("glass_thickness", "SOLIDIFY")
        sol.thickness = max(0.0015, 0.004 * H)
        sol.offset = -1.0   # thickness grows inward: centred shells poke through voxel bumps as specks
        sol.material_offset = 0
        bpy.context.view_layer.objects.active = gobj
        try:
            bpy.ops.object.modifier_apply(modifier=sol.name)
            print(f"AI_PREMIUM glass thickness {sol.thickness:.4f} applied "
                  f"({n_glass} glass faces separated, body untouched)")
        except Exception as e:
            print(f"AI_PREMIUM solidify skipped: {str(e)[:60]}")

# ---- 1c. surface quality -------------------------------------------------
# Generated shells carry micro-ripple and flat-shaded facets, so studio
# reflections break up instead of flowing along the body — the "not a real car"
# tell that survives every other fix. Two cheap treatments:
#   * shade-smooth with a sharp-edge angle: normals blend across panels but
#     creases (bonnet shut line, arch lips) stay hard;
#   * a light volume-preserving Laplacian pass on BODY faces only, which flattens
#     ripple without eating the little crease detail the model did resolve.
if DO_SMOOTH:
    for o in meshes:
        me = o.data
        for poly in me.polygons:
            poly.use_smooth = True
        try:                                   # Blender 4.1+ dropped auto_smooth
            me.set_sharp_from_angle(angle=float(np.radians(SHARP_ANGLE)))
        except Exception:
            try:
                me.use_auto_smooth = True
                me.auto_smooth_angle = float(np.radians(SHARP_ANGLE))
            except Exception:
                pass
        bpy.context.view_layer.objects.active = o
        lap = o.modifiers.new("body_smooth", "LAPLACIANSMOOTH")
        lap.iterations = SMOOTH_ITERS
        lap.lambda_factor = SMOOTH_LAMBDA
        lap.lambda_border = 0.0
        lap.use_volume_preserve = True
        lap.use_x = lap.use_y = lap.use_z = True
        try:
            bpy.ops.object.modifier_apply(modifier=lap.name)
            print(f"AI_PREMIUM surface: shade-smooth @{SHARP_ANGLE}deg + laplacian "
                  f"x{SMOOTH_ITERS} lambda={SMOOTH_LAMBDA}")
        except Exception as e:
            print(f"AI_PREMIUM smoothing skipped: {str(e)[:60]}")

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

# ---- 3. true scale -------------------------------------------------------
# Factory length from platform/geometry/vehicle_dims.csv (verified, sourced).
if TRUE_LENGTH_MM:
    target = TRUE_LENGTH_MM / 1000.0
    factor = target / size[LA]
    for o in bpy.context.scene.objects:
        if o.parent is None:
            o.scale = tuple(v * factor for v in o.scale)
    bpy.context.view_layer.update()
    print(f"AI_PREMIUM true-scale: {size[LA]:.3f} -> {target:.3f} m (x{factor:.3f})")

bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_materials="EXPORT")
print(f"AI_PREMIUM done -> {DST} ({os.path.getsize(DST)//1024}KB)")
