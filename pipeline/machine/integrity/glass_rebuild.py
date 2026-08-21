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
GROW = int(os.environ.get("GR_GROW", "0"))       # 0 = aperture OFF (see below)
SMOOTH = float(os.environ.get("GR_SMOOTH", "3.0"))  # outline gaussian, in cells
TUCK = int(os.environ.get("GR_TUCK", "4"))       # cells tucked under the body edge
BAND = float(os.environ.get("GR_BAND", "0.12"))  # body within this of the pane occludes
SELFTEST = int(os.environ.get("GR_SELFTEST_DILATE", "0"))  # inject inflation
FLECK = float(os.environ.get("GR_FLECK_CM2", "5"))   # strip debris below this

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


# BODY OCCLUDERS. The pane outline must come from the window APERTURE — the
# hole in the body — not from the torn edge of the glass that was found in it.
# Body_Glass_Reverted is excluded here as well as from the glazing: it is 714
# carpaint fragments sitting IN the openings, and counting it as body would
# punch the aperture full of holes.
occ = []
gset = {o.name for o in glazing} | {"Body_Glass_Reverted"}
for o in sc.objects:
    if o.type != "MESH" or o.name in gset:
        continue
    me = o.to_mesh()
    M = np.array(o.matrix_world.to_4x4())
    V = np.array([v.co[:] for v in me.vertices], dtype=float)
    if len(V):
        V = V @ M[:3, :3].T + M[:3, 3]
        for poly in me.polygons:
            vi = list(poly.vertices)
            for t in range(1, len(vi) - 1):
                occ.append([V[vi[0]], V[vi[t]], V[vi[t + 1]]])
    o.to_mesh_clear()
OCC = np.array(occ, dtype=float) if occ else np.zeros((0, 3, 3))
print(f"GR_OCCLUDERS: {len(OCC)} body triangles")

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


def _scan(g, tu, tv, nu, nv):
    """Barycentric scan conversion. Fills a triangle's interior without moving
    its edge — the whole reason run 1's stamp-and-dilate inflated every pane."""
    eps = 0.5 / max(nu, nv)
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
            g[gu, gv] = True
            continue
        w0 = ((b1 - b2) * (gu - a2) + (a2 - a1) * (gv - b2)) / den
        w1 = ((b2 - b0) * (gu - a2) + (a0 - a2) * (gv - b2)) / den
        w2 = 1.0 - w0 - w1
        m = (w0 >= -eps) & (w1 >= -eps) & (w2 >= -eps)
        if m.any():
            g[gu[m], gv[m]] = True


