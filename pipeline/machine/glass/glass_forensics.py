#!/usr/bin/env python3
"""glass_forensics.py — measure the GLAZING of a labelled car GLB before touching it.

Written for Gate "glass" on car_rebound.glb (2026-08-21). It answers, with numbers,
the four questions the gate brief asks and that no render can answer honestly
(CLAUDE.md: render/handler.py force-writes transmission=1.0 onto any material whose
NAME matches /glass|window|screen/..., so a production sheet of a car whose nodes are
called Glass_* is worthless as glazing evidence):

  1 SKINS / THICKNESS   is each pane a single zero-thickness sheet or a real solid?
  2 WINDING             does each skin face the way a viewer needs it to?  The glass
                        material here is doubleSided:false, so an inverted skin is
                        BACKFACE-CULLED in three.js / model-viewer — the exact client
                        the resolver hands desktopGlbUrl to.  Cycles ignores
                        doubleSided, so NO Blender render can see this defect.
  3 SPILL               glazing area sitting on roof / cowl / pillar rather than in an
                        aperture.
  4 SEPARABILITY        can the side band be cut into per-door panes, and what is the
                        real overlap between its components?

DESIGN RULE (CLAUDE.md, the white-dot saga): every measurement here must be able to
come back the other way.  Winding is measured by RAY CASTING from outside the car —
the same operation the renderer performs — not by reading the mean face normal, which
cannot distinguish "inverted single skin" from "double skin with unequal areas".
--selftest injects a known-inverted copy and a known-good control and asserts the
probe separates them; a probe that cannot fail is not evidence.

Usage:
  glass_forensics.py <car.glb> [--json out.json] [--selftest]
"""
import argparse
import json
import sys

import numpy as np
import trimesh

GLASS_NODES = ("Glass_Windscreen", "Glass_Rear", "Glass_Side_L", "Glass_Side_R")


def world_mesh(sc, name):
    m = sc.geometry[name].copy()
    T = sc.graph.get(name)[0]
    m.apply_transform(T)
    return m


def cabin_centre(sc, y_lo=None):
    """A single point inside the cabin, used as the 'inside' reference for outwardness.

    Uses the INTERIOR node's vertices above the glazing's lower edge when present (that
    is the cabin volume by construction); falls back to the glazing centroid.
    """
    gl = [n for n in GLASS_NODES if n in sc.geometry]
    gv = np.vstack([world_mesh(sc, n).vertices for n in gl]) if gl else None
    if y_lo is None and gv is not None:
        y_lo = float(np.percentile(gv[:, 1], 5))
    if "Interior" in sc.geometry:
        v = world_mesh(sc, "Interior").vertices
        v = v[v[:, 1] > y_lo]
        if len(v) > 100:
            return np.median(v, axis=0)
    return np.median(gv, axis=0)


def outwardness(mesh, axis_fn):
    """Per-face signed cosine between the face normal and the outward direction from a
    single point INSIDE the cabin.  +ve = faces away from the car, -ve = into it.

    CORRECTION 2026-08-21: v1 used a radial with the X component ZEROED (distance from
    the cabin's length axis).  That is fine for side glazing and MEANINGLESS for the
    windscreen and rear screen, whose outward direction is mostly +/-X: it scored the
    windscreen 0.39 outward / 0.02 inward with 59% of its area "edge-on", and the rear
    screen 0.48/0.51, i.e. no signal at all.  A full 3-D radial from the cabin centre
    classifies all four panes.  This measure ORGANISES skins; the ray test decides
    winding.
    """
    c = mesh.triangles_center
    r = c - axis_fn
    n = np.linalg.norm(r, axis=1)
    keep = n > 1e-9
    r[keep] /= n[keep, None]
    return (mesh.face_normals * r).sum(1)


