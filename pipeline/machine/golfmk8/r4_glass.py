#!/usr/bin/env python3
"""r4_glass.py — REPAIR 4: rebuild the glazing as one clean pane per window.

WHY A CLASSIFIER AND NOT THE NODE NAMES. In this source every window shares a
single object called `glass`: 278 components, 31,610 cm2. The earlier pane tool
grouped one window per NODE, which cannot work here. An earlier attempt at
merging by parallel-normal + bounding-box overlap also failed, because the
windscreen and side glass boxes overlap at the A-pillar and nine skins collapsed
into one surface fitted at 22.78 mm rms.

So windows are assigned SEMANTICALLY, from the two things that actually separate
them -- where a component sits, and which way it faces:

    |n_y| dominant, y > 0        -> Glass_Side_L
    |n_y| dominant, y < 0        -> Glass_Side_R
    x >  BACKLIGHT_X             -> Glass_Rear
    otherwise, x < 0             -> Glass_Windscreen

Inner skins land in the same class as their outer skin because the test is
sign-agnostic on the normal.

THE PANE IS FITTED FROM THE WHOLE CLASS, NOT FROM ITS LARGEST MEMBER. Taking the
largest was the first attempt and it built the windscreen out of the 1,414.7 cm2
COWL STRIP, because this windscreen is shattered into four pieces (1,415 + 1,361
+ 965 + 671 cm2) and none of them dominates. The result was a 1,347 cm2
"windscreen" -- about a fifth of a real one. Fitting the union is safe here in a
way it was NOT for the earlier bbox-overlap merge, because the semantic
classifier guarantees every member is the same physical window; the surfaces
being merged are the two skins of one pane, ~4 mm apart, and solidify regenerates
the inner one anyway.

Debris below MIN_CM2 is dropped -- measured at 258 components totalling 334 cm2,
1.1% of the glazing.

Run: blender -b --python r4_glass.py -- in.glb out.glb report.json
Env: R4_MIN_CM2 (20) · R4_RASTER (220) · R4_THICK_MM (4) · R4_SMOOTH (2.0)
     R4_BACKLIGHT_X (1.30) · R4_FOOTPRINT_LO (0.75) · R4_FOOTPRINT_HI (1.35)
"""
import json
import os
import sys

import bmesh
import bpy
import mathutils
import numpy as np
from scipy import ndimage

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST, REPORT = argv[0], argv[1], argv[2]
MIN_CM2 = float(os.environ.get("R4_MIN_CM2", "20"))
RASTER = int(os.environ.get("R4_RASTER", "220"))
THICK = float(os.environ.get("R4_THICK_MM", "4")) / 1000.0
SMOOTH = float(os.environ.get("R4_SMOOTH", "2.0"))
BACKLIGHT_X = float(os.environ.get("R4_BACKLIGHT_X", "1.30"))
LO = float(os.environ.get("R4_FOOTPRINT_LO", "0.75"))
HI = float(os.environ.get("R4_FOOTPRINT_HI", "1.35"))

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=SRC)
src = next((o for o in sc.objects if o.name == "glass"), None)
if src is None:
    raise SystemExit("R4_FAIL: no `glass` object")
glass_mat = src.data.materials[0] if src.data.materials else None

bm = bmesh.new()
bm.from_mesh(src.data)
bm.transform(src.matrix_world)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
bm.faces.ensure_lookup_table()
seen, comps = set(), []
for f in bm.faces:
    if f.index in seen:
        continue
    st, fs = [f], []
    seen.add(f.index)
    while st:
        c = st.pop()
        fs.append(c)
        for e in c.edges:
            for nf in e.link_faces:
                if nf.index not in seen:
                    seen.add(nf.index)
                    st.append(nf)
    area = sum(x.calc_area() for x in fs)
    tris = []
    for x in fs:
        vs = [v.co for v in x.verts]
        for t in range(1, len(vs) - 1):
            tris.append([[vs[0][i] for i in range(3)], [vs[t][i] for i in range(3)],
                         [vs[t + 1][i] for i in range(3)]])
    n = mathutils.Vector((0, 0, 0))
    for x in fs:
        n += x.normal * x.calc_area()
    if n.length < 1e-12:
        continue
    n.normalize()
    T = np.array(tris, float)
    comps.append({"area": area, "tris": T, "pts": T.reshape(-1, 3),
                  "n": np.array([n[0], n[1], n[2]])})
