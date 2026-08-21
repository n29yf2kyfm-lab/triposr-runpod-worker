#!/usr/bin/env python3
"""glass_rebuild.py — rebuild vehicle glazing as ONE CLEAN PANE PER WINDOW.

WHY CONSTRUCT RATHER THAN PATCH. The Golf's glazing measured 71 components and
108 holes on the windscreen alone, and the instinct is to fill the holes. That
reads the defect wrong. Locating every substantial component showed the panes
are DOUBLE-SKINNED: the windscreen's 6,963 cm2 piece faces up-and-forward
(n_z +0.87) while its 965 and 669 cm2 pieces face down-and-back (n_z -0.85).
Those are the inner surface of the same glass, never stitched to the outer, and
each skin is an open sheet with its own ragged boundary. Patching would weld two
surfaces that were never one.

So: take every skin of a window as a POINT CLOUD, fit one surface through it,
and emit fresh regular geometry. One component with one boundary loop and zero
holes then holds BY CONSTRUCTION rather than by repair — the same reasoning that
made glass_panes.py emit panes instead of smoothing blob glass.

A FIRST ATTEMPT MERGED SKINS BY PARALLEL-NORMAL + BBOX-OVERLAP AND FAILED, in a
way worth recording because both faults were invisible until the numbers were
read: the 3D bounding boxes of the windscreen and the side glass overlap at the
A-pillar, so the union-find swallowed nine skins into one "window" and fitted a
quadric across them at 22.78 mm rms; and stamping source vertices into the grid
then dilating inflated the windscreen from 9,894 cm2 of source skin to 18,622 cm2
of emitted pane. Neither shows up as an error.

So this version does not merge across nodes at all. Each ORIGINAL glazing node is
already semantically named, and within it the LARGEST component is the outer skin
— identified by area, then reported alongside everything discarded so the choice
is auditable. The inner skins are dropped rather than fitted, because solidify
regenerates an inner surface exactly THICK behind the outer one. And the footprint
comes from exact triangle scan-conversion, not from stamped points, so the emitted
pane cannot be larger than the glass it was fitted to. A guard refuses any pane
whose area departs from its source skin by more than AREA_TOL.

The pane is solidified, so the result is watertight: 1 component, 0 boundary
edges, 0 holes — strictly stronger than a clean open sheet, and it gives the
real edge thickness the production brief asks for.

Run: blender -b --python glass_rebuild.py -- in.glb out.glb [report.json]
Env: GR_MIN_CM2 (5) · GR_RASTER (220) · GR_THICK_MM (4) · GR_DOT (0.85)
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
SRC, DST = argv[0], argv[1]
REPORT = argv[2] if len(argv) > 2 else None
MIN_CM2 = float(os.environ.get("GR_MIN_CM2", "5"))
RASTER = int(os.environ.get("GR_RASTER", "220"))
THICK = float(os.environ.get("GR_THICK_MM", "4")) / 1000.0
DOT = float(os.environ.get("GR_DOT", "0.85"))
AREA_TOL = float(os.environ.get("GR_AREA_TOL", "0.25"))   # emitted vs source skin

# Body_Glass_Reverted is glazing-NAMED but carries carpaint on 714 fragments.
# That is a body-coloured-glazing question, not a pane-integrity one, and
# merging it into a pane would silently convert a documented defect into glass.
EXCLUDE = {"body_glass_reverted"}

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=SRC)

glazing = [o for o in sc.objects
           if o.type == "MESH" and "glass" in o.name.lower()
           and o.name.lower() not in EXCLUDE]
if not glazing:
    raise SystemExit("GR_FAIL: no glazing nodes")
glass_mat = next((o.data.materials[0] for o in glazing if o.data.materials), None)
print("GR_NODES:", sorted(o.name for o in glazing),
      "material:", glass_mat.name if glass_mat else None)


def components(obj):
    """World-space components, welded first — a GLB stores split vertices and a
    naive count reads one sheet as thousands of pieces."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.faces.ensure_lookup_table()
    seen, out = set(), []
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
        # keep TRIANGLES, not just points: the footprint must come from scan
        # conversion. Stamping points and dilating to close the gaps between
        # them is what inflated the windscreen 9,894 -> 18,622 cm2.
        tris = []
        for x in fs:
            vs = [v.co for v in x.verts]
            for t in range(1, len(vs) - 1):          # fan-triangulate any n-gon
                tris.append([[vs[0][i] for i in range(3)],
                             [vs[t][i] for i in range(3)],
                             [vs[t + 1][i] for i in range(3)]])
        tris = np.array(tris, dtype=float)
        pts = tris.reshape(-1, 3)
        n = mathutils.Vector((0, 0, 0))
        for x in fs:
            n += x.normal * x.calc_area()
        if n.length < 1e-12:
            continue
        n.normalize()
        out.append({"area": area, "pts": pts, "tris": tris,
                    "n": np.array([n[0], n[1], n[2]]),
                    "lo": pts.min(0), "hi": pts.max(0), "src": obj.name})
    bm.free()
    return out


