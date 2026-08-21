#!/usr/bin/env python3
"""aperture_open.py — open the glazing apertures on car_rebound.glb.

TWO deletions, both of which MOVE NOTHING (deletion is the safe operator; the
25,369 coincident carpaint/interior vertices make any MOVE unsafe):

  (1) BODY FRAGMENTS. Body_Shell connected components, other than the main one,
      that float inside a window opening. Deleting a whole non-main component
      cannot open a hole in the main shell because no main face is touched —
      that is a proof, not a hope. Selection is by DEPTH, never by material
      name and never by face normal (both are recorded traps on this mesh):
        in-aperture : at some pixel the component is hit in front of the
                      Interior skin, where the Interior skin is itself in front
                      of the main shell (= we are looking into the cabin)
        protected   : at some pixel outside such an opening the component sits
                      at or in front of the main shell (= it is exterior skin)
      Protected wins; the main component is protected unconditionally.

  (2) THE INTERIOR SKIN ACROSS THE APERTURES. `Interior` is the inner offset of
      the outer skin and measures only ~40 mm inboard of the glazing at window
      height, so it BLOCKS the cabin rather than backing it. Faces whose
      centroid lies within DIST of the glazing surface are removed, which is
      aperture-shaped by construction and leaves the lining everywhere else.

Run: python3 aperture_open.py [--controls]
"""
import json
import sys
import numpy as np
import trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
import raster

import os
CAR = os.environ.get("CABIN_CAR", "car_merged.glb")
GLAZE = ["Glass_Rear", "Glass_Windscreen", "Glass_Side_L", "Glass_Side_R"]
DIST = 0.10          # m: interior skin within this of the glazing is removed
EPS_OPEN = 0.005     # m: interior must beat the main shell by this to be "open"
EPS_FRONT = 0.002    # m: fragment must beat the interior skin by this
EPS_SKIN = 0.003     # m: fragment at/in front of main shell -> exterior skin


def load():
    sc = trimesh.load(CAR, force="scene", process=False)
    out = {}
    for node in sc.graph.nodes_geometry:
        T, gn = sc.graph[node]
        g = sc.geometry[gn]
        out[node] = (trimesh.transform_points(g.vertices, T), np.asarray(g.faces))
    return sc, out


def comps(V, F):
    q = np.round(V / 1e-5).astype(np.int64)
    _, inv = np.unique(q, axis=0, return_inverse=True)
    Fw = inv[F]
    e = np.vstack([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]])
    n = int(inv.max()) + 1
    A = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    nc, lab = connected_components(A, directed=False)
    return lab[Fw[:, 0]], nc