def ray_winding(scene_mesh, glass_masks, n_dirs=24, res=200, seed=0):
    """THE decisive winding test: shoot rays at the car from outside and ask, at the
    FIRST FACE OF THE WHOLE CAR each ray hits, whether that face points back at the
    camera.  Returns per-node (front_hits, back_hits).

    CORRECTION 2026-08-21 (my own v1 was confounded and its selftest could not fail):
    v1 took the first GLAZING hit, not the first hit on the car.  A ray entering from
    the rear passes through the rear screen, crosses the cabin and strikes the
    windscreen's BACK face -- a legitimate back hit that is not a defect at all.  That
    put every node near back_frac 0.5 and made the injected-inversion control move only
    0.46 -> 0.54, i.e. the control could not separate a good pane from an inverted one.
    Counting only what the CAMERA ACTUALLY SEES (first surface along the ray) is the
    operation a rasteriser performs, and a back-facing first hit is exactly the pixel a
    client honouring doubleSided:false drops.
    """
    rng = np.random.default_rng(seed)
    b = scene_mesh.bounds
    ctr = b.mean(0)
    rad = float(np.linalg.norm(b[1] - b[0]))
    # Fibonacci directions on the sphere, biased away from straight up/down so the
    # rays look at the car the way a customer orbits it.
    i = np.arange(n_dirs) + 0.5
    phi = np.arccos(np.clip(1 - 2 * i / n_dirs, -1, 1)) * 0.55 + 0.5 * np.pi * 0.45
    theta = np.pi * (1 + 5 ** 0.5) * i
    dirs = np.c_[np.sin(phi) * np.cos(theta), np.cos(phi), np.sin(phi) * np.sin(theta)]

    try:                                   # embreex is present in this container and is
        from trimesh.ray import ray_pyembree   # ~100x the pure-python intersector
        inter = ray_pyembree.RayMeshIntersector(scene_mesh)
    except Exception:
        inter = trimesh.ray.ray_triangle.RayMeshIntersector(scene_mesh)
    out = {k: [0, 0] for k in glass_masks}
    for d in dirs:
        d = d / np.linalg.norm(d)
        # orthonormal frame for the ray grid
        up = np.array([0, 1, 0.0])
        if abs(d @ up) > 0.95:
            up = np.array([1, 0, 0.0])
        e1 = np.cross(d, up); e1 /= np.linalg.norm(e1)
        e2 = np.cross(d, e1)
        g = np.linspace(-0.55 * rad, 0.55 * rad, res)
        gu, gv = np.meshgrid(g, g)
        org = ctr + np.outer(gu.ravel(), e1) + np.outer(gv.ravel(), e2) - d * rad
        dd = np.tile(d, (len(org), 1))
        loc, ray_i, tri = inter.intersects_location(org, dd, multiple_hits=True)
        if not len(tri):
            continue
        t = ((loc - org[ray_i]) * dd[ray_i]).sum(1)
        order = np.lexsort((t, ray_i))
        ray_i, tri = ray_i[order], tri[order]
        # FIRST hit on the car per ray -- what the camera sees
        _, uidx = np.unique(ray_i, return_index=True)
        first_tri = tri[uidx]
        dot = scene_mesh.face_normals[first_tri] @ d
        for name, mask in glass_masks.items():
            isg = mask[first_tri]
            if not isg.any():
                continue
            out[name][0] += int((dot[isg] < 0).sum())   # front-facing: drawn
            out[name][1] += int((dot[isg] > 0).sum())   # back-facing: culled by the client
    return out