bm.free()

tot = sum(c["area"] for c in comps)
kept = [c for c in comps if c["area"] * 1e4 >= MIN_CM2]
drop = tot - sum(c["area"] for c in kept)
print(f"R4_COMPS {len(comps)} -> {len(kept)} kept at >={MIN_CM2} cm2; "
      f"{len(comps)-len(kept)} debris = {drop*1e4:.1f} cm2 ({100*drop/tot:.2f}%)")


def classify(c):
    ctr = c["pts"].mean(0)
    n = np.abs(c["n"])
    if ctr[0] > BACKLIGHT_X:
        return "Glass_Rear"
    if n[1] >= max(n[0], n[2]):
        return "Glass_Side_L" if ctr[1] > 0 else "Glass_Side_R"
    return "Glass_Windscreen" if ctr[0] < 0 else "Glass_Rear"


groups = {}
for c in kept:
    groups.setdefault(classify(c), []).append(c)
for k in groups:
    groups[k].sort(key=lambda c: -c["area"])
    print(f"R4_WINDOW {k:<18} {len(groups[k]):>2} skins, outer={groups[k][0]['area']*1e4:>8.1f}cm2, "
          f"total={sum(x['area'] for x in groups[k])*1e4:>8.1f}cm2")


def scan(g, tu, tv, nu, nv):
    eps = 0.5 / max(nu, nv)
    for k in range(tu.shape[0]):
        a0, a1, a2 = tu[k]
        b0, b1, b2 = tv[k]
        la = max(0, int(np.floor(min(a0, a1, a2))))
        ha = min(nu - 1, int(np.ceil(max(a0, a1, a2))))
        lb = max(0, int(np.floor(min(b0, b1, b2))))
        hb = min(nv - 1, int(np.ceil(max(b0, b1, b2))))
        if la > ha or lb > hb:
            continue
        den = (b1 - b2) * (a0 - a2) + (a2 - a1) * (b0 - b2)
        gu, gv = np.meshgrid(np.arange(la, ha + 1), np.arange(lb, hb + 1), indexing="ij")
        if abs(den) < 1e-12:
            g[gu, gv] = True
            continue
        w0 = ((b1 - b2) * (gu - a2) + (a2 - a1) * (gv - b2)) / den
        w1 = ((b2 - b0) * (gu - a2) + (a0 - a2) * (gv - b2)) / den
        w2 = 1.0 - w0 - w1
        m = (w0 >= -eps) & (w1 >= -eps) & (w2 >= -eps)
        if m.any():
            g[gu[m], gv[m]] = True


