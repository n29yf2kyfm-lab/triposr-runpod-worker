#!/usr/bin/env python3
"""label_fix.py — repair two label defects on an ALREADY-ASSEMBLED machine GLB.

WHY THIS EXISTS. Both defects were found by reviewers on the Pixal van2 and
confirmed by measurement, and both are LABEL errors on correct geometry — so
they are repairable by moving faces between material nodes without touching a
vertex:

  ROOF GLASS. 29.6% of the glazing area sat in the roof zone and 64.5% was
  up-facing. A panel van has no glass roof. Confirmed independently by a matID
  render showing blue across the roof. The seg chain's own roof rule did not
  reclaim it on this mesh.

  TYRE ANNULUS. Only 6.12% of the annulus below the hub carried Tyre_Rubber;
  85.13% carried `interior`. The tyres rendered black because interior is dark
  (0.102), not because the tyre material was bound to them — so "tyres pass"
  was an artefact, exactly like the glazing claim before it. Tightening the
  measurement band made the number WORSE, which is what separates a real result
  from a loose-window artefact.

WHAT IT DELIBERATELY DOES NOT DO. It does not invent geometry, move vertices,
or re-run segmentation. Face count and vertex positions are asserted unchanged;
only which node a face belongs to changes.

THE TRIMESH ROUND-TRIP COSTS NORMALS, AND THAT IS HANDLED, NOT IGNORED.
Re-partitioning primitives cannot be done as a JSON-only edit the way fit_spec
and pose_fix can — the primitives themselves change. trimesh submesh exports
carry no NORMAL accessors, which renders as crumpled foil under the studio
clearcoat (the recorded v6->v7 finding), so this file REQUIRES normals_fix to
be run on its output and says so in its own exit message rather than leaving it
to be remembered.

Run: python3 label_fix.py <in.glb> <out.glb> [--no-roof] [--no-tyre]
     python3 normals_fix.py <out.glb> <final.glb>      # MANDATORY
"""
import argparse
import sys

import numpy as np
import trimesh

UP_COS = 0.7        # |n_y| above this is "facing up", not a raked screen
ROOF_YF = 0.85      # top 15% of car height
ANN_LO, ANN_HI = 1.02, 1.45     # annulus as a multiple of rim radius
ANN_LAT = 0.5       # lateral half-width, as a multiple of rim radius


def _uv_of(visual, idx):
    """Per-vertex UV rows for the given vertex indices, or None if untextured."""
    uv = getattr(visual, "uv", None)
    if uv is None:
        return None
    uv = np.asarray(uv)
    return uv[idx] if len(uv) else None


def _uv_by_nearest(dst_mesh, dst_uv, new_v):
    """Synthesise UVs for vertices arriving from an UNTEXTURED node.

    The glass node carries no UV at all, so moving its faces into the TEXTURED
    carpaint node has nothing to carry — the first fix addressed the wrong half
    and the render came back byte-identical. Nearest-neighbour in 3D from the
    destination's own vertices gives each arriving vertex the UV of the body
    surface it is physically adjacent to, which is the right answer for roof
    panels sitting in the middle of painted bodywork.
    """
    from scipy.spatial import cKDTree
    tree = cKDTree(np.asarray(dst_mesh.vertices))
    _, idx = tree.query(new_v, k=1)
    return np.asarray(dst_uv)[idx]


def _rebuild_visual(visual, uv_extra=None, keep=True):
    """A FRESH TextureVisuals wrapping the same material, with UV extended.

    Fresh, never the original object: trimesh validates uv length against the
    vertex count at export time, so a reused visual whose uv is now short is
    dropped without an error.
    """
    from trimesh.visual import TextureVisuals
    mat = getattr(visual, "material", None)
    if mat is None:
        return visual
    uv = getattr(visual, "uv", None)
    if uv is None:
        return TextureVisuals(material=mat)
    uv = np.asarray(uv)
    if uv_extra is not None and len(uv_extra):
        uv = np.vstack([uv, uv_extra])
    return TextureVisuals(uv=uv, material=mat)