def build_pane(cs, name):
    """Fit one surface through every skin of a window and emit fresh geometry."""
    P = np.vstack([c["pts"] for c in cs])
    ctr = P.mean(0)
    Q = P - ctr
    # PCA: the LAST axis is the thin one, i.e. the pane's own normal
    _, _, Vt = np.linalg.svd(Q, full_matrices=False)
    u, v, w = Vt[0], Vt[1], Vt[2]
    U, V, W = Q @ u, Q @ v, Q @ w
    # CUBIC w(u,v). A quadratic could not follow Glass_Side_R's wrap: the true
    # 3D surface is more curved than its own graph, so the emitted pane came out
    # at 0.691x the source area and the guard refused it. Ten terms follow the
    # wrap and the area comes back.
    A = np.column_stack([np.ones_like(U), U, V, U * U, U * V, V * V,
                         U ** 3, U * U * V, U * V * V, V ** 3])
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
    def scanconv(T):
        g = np.zeros((nu, nv), bool)
        if not len(T):
            return g
        _scan(g, (T @ u - umin) / (umax - umin) * (nu - 1),
              (T @ v - vmin) / (vmax - vmin) * (nv - 1), nu, nv)
        return g

    grid = scanconv(np.vstack([c["tris"] for c in cs]) - ctr)
    cells_raw = int(grid.sum())
    grid = ndimage.binary_closing(grid, np.ones((3, 3), bool))
    grid = ndimage.binary_fill_holes(grid)
    lab, nlab = ndimage.label(grid)
    if nlab > 1:
        sizes = ndimage.sum(grid, lab, range(1, nlab + 1))
        grid = lab == (int(np.argmax(sizes)) + 1)

    # ---- APERTURE-DRIVEN OUTLINE (GROW>0) --------------------------------
    # DEFAULT OFF, and the reason is measured. Deriving the outline from the
    # body's opening is the right idea on a clean body; this body is fragment
    # soup (320,431 boundary edges across 40,398 open components), so "what the
    # body covers" near a window is not trustworthy geometry. A band sweep found
    # no value that works for all five: at 0.12 m the interior (seats, door
    # cards, ~10 cm inboard) projects onto the side windows and halved Side_L's
    # region 7,840 -> 4,146 cells; thinning to 0.02 m let the windscreen escape
    # its opening (1.068x -> 1.285x) while Glass_Quarter_L collapsed to 2 cells
    # because torn C-pillar geometry sits on top of it. Tuning further would be
    # turning knobs against noise. Kept, switchable, and documented for a body
    # that has been de-fragmented first.
    # The torn glass stops short of the opening in places and overshoots it in
    # others, so its own boundary is not the pane's shape. The BODY knows the
    # shape: the aperture is the part of this surface the body does NOT cover.
    # Grow the glass footprint outward, subtract everything the body occupies
    # near the pane, and the remaining island IS the opening.
    if GROW <= 0:
        sm = ndimage.binary_fill_holes(grid)
        # smooth the OUTLINE itself: the pane inherits the torn boundary of the
        # glass it was fitted to, and a gaussian on the stencil is what turns a
        # ragged edge into a pane edge. Re-fill after thresholding, which can
        # reopen a pinhole the fill had just closed.
        sm = ndimage.gaussian_filter(sm.astype(float), SMOOTH) > 0.5
        sm = ndimage.binary_fill_holes(sm)
        lab, nlab = ndimage.label(sm)
        if nlab > 1:
            sizes = ndimage.sum(sm, lab, range(1, nlab + 1))
            sm = lab == (int(np.argmax(sizes)) + 1)
        sm = ndimage.binary_fill_holes(sm)
        if not sm.any():
            return None
        cells_final = int(sm.sum())
        print(f"GR_OUTLINE {name:<20} glass_cells={int(grid.sum()):>6d} "
              f"final={cells_final:>6d} smooth={SMOOTH}")
        return _emit(cs, name, sm, nu, nv, umin, umax, vmin, vmax,
                     ctr, u, v, w, coef, resid, cells_raw, cells_final)

    Tb = OCC.reshape(-1, 3) - ctr
    wb = Tb @ w
    ub = (Tb @ u - umin) / (umax - umin) * (nu - 1)
    vb = (Tb @ v - vmin) / (vmax - vmin) * (nv - 1)
    near = ((np.abs(wb) < BAND).reshape(-1, 3).any(1)
            & ((ub > -2) & (ub < nu + 1)).reshape(-1, 3).any(1)
            & ((vb > -2) & (vb < nv + 1)).reshape(-1, 3).any(1))
    body = np.zeros((nu, nv), bool)
    if near.any():
        _scan(body, ub.reshape(-1, 3)[near], vb.reshape(-1, 3)[near], nu, nv)
    grown = ndimage.binary_dilation(grid, np.ones((3, 3), bool), iterations=GROW)
    free = grown & ~body
    lab, nlab = ndimage.label(free)
    if nlab:
        # the aperture is the free island the ORIGINAL glass sits in — not
        # merely the biggest one, which can be the cabin void behind the pane
        best, bs = None, -1
        for t in range(1, nlab + 1):
            isl = lab == t
            sc_ = int((isl & grid).sum())
            if sc_ > bs:
                best, bs = isl, sc_
        if best is not None and bs > 0:
            free = best
        else:
            free = grid
    else:
        free = grid
    free = ndimage.binary_fill_holes(free)
    # tuck the pane back UNDER the aperture edge so no gap shows at the seam
    sm = ndimage.binary_dilation(free, np.ones((3, 3), bool), iterations=TUCK)
    sm = ndimage.binary_fill_holes(sm)
    sm = ndimage.gaussian_filter(sm.astype(float), 1.2) > 0.5
    sm = ndimage.binary_fill_holes(sm)
    if not sm.any():
        return None
    cells_final = int(sm.sum())
    print(f"GR_APERTURE {name:<20} glass_cells={int(grid.sum()):>6d} "
          f"body_cells={int(body.sum()):>6d} aperture={int(free.sum()):>6d} "
          f"final={cells_final:>6d}")
    return _emit(cs, name, sm, nu, nv, umin, umax, vmin, vmax,
                 ctr, u, v, w, coef, resid, cells_raw, cells_final)