comps = []
for o in glazing:
    comps += components(o)
tot_area = sum(c["area"] for c in comps)
kept = [c for c in comps if c["area"] * 1e4 >= MIN_CM2]
drop_area = tot_area - sum(c["area"] for c in kept)
print(f"GR_COMPS: {len(comps)} total -> {len(kept)} kept at >={MIN_CM2} cm2; "
      f"{len(comps)-len(kept)} slivers dropped = {100*drop_area/tot_area:.3f}% of glazing area")


# one window per ORIGINAL node; within it, the outer skin is the largest piece
windows = {}
for c in kept:
    windows.setdefault(c["src"], []).append(c)
for k in windows:
    windows[k].sort(key=lambda c: -c["area"])
    outer = windows[k][0]
    rest = windows[k][1:]
    shed = ", ".join("%.0f" % (c["area"] * 1e4) for c in rest[:4])
    print(f"GR_WINDOW {k:<20} outer={outer['area']*1e4:>8.1f}cm2  "
          f"discarded {len(rest)} skin(s) totalling {sum(c['area'] for c in rest)*1e4:>8.1f}cm2 "
          f"[{shed}]")
print(f"GR_WINDOWS: {len(kept)} components -> {len(windows)} windows (one per source node)")


def build_pane(cs, name):
    """Fit one surface through every skin of a window and emit fresh geometry."""
    P = np.vstack([c["pts"] for c in cs])
    ctr = P.mean(0)
    Q = P - ctr
    # PCA: the LAST axis is the thin one, i.e. the pane's own normal
    _, _, Vt = np.linalg.svd(Q, full_matrices=False)
    u, v, w = Vt[0], Vt[1], Vt[2]
    U, V, W = Q @ u, Q @ v, Q @ w
    # quadratic w(u,v) so a raked, curved screen is followed rather than flattened
    A = np.column_stack([np.ones_like(U), U, V, U * U, U * V, V * V])
    coef, *_ = np.linalg.lstsq(A, W, rcond=None)
    resid = float(np.sqrt(np.mean((A @ coef - W) ** 2)))

    umin, umax, vmin, vmax = U.min(), U.max(), V.min(), V.max()
    pad = 0.02 * max(umax - umin, vmax - vmin)
    umin, umax, vmin, vmax = umin - pad, umax + pad, vmin - pad, vmax + pad
    span = max(umax - umin, vmax - vmin)
    step = span / RASTER
    nu = max(8, int(round((umax - umin) / step)) + 1)
    nv = max(8, int(round((vmax - vmin) / step)) + 1)

    # EXACT TRIANGLE SCAN CONVERSION. Every source triangle is projected to
    # (u,v) and its covered cells marked by barycentric test. This is the whole
    # difference from the failed first attempt: a stamped point cloud has gaps
    # between samples that must be dilated shut, and the dilation grows the
    # OUTLINE too. Scan conversion fills the interior without touching the edge,
    # so the emitted pane cannot be larger than the glass it was fitted to.
    grid = np.zeros((nu, nv), bool)
    T = np.vstack([c["tris"] for c in cs]) - ctr
    tu = (T @ u - umin) / (umax - umin) * (nu - 1)
    tv = (T @ v - vmin) / (vmax - vmin) * (nv - 1)
    for k in range(tu.shape[0]):
        a0, a1, a2 = tu[k]
        b0, b1, b2 = tv[k]
        lo_a = max(0, int(np.floor(min(a0, a1, a2))))
        hi_a = min(nu - 1, int(np.ceil(max(a0, a1, a2))))
        lo_b = max(0, int(np.floor(min(b0, b1, b2))))
        hi_b = min(nv - 1, int(np.ceil(max(b0, b1, b2))))
        if lo_a > hi_a or lo_b > hi_b:
            continue
        den = (b1 - b2) * (a0 - a2) + (a2 - a1) * (b0 - b2)
        gu, gv = np.meshgrid(np.arange(lo_a, hi_a + 1),
                             np.arange(lo_b, hi_b + 1), indexing="ij")
        if abs(den) < 1e-12:
            grid[gu, gv] = True          # degenerate sliver: mark its bbox cells
            continue
        w0 = ((b1 - b2) * (gu - a2) + (a2 - a1) * (gv - b2)) / den
        w1 = ((b2 - b0) * (gu - a2) + (a0 - a2) * (gv - b2)) / den
        w2 = 1.0 - w0 - w1
        m = (w0 >= -0.5 / max(nu, nv)) & (w1 >= -0.5 / max(nu, nv)) & (w2 >= -0.5 / max(nu, nv))
        if m.any():
            grid[gu[m], gv[m]] = True
    cells_raw = int(grid.sum())
    # close only pinhole-scale gaps left by tessellation, never a real aperture
    grid = ndimage.binary_closing(grid, np.ones((3, 3), bool))
    # THE HOLE KILL: every enclosed void becomes solid, so the emitted pane
    # cannot inherit a single perforation from the blob it was fitted to
    grid = ndimage.binary_fill_holes(grid)
    # keep only the largest island: a detached fleck must not become a pane
    lab, nlab = ndimage.label(grid)
    if nlab > 1:
        sizes = ndimage.sum(grid, lab, range(1, nlab + 1))
        grid = lab == (int(np.argmax(sizes)) + 1)
    # smooth the outline, then re-fill (thresholding can reopen a pinhole)
    sm = ndimage.gaussian_filter(grid.astype(float), 1.2) > 0.5
    sm = ndimage.binary_fill_holes(sm)
    if not sm.any():
        return None
    cells_final = int(sm.sum())

    # vertices where all four incident cells are inside -> quad, so the mesh is
    # regular and its boundary is a single loop
    vin = np.zeros((nu + 1, nv + 1), bool)
    vin[:-1, :-1] |= sm
    vin[1:, :-1] |= sm
    vin[:-1, 1:] |= sm
    vin[1:, 1:] |= sm
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
            ww = (coef[0] + coef[1] * uu + coef[2] * vv
                  + coef[3] * uu * uu + coef[4] * uu * vv + coef[5] * vv * vv)
            idx[a, b] = len(vs)
            vs.append(ctr + uu * u + vv * v + ww * w)
    faces = []
    for a in range(nu):
        for b in range(nv):
            if not sm[a, b]:
                continue
            q = [idx[a, b], idx[a + 1, b], idx[a + 1, b + 1], idx[a, b + 1]]
            if min(q) >= 0:
                faces.append(q)
    if not faces:
        return None

    me = bpy.data.meshes.new(name)
    me.from_pydata([list(map(float, x)) for x in vs], [], faces)
    me.validate()
    # THE GUARD. Compare the emitted single-sided sheet against the SOURCE OUTER
    # SKIN before anything is kept. Run 1 shipped a windscreen at 188% of its
    # source and completed rc=0; a number that wrong must refuse, not warn.
    sheet = sum(p.area for p in me.polygons)
    ref = cs[0]["area"]
    ratio = sheet / ref if ref > 1e-12 else 0.0
    if not (1.0 - AREA_TOL) <= ratio <= (1.0 + AREA_TOL):
        bpy.data.meshes.remove(me)
        print(f"GR_REFUSE {name}: emitted {sheet*1e4:.1f} cm2 vs source outer skin "
              f"{ref*1e4:.1f} cm2 = {ratio:.3f}x, outside {1-AREA_TOL:.2f}-{1+AREA_TOL:.2f}")
        return {"name": name, "REFUSED": True, "ratio": round(ratio, 3),
                "emitted_cm2": round(sheet * 1e4, 1), "source_cm2": round(ref * 1e4, 1),
                "fit_rms_mm": round(resid * 1000, 2)}
    ob = bpy.data.objects.new(name, me)
    sc.collection.objects.link(ob)
    if glass_mat:
        ob.data.materials.append(glass_mat)
    # solidify -> watertight pane with real edge thickness
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    r = bmesh.ops.solidify(bm, geom=bm.faces[:] + bm.edges[:] + bm.verts[:], thickness=-THICK)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bnd = 0
    bm2 = bmesh.new()
    bm2.from_mesh(me)
    bmesh.ops.remove_doubles(bm2, verts=bm2.verts, dist=1e-6)
    bnd = sum(1 for e in bm2.edges if len(e.link_faces) == 1)
    bm2.free()
    bm.free()
    area = sum(p.area for p in me.polygons)
    return {"name": name, "faces": len(me.polygons), "verts": len(me.vertices),
            "sheet_cm2": round(sheet * 1e4, 1), "source_cm2": round(ref * 1e4, 1),
            "area_ratio": round(ratio, 3), "solid_area_cm2": round(area * 1e4, 1),
            "fit_rms_mm": round(resid * 1000, 2),
            "boundary_edges_after_solidify": bnd,
            "grid": [nu, nv], "cells_scanconv": cells_raw, "cells_final": cells_final,
            "source_nodes": sorted({c["src"] for c in cs})}