built = []
for name, cs in sorted(groups.items(), key=lambda kv: -sum(c["area"] for c in kv[1])):
    outer = cs[0]
    P = np.vstack([c["pts"] for c in cs])
    ctr = P.mean(0)
    Q = P - ctr
    _, _, Vt = np.linalg.svd(Q, full_matrices=False)
    u, v, w = Vt[0], Vt[1], Vt[2]
    U, V, W = Q @ u, Q @ v, Q @ w
    A = np.column_stack([np.ones_like(U), U, V, U * U, U * V, V * V,
                         U ** 3, U * U * V, U * V * V, V ** 3])
    coef, *_ = np.linalg.lstsq(A, W, rcond=None)
    resid = float(np.sqrt(np.mean((A @ coef - W) ** 2)))
    umin, umax, vmin, vmax = U.min(), U.max(), V.min(), V.max()
    pad = 0.02 * max(umax - umin, vmax - vmin)
    umin, umax, vmin, vmax = umin - pad, umax + pad, vmin - pad, vmax + pad
    step = max(umax - umin, vmax - vmin) / RASTER
    nu = max(8, int(round((umax - umin) / step)) + 1)
    nv = max(8, int(round((vmax - vmin) / step)) + 1)
    grid = np.zeros((nu, nv), bool)
    T = np.vstack([c["tris"] for c in cs]) - ctr
    scan(grid, (T @ u - umin) / (umax - umin) * (nu - 1),
         (T @ v - vmin) / (vmax - vmin) * (nv - 1), nu, nv)
    raw = int(grid.sum())
    grid = ndimage.binary_fill_holes(ndimage.binary_closing(grid, np.ones((3, 3), bool)))
    sm = ndimage.binary_fill_holes(ndimage.gaussian_filter(grid.astype(float), SMOOTH) > 0.5)
    lab, nl = ndimage.label(sm)
    if nl > 1:
        sz = ndimage.sum(sm, lab, range(1, nl + 1))
        sm = lab == (int(np.argmax(sz)) + 1)
    sm = ndimage.binary_fill_holes(sm)
    fin = int(sm.sum())
    ratio = fin / raw if raw else 0.0
    if not (LO <= ratio <= HI):
        print(f"R4_REFUSE {name}: footprint {fin} vs {raw} = {ratio:.3f}x outside {LO}-{HI}")
        built.append({"name": name, "REFUSED": True, "footprint_ratio": round(ratio, 3)})
        continue
    vin = np.zeros((nu + 1, nv + 1), bool)
    for dx in (0, 1):
        for dy in (0, 1):
            vin[dx:nu + dx, dy:nv + dy] |= sm
    idx = -np.ones((nu + 1, nv + 1), int)
    vs = []
    du = (umax - umin) / max(nu - 1, 1)
    dv = (vmax - vmin) / max(nv - 1, 1)
    for a in range(nu + 1):
        for b in range(nv + 1):
            if not vin[a, b]:
                continue
            uu = umin + (a - 0.5) * du
            vv = vmin + (b - 0.5) * dv
            ww = (coef[0] + coef[1] * uu + coef[2] * vv + coef[3] * uu * uu
                  + coef[4] * uu * vv + coef[5] * vv * vv + coef[6] * uu ** 3
                  + coef[7] * uu * uu * vv + coef[8] * uu * vv * vv + coef[9] * vv ** 3)
            idx[a, b] = len(vs)
            vs.append(ctr + uu * u + vv * v + ww * w)
    faces = [[idx[a, b], idx[a + 1, b], idx[a + 1, b + 1], idx[a, b + 1]]
             for a in range(nu) for b in range(nv)
             if sm[a, b] and min(idx[a, b], idx[a + 1, b], idx[a + 1, b + 1], idx[a, b + 1]) >= 0]
    if not faces:
        continue
    me = bpy.data.meshes.new(name)
    me.from_pydata([list(map(float, x)) for x in vs], [], faces)
    me.validate()
    sheet = sum(p.area for p in me.polygons)
    ob = bpy.data.objects.new(name, me)
    sc.collection.objects.link(ob)
    if glass_mat:
        ob.data.materials.append(glass_mat)
    b2 = bmesh.new()
    b2.from_mesh(me)
    bmesh.ops.recalc_face_normals(b2, faces=b2.faces)
    bmesh.ops.solidify(b2, geom=b2.faces[:] + b2.edges[:] + b2.verts[:], thickness=-THICK)
    bmesh.ops.recalc_face_normals(b2, faces=b2.faces)
    b2.to_mesh(me)
    b2.free()
    b3 = bmesh.new()
    b3.from_mesh(me)
    bmesh.ops.remove_doubles(b3, verts=b3.verts, dist=1e-6)
    bnd = sum(1 for e in b3.edges if len(e.link_faces) == 1)
    b3.free()
    built.append({"name": name, "faces": len(me.polygons), "sheet_cm2": round(sheet * 1e4, 1),
                  "source_outer_cm2": round(outer["area"] * 1e4, 1),
                  "source_class_cm2": round(sum(c["area"] for c in cs) * 1e4, 1),
                  "footprint_ratio": round(ratio, 3), "fit_rms_mm": round(resid * 1000, 2),
                  "boundary_edges": bnd, "skins_merged": len(cs)})
    print(f"R4_PANE {name:<18} faces={len(me.polygons):>6d} sheet={sheet*1e4:>8.1f}cm2 "
          f"src_class={sum(c['area'] for c in cs)*1e4:>8.1f}cm2 fp={ratio:.3f} "
          f"rms={resid*1000:>6.2f}mm bnd={bnd}")

bpy.data.objects.remove(src, do_unlink=True)
bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_yup=True)
print("R4_EXPORTED", DST)
json.dump({"repair": "R4 glazing rebuild", "in": SRC, "out": DST,
           "components_total": len(comps), "components_kept": len(kept),
           "debris_cm2": round(drop * 1e4, 1), "panes": built},
          open(REPORT, "w"), indent=2)
print("R4_DONE")