def main():
    CONTROLS = "--controls" in sys.argv
    sc, N = load()
    BV, BF = N["Body_Shell"]
    IV, IF = N["Interior"]

    # -------- glazing union, for the interior-skin proximity test
    gv, gf = [], []
    for n in GLAZE:
        v, f = N[n]
        gf.append(f + sum(len(x) for x in gv))
        gv.append(v)
    G = trimesh.Trimesh(np.vstack(gv), np.vstack(gf), process=False)

    # -------- (2) interior skin across the apertures
    IC = IV[IF].mean(1)
    # Distance to the glazing via a KD-tree on the glazing VERTICES, not
    # trimesh.closest_point (which OOM-killed this container at 20k-point
    # chunks — the recorded cgroup-cap trap). The panes carry 27,561 verts over
    # 3.175 m^2, i.e. ~10.7 mm mean spacing, so vertex distance approximates
    # surface distance to about a centimetre — an order of magnitude finer than
    # the 100 mm threshold it feeds. The approximation is stated, not hidden.
    from scipy.spatial import cKDTree
    gv_all = np.vstack(gv)
    sp = np.sqrt(G.area / len(gv_all))
    print(f"  glazing: {len(gv_all)} verts, area {G.area:.3f} m^2, "
          f"mean spacing {sp*1000:.1f} mm")
    tree = cKDTree(gv_all)
    d = np.empty(len(IC))
    CH = 20000
    for i in range(0, len(IC), CH):
        d[i:i + CH], _ = tree.query(IC[i:i + CH], k=1, workers=2)
    int_del = d < DIST
    print(f"Interior {len(IF)} faces: {int_del.sum()} within {DIST*1000:.0f} mm "
          f"of glazing -> removed ({100*int_del.sum()/len(IF):.2f}%)")
    np.save("interior_keep.npy", ~int_del)

    # -------- (1) body fragments, by depth
    flab, nc = comps(BV, BF)
    cnt = np.bincount(flab, minlength=nc)
    MAIN = int(np.argmax(cnt))
    print(f"Body_Shell {len(BF)} faces -> {nc} components, main {cnt[MAIN]}")

    ctl = {}
    if CONTROLS:
        # Controls placed from MEASURED local depths: just inboard of the LEFT
        # glazing (z_glass ~ -0.637 at x~+0.35) so a real fragment would live
        # there, and outboard of the Interior skin (z ~ -0.597) so it is
        # genuinely visible.
        def quad(c, s=0.035):
            return (np.array([[c[0] - s, c[1] - s, c[2]], [c[0] + s, c[1] - s, c[2]],
                              [c[0] + s, c[1] + s, c[2]], [c[0] - s, c[1] + s, c[2]]]),
                    np.array([[0, 1, 2], [0, 2, 3]]))
        pB, fB = quad([0.35, 1.15, -0.615])     # welded into main
        pC, fC = quad([0.10, 1.15, -0.610])     # free, behind the L glazing
        pD, fD = quad([-1.55, 0.92, 0.00])      # free, on the bonnet
        pE, fE = quad([0.10, 1.15, -0.700])     # free, OUTSIDE the L glazing
        mainv = BF[flab == MAIN][0][0]
        pB[0] = BV[mainv]
        Vn, Fn = [BV], [BF]
        for p, f, tag in [(pB, fB, "B"), (pC, fC, "C"), (pD, fD, "D"),
                          (pE, fE, "E")]:
            off = sum(len(x) for x in Vn)
            Vn.append(p)
            Fn.append(f + off)
            ctl[tag] = off
        BV = np.vstack(Vn)
        BF = np.vstack(Fn)
        flab, nc = comps(BV, BF)
        cnt = np.bincount(flab, minlength=nc)
        MAIN = int(np.argmax(cnt))
        for tag, off in list(ctl.items()):
            fi = np.where((BF == off).any(1))[0][0]
            ctl[tag] = int(flab[fi])
            print(f"  control {tag}: component {ctl[tag]} "
                  f"({'MAIN' if ctl[tag] == MAIN else 'free'})")

    Vb_b = raster.gltf_to_blender(BV)
    Vb_g = raster.gltf_to_blender(G.vertices)
    GFa = np.asarray(G.faces)
    cams, cfg = raster.cams_from_cfg(__import__("os").environ.get("CABIN_CFG", "rig_cfg.json"))
    mainmask = flab == MAIN
    BFm, BFo = BF[mainmask], BF[~mainmask]
    olab = flab[~mainmask]

    in_ap = np.zeros(nc, bool)
    protect = np.zeros(nc, bool)
    # The aperture reference is the GLAZING depth, never the Interior skin —
    # the first version used the OPENED Interior as the reference, i.e. it
    # deleted the surface its own test depended on, and control C caught it.
    for view, cam in cams.items():
        _, zm = raster.rasterise(cam, Vb_b, BFm)          # near/far main skin
        _, zg = raster.rasterise(cam, Vb_g, GFa)          # nearest glazing
        _, zgf = raster.rasterise(cam, Vb_g, GFa, keep="far")   # farthest
        ido, zo = raster.rasterise(cam, Vb_b, BFo, olab)  # candidate comps
        OPEN = np.isfinite(zg) & (zg < zm - EPS_OPEN)     # looking THROUGH glass
        hit = ido > 0
        # behind the glass and in front of the far side of the shell
        # inside the GLAZED CABIN: behind the near pane, in front of the far
        # pane, and in front of the far side of the shell
        frag = (hit & OPEN & (zo > zg + EPS_FRONT) & (zo < zgf - EPS_FRONT)
                & (zo < zm - EPS_FRONT))
        # coplanar with the outer skin anywhere = it IS exterior skin
        skin = hit & (np.abs(zo - zm) <= EPS_SKIN)
        for m, arr in ((frag, in_ap), (skin, protect)):
            u = np.unique(ido[m]) - 1
            arr[u[u >= 0]] = True
        print(f"  {view}: through-glass px={int(OPEN.sum()):6d}  frag px={int(frag.sum()):5d}"
              f"  comps frag={len(np.unique(ido[frag])):4d} skin={len(np.unique(ido[skin])):4d}")

    protect[MAIN] = True
    sel = in_ap & ~protect
    print(f"\nSELECTED body fragments: {sel.sum()} components / {cnt[sel].sum()} faces"
          f" ({100*cnt[sel].sum()/len(BF):.3f}% of Body_Shell)")

    if CONTROLS:
        r = {"A main spared": not sel[MAIN],
             "B welded in-aperture patch spared": not sel[ctl["B"]],
             "C free in-aperture patch SELECTED": bool(sel[ctl["C"]]),
             "D free bonnet patch spared": not sel[ctl["D"]],
             "E free patch OUTSIDE glazing spared": not sel[ctl["E"]]}
        print("\nNEGATIVE CONTROLS")
        for k, v in r.items():
            print(f"  {k:38s} {'PASS' if v else 'FAIL'}")
        print("  ALL CONTROLS", "PASS" if all(r.values()) else "FAIL")
        return

    np.save("body_keep.npy", ~sel[flab])
    json.dump({"body_faces": int(len(BF)), "body_components": int(nc),
               "main_component_faces": int(cnt[MAIN]),
               "fragment_components": int(sel.sum()),
               "fragment_faces": int(cnt[sel].sum()),
               "interior_faces": int(len(IF)),
               "interior_faces_removed": int(int_del.sum()),
               "interior_dist_mm": DIST * 1000},
              open("aperture_open_report.json", "w"), indent=1)
    print("wrote body_keep.npy interior_keep.npy aperture_open_report.json")


main()