# windows are now one-per-node, so the SOURCE NODE NAME is the correct name.
# Deriving it from geometry instead produced Glass_Backlight_2_2_2_2_2 — a
# generated name is only worth having when there is nothing authoritative.
order = sorted(windows.items(), key=lambda kv: -sum(c["area"] for c in kv[1]))
built = []
for name, cs in order:
    r = build_pane([cs[0]], name)
    if r:
        built.append(r)
        if r.get("REFUSED"):
            continue
        print(f"GR_PANE {r['name']:<20} "
              f"sheet={r['sheet_cm2']:>8.1f}cm2 src={r['source_cm2']:>8.1f}cm2 "
              f"ratio={r['area_ratio']:.3f} fit_rms={r['fit_rms_mm']:>6.2f}mm "
              f"faces={r['faces']:>6d} bnd_edges={r['boundary_edges_after_solidify']}")

for o in glazing:
    bpy.data.objects.remove(o, do_unlink=True)

bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB",
                          export_apply=False, export_yup=True)
print("GR_EXPORTED", DST)
if REPORT:
    json.dump({"source": SRC, "output": DST, "panes": built,
               "windows": len(windows), "components_kept": len(kept),
               "components_total": len(comps),
               "sliver_area_pct_dropped": round(100 * drop_area / tot_area, 3),
               "thickness_mm": THICK * 1000, "raster": RASTER},
              open(REPORT, "w"), indent=2)
print("GR_DONE")