def _emit(cs, name, sm, nu, nv, umin, umax, vmin, vmax,
          ctr, u, v, w, coef, resid, cells_raw, cells_final):
    if SELFTEST:
        # negative control: inflate the stencil the way run 1 did, so the guard
        # is proven to fire rather than assumed to. A gate nobody tested is a
        # gate that does not exist.
        sm = ndimage.binary_dilation(sm, np.ones((3, 3), bool), iterations=SELFTEST)
        cells_final = int(sm.sum())
    """Emit the pane: regular grid over the stencil, evaluated on the fitted
    surface, then solidified. Split out so the aperture path and the
    outline-only path emit through EXACTLY the same code."""
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
                  + coef[3] * uu * uu + coef[4] * uu * vv + coef[5] * vv * vv
                  + coef[6] * uu ** 3 + coef[7] * uu * uu * vv
                  + coef[8] * uu * vv * vv + coef[9] * vv ** 3)
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
    area_ratio = sheet / ref if ref > 1e-12 else 0.0
    # GUARD ON FOOTPRINT, NOT ON SURFACE AREA. The first guard compared the
    # emitted pane's 3D area against the source skin's and refused Glass_Side_R
    # at 0.692x. Rendering both side-on showed the pane covers the SAME opening
    # with the pinholes gone — nothing was missing. A crinkled torn sheet simply
    # carries more surface area than a smooth pane over the same hole, so that
    # comparison punishes the repair for having worked. Footprint cells are
    # measured in one shared (u,v) grid and are the like-for-like quantity; they
    # still catch run 1, whose stencil ballooned ~2.7x under stamp-and-dilate.
    ratio = cells_final / cells_raw if cells_raw else 0.0
    # The band is deliberately ASYMMETRIC now. Filling the aperture SHOULD make
    # a pane bigger than the torn glass it replaced — that is the repair. What
    # must never happen is losing glass (< LO, the Side_R failure) or escaping
    # the opening and paving over the body (> HI).
    # HI was 2.0 and the negative control showed that is too loose: injected
    # inflations of 1.49x-1.93x sailed through and only 2.04x was caught. Real
    # repairs land at 1.00-1.08, so 1.35 leaves headroom and still refuses every
    # injected case. The control is what set this number, not judgement.
    LO, HI = 1.0 - AREA_TOL, float(os.environ.get("GR_AREA_HI", "1.35"))
    if not LO <= ratio <= HI:
        bpy.data.meshes.remove(me)
        print(f"GR_REFUSE {name}: footprint {cells_final} cells vs source "
              f"{cells_raw} = {ratio:.3f}x, outside {LO:.2f}-{HI:.2f}")
        return {"name": name, "REFUSED": True, "footprint_ratio": round(ratio, 3),
                "cells_final": cells_final, "cells_scanconv": cells_raw,
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
            "footprint_ratio": round(ratio, 3),
            "surface_area_ratio": round(area_ratio, 3),
            "solid_area_cm2": round(area * 1e4, 1),
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
              f"fp={r['footprint_ratio']:.3f} area={r['surface_area_ratio']:.3f} "
              f"fit_rms={r['fit_rms_mm']:>6.2f}mm "
              f"faces={r['faces']:>6d} bnd_edges={r['boundary_edges_after_solidify']}")

for o in glazing:
    bpy.data.objects.remove(o, do_unlink=True)

# Body_Glass_Reverted: 714 components of CARPAINT sitting in the window
# openings. Rendered in isolation it is torn fringe tracing the aperture edges
# — slivers and flecks, no coherent surface — and with clean panes now in those
# openings it sits right on the seam. Only the unambiguous flecks are stripped:
# anything above FLECK_CM2 could be real window surround and removing it is the
# owner's call, not a repair. Deliberately conservative.
rev = bpy.data.objects.get("Body_Glass_Reverted")
if rev and FLECK > 0:
    bm = bmesh.new()
    bm.from_mesh(rev.data)
    bm.faces.ensure_lookup_table()
    seen, kill, ncomp, nkill, akill = set(), [], 0, 0, 0.0
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
        ncomp += 1
        a = sum(x.calc_area() for x in fs)
        if a * 1e4 < FLECK:
            kill += fs
            nkill += 1
            akill += a
    if kill:
        bmesh.ops.delete(bm, geom=kill, context="FACES")
    bm.to_mesh(rev.data)
    bm.free()
    print(f"GR_FLECKS Body_Glass_Reverted: {ncomp} components -> removed {nkill} "
          f"below {FLECK} cm2 ({akill*1e4:.1f} cm2), {ncomp-nkill} kept")

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