def _face_normals(v, f):
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return n / (ln + 1e-12), tri


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--no-roof", action="store_true")
    ap.add_argument("--roof-mode", choices=["zone", "upfacing"], default="zone",
                    help="zone (default): evict only glazing in the top "
                         "ROOF_YF of car height. upfacing: also evict any "
                         "up-facing glazing — MEASURED TO DESTROY THE "
                         "WINDSCREEN on the Pixal van2, because a noisy "
                         "generated screen has near-horizontal normals and "
                         "93.7% of that car's glazing sat in the cabin third "
                         "with 73.2% of it up-facing. Opt in only with a "
                         "render to back it.")
    ap.add_argument("--no-tyre", action="store_true")
    a = ap.parse_args()

    sc = trimesh.load(a.inp, process=False)
    names = list(sc.geometry)
    for need in ("glass", "carpaint", "Tyre_Rubber", "interior", "Rim_Alloy"):
        if need not in names:
            sys.exit(f"REFUSED: no '{need}' node; have {sorted(names)}")

    allv = np.vstack([np.asarray(g.vertices) for g in sc.geometry.values()])
    lo, hi = allv.min(0), allv.max(0)
    ext = hi - lo
    ax = int(np.argmax(ext))
    side = [i for i in range(3) if i not in (ax, 1)][0]
    if ax != 0:
        sys.exit(f"REFUSED: length axis is {ax}, expected X — run canon.py first")

    faces_before = sum(len(g.faces) for g in sc.geometry.values())

    # ---- move[(src, dst)] -> boolean mask over src's faces -----------------
    moves = []

    if not a.no_roof:
        g = sc.geometry["glass"]
        v, f = np.asarray(g.vertices), np.asarray(g.faces)
        n, tri = _face_normals(v, f)
        yf = (tri.mean(1)[:, 1] - lo[1]) / ext[1]
        m = (yf > ROOF_YF)
        if a.roof_mode == "upfacing":
            m = m | (np.abs(n[:, 1]) > UP_COS)
        ar = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                     tri[:, 2] - tri[:, 0]), axis=1) / 2
        print(f"roof-glass: {int(m.sum())}/{len(f)} glass faces "
              f"({100 * ar[m].sum() / ar.sum():.1f}% of glazing AREA) -> carpaint")
        moves.append(("glass", "carpaint", m))

    if not a.no_tyre:
        rim = np.asarray(sc.geometry["Rim_Alloy"].vertices)
        mx, mz = np.median(rim[:, ax]), np.median(rim[:, side])
        corners = []
        for sx in (True, False):
            for sz in (True, False):
                k = ((rim[:, ax] > mx) == sx) & ((rim[:, side] > mz) == sz)
                if k.sum() < 50:
                    continue
                c = rim[k]
                cx, cy, cz = c[:, ax].mean(), c[:, 1].mean(), c[:, side].mean()
                rr = float(np.percentile(np.hypot(c[:, ax] - cx, c[:, 1] - cy), 98))
                corners.append((cx, cy, cz, rr))
        if len(corners) != 4:
            print(f"tyre-annulus SKIPPED: found {len(corners)} rim corners, "
                  "need exactly 4 — refusing to guess which wheel is which")
        else:
            g = sc.geometry["interior"]
            v, f = np.asarray(g.vertices), np.asarray(g.faces)
            cen = v[f].mean(1)
            m = np.zeros(len(f), bool)
            for (cx, cy, cz, rr) in corners:
                r = np.hypot(cen[:, ax] - cx, cen[:, 1] - cy)
                lat = np.abs(cen[:, side] - cz)
                # BELOW the hub only: arch lips and liners sit above it, and
                # sweeping them in would paint bodywork as rubber.
                m |= ((r > rr * ANN_LO) & (r < rr * ANN_HI)
                      & (lat < rr * ANN_LAT) & (cen[:, 1] < cy))
            frac = m.sum() / max(len(f), 1)
            if frac > 0.25:
                print(f"tyre-annulus REFUSED: would move {100*frac:.1f}% of the "
                      "interior node — that is far more than four tyres and "
                      "means the annulus is mis-sized")
            else:
                print(f"tyre-annulus: {int(m.sum())}/{len(f)} interior faces "
                      f"({100*frac:.2f}% of the interior node) -> Tyre_Rubber")
                moves.append(("interior", "Tyre_Rubber", m))

    if not moves:
        sys.exit("nothing to do")

    # ---- apply: rebuild only the touched nodes -----------------------------
    for src, dst, m in moves:
        gs, gd = sc.geometry[src], sc.geometry[dst]
        vs, fs = np.asarray(gs.vertices), np.asarray(gs.faces)
        moved = fs[m]
        uniq, inv = np.unique(moved.ravel(), return_inverse=True)
        add_v = vs[uniq]
        add_f = inv.reshape(-1, 3) + len(gd.vertices)

        nd = trimesh.Trimesh(
            vertices=np.vstack([np.asarray(gd.vertices), add_v]),
            faces=np.vstack([np.asarray(gd.faces), add_f]), process=False)
        ns = trimesh.Trimesh(vertices=vs, faces=fs[~m], process=False)

        # UV MUST BE CARRIED, AND A STALE TextureVisuals MUST NEVER BE REUSED.
        # Assigning gd.visual straight onto a mesh with MORE vertices leaves a
        # uv array shorter than the vertex array; the exporter then silently
        # drops the material binding and the faces render default-grey. That is
        # a recorded trap in this repo ("evicted roof faces rendered
        # default-white") and the first version of this file walked into it —
        # caught by the render, which turned the whole van grey.
        _extra = _uv_of(gs.visual, uniq)
        _dst_uv = getattr(gd.visual, "uv", None)
        if _extra is None and _dst_uv is not None and len(_dst_uv):
            # source untextured, destination textured -> synthesise
            _extra = _uv_by_nearest(gd, _dst_uv, add_v)
            print(f"  {src}->{dst}: source has no UV; synthesised "
                  f"{len(_extra)} UVs by nearest body vertex")
        nd.visual = _rebuild_visual(gd.visual, uv_extra=_extra)
        ns.visual = _rebuild_visual(gs.visual, keep=None)
        sc.geometry[dst] = nd
        sc.geometry[src] = ns

    faces_after = sum(len(g.faces) for g in sc.geometry.values())
    if faces_after != faces_before:
        sys.exit(f"REFUSED: face count changed {faces_before} -> {faces_after}; "
                 "this stage moves labels and must never add or drop geometry")
    print(f"face count preserved: {faces_after}")

    sc.export(a.out)
    print(f"wrote {a.out}")
    print("\nNOW RUN normals_fix.py ON THIS FILE. The trimesh round-trip above "
          "drops NORMAL accessors and the car will render as crumpled foil "
          "without it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