def skin_analysis(node_mesh, axis_fn, min_area_frac=0.005):
    """Split a glazing node into components, label each OUTER/INNER by outwardness,
    and measure the gap between paired skins (= pane thickness, if any)."""
    comps = sorted(node_mesh.split(only_watertight=False), key=lambda c: -c.area)
    total = node_mesh.area
    rows = []
    for c in comps:
        if c.area < min_area_frac * total:
            continue
        ow = outwardness(c, axis_fn)
        a = c.area_faces
        outf = float(a[ow > 0].sum() / a.sum())
        innf = float(a[ow < 0].sum() / a.sum())
        rows.append({
            "faces": int(len(c.faces)), "area": float(c.area),
            "area_frac": float(c.area / total),
            "bounds": np.round(c.bounds, 4).tolist(),
            "outward_area_frac": round(outf, 4), "inward_area_frac": round(innf, 4),
            "side": "outer" if outf > innf else "inner",
            "_mesh": c,
        })
    # pair each inner skin with the nearest outer skin and measure the gap
    outers = [r for r in rows if r["side"] == "outer"]
    for r in rows:
        r["gap_mm"] = None
        if r["side"] == "inner" and outers:
            best = max(outers, key=lambda o: _bbox_overlap(o["bounds"], r["bounds"]))
            q = trimesh.proximity.ProximityQuery(best["_mesh"])
            d = np.abs(q.signed_distance(r["_mesh"].triangles_center[::max(1, len(r["_mesh"].faces) // 2000)]))
            r["gap_mm"] = [round(float(np.percentile(d, p)) * 1000, 2) for p in (5, 50, 95)]
    for r in rows:
        r.pop("_mesh", None)
    return rows, len(comps)


def _bbox_overlap(a, b):
    a, b = np.array(a), np.array(b)
    lo = np.maximum(a[0], b[0]); hi = np.minimum(a[1], b[1])
    return float(np.prod(np.clip(hi - lo, 0, None)))


def roof_spill(node_mesh, car_bounds, x_ws_back, x_rear_front, n_up=0.7):
    """hybrid_transfer._roofish, ported: in the cabin MID-BAND there is no raked
    screen, so a strongly up-facing glazing face there is ROOF SKIN by construction.
    Returns (area, area_frac, face_index)."""
    c = mesh_centers = node_mesh.triangles_center
    n = node_mesh.face_normals
    mid = (c[:, 0] > x_ws_back) & (c[:, 0] < x_rear_front)
    up = np.abs(n[:, 1]) > n_up
    m = mid & up
    a = node_mesh.area_faces
    return float(a[m].sum()), float(a[m].sum() / a.sum()), np.where(m)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("--json")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--rays", type=int, default=16)
    ap.add_argument("--res", type=int, default=160)
    a = ap.parse_args()

    sc = trimesh.load(a.glb, force="scene", process=False)
    axis_fn = cabin_centre(sc)
    print("cabin centre reference:", np.round(axis_fn, 4).tolist())
    names = [n for n in GLASS_NODES if n in sc.geometry]
    rep = {"file": a.glb, "nodes": {}}

    # ---- 1/3/4 per-node geometry ----------------------------------------
    tot_area = sum(float(world_mesh(sc, n).area) for n in sc.geometry)
    gl_area = 0.0
    for n in names:
        m = world_mesh(sc, n)
        gl_area += float(m.area)
        rows, ncomp = skin_analysis(m, axis_fn)
        rep["nodes"][n] = {
            "faces": int(len(m.faces)), "verts": int(len(m.vertices)),
            "area": float(m.area), "components": ncomp,
            "watertight": bool(m.is_watertight),
            "boundary_edges": int((np.unique(m.edges_sorted, axis=0, return_counts=True)[1] == 1).sum()),
            "skins": rows,
        }
    rep["glazing_area"] = gl_area
    rep["scene_area"] = tot_area
    rep["glazing_area_pct"] = round(100 * gl_area / tot_area, 3)

    # ---- 2 winding by ray cast ------------------------------------------
    parts, masks, off = [], {}, 0
    for nm in sc.geometry:
        m = world_mesh(sc, nm)
        parts.append(m)
    big = trimesh.util.concatenate(parts)
    off = 0
    for nm, m in zip(sc.geometry, parts):
        k = np.zeros(len(big.faces), dtype=bool)
        k[off:off + len(m.faces)] = True
        if nm in names or nm in ("Body_Shell",):
            masks[nm] = k
        off += len(m.faces)
    w = ray_winding(big, masks, n_dirs=a.rays, res=a.res)
    for k, (f, b) in w.items():
        tot = f + b
        rep.setdefault("winding", {})[k] = {
            "front_hits": f, "back_hits": b,
            "back_frac": round(b / tot, 4) if tot else None,
        }

    if a.selftest:
        # NEGATIVE CONTROL: invert one node's winding and assert the probe flips.
        inv = "Glass_Windscreen" if "Glass_Windscreen" in names else names[0]
        parts2 = []
        for nm, m in zip(sc.geometry, parts):
            mm = m.copy()
            if nm == inv:
                mm.faces = mm.faces[:, ::-1]
                mm.face_normals = -m.face_normals
            parts2.append(mm)
        big2 = trimesh.util.concatenate(parts2)
        w2 = ray_winding(big2, masks, n_dirs=a.rays, res=a.res)
        base = rep["winding"][inv]["back_frac"]
        flip = (w2[inv][1] / max(1, sum(w2[inv]))) if sum(w2[inv]) else None
        rep["selftest"] = {"node": inv, "back_frac_normal": base,
                           "back_frac_inverted": round(flip, 4) if flip is not None else None}
        # STRICT, and it CAN fail: an injected full inversion must send back_frac from
        # near 0 to near 1.  The v1 criterion (|flip-(1-base)|<0.25) was satisfied by
        # ANY value when base sat near 0.5 -- a gate that is empty by construction.
        ok = (base is not None and flip is not None and base < 0.15 and flip > 0.85)
        rep["selftest"]["passes"] = bool(ok)
        rep["selftest"]["criterion"] = "back_frac_normal < 0.15 AND back_frac_inverted > 0.85"
        print(f"SELFTEST invert({inv}): back_frac {base} -> {flip}  {'PASS' if ok else 'FAIL'}")

    print(json.dumps({k: v for k, v in rep.items() if k != "nodes"}, indent=2))
    for n, d in rep["nodes"].items():
        print(f"\n=== {n}  faces={d['faces']} area={d['area']:.4f} comps={d['components']} "
              f"boundary_edges={d['boundary_edges']}")
        for r in d["skins"]:
            print(f"   {r['side']:5s} f={r['faces']:6d} {100*r['area_frac']:5.1f}%  "
                  f"out={r['outward_area_frac']:.2f} in={r['inward_area_frac']:.2f} "
                  f"gap(mm p5/50/95)={r['gap_mm']} bbox={r['bounds']}")
    if a.json:
        json.dump(rep, open(a.json, "w"), indent=1)
        print(f"\nwrote {a.json}")


if __name__ == "__main__":
    main()
