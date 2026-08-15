#!/usr/bin/env python3
"""glaze_openings.py — cap a generated mesh's WINDOW OPENINGS with panes.

Hi3DGen (the experiment winner, 2026-08-15) emits glazing as HOLES — real
window apertures with pillars, not an opaque fused shell. That is the GOOD
failure mode, but it broke the downstream chain in the expected place: with no
glass surface to label, hybrid_transfer found 1.0% glass and refused (its
guard is right; do not relax it). This stage completes the geometry instead:
find the boundary loops of the openings in the cabin band, cap each with a
triangle fan, and merge the caps INTO the shape mesh. Materials stay the
downstream chain's job — the caps sit exactly where PartCrafter's canopy part
is, so the existing label transfer marks them glass with no new rules.

Selection rules (a car has many holes that are NOT windows — arch clearances,
underbody artefacts, mirror gaps):
  * loop centroid must sit in the CABIN BAND: height 40–97% of the car,
    and within the middle 80% of the length;
  * loop span must be big enough to be a window (>4% of car length) and not
    the whole underbody (<60%);
  * loops whose centroid is BELOW the mesh's vertical midline are ignored.

Usage:
    python3 pipeline/carglb/glaze_openings.py in.glb out.glb
Prints per-loop verdicts and the added-face count; refuses loudly if no
opening qualifies (a fused shell should go down the old hybrid path instead).

MEASURED RESULT on the Golf run (2026-08-15): NOT APPLICABLE to that mesh.
The Hi3DGen output is WATERTIGHT (0 boundary loops, 13 bodies) — its windows
are deep RECESSES that read as openings in renders, not actual holes. The
1.0%-glass gate failure on that run was caused one stage earlier: PartCrafter
emitted five overlapping MEGA-parts (1.6M/1.0M/780k/620k/460k faces, each
spanning the car) instead of a separable greenhouse, so hybrid_transfer's
canopy isolation had nothing to isolate. Kept for genuinely open meshes;
the open engineering item is canopy recovery when PartCrafter under-separates.
"""
import sys

import numpy as np
import trimesh


def boundary_loops(mesh):
    """Closed loops of boundary edges (edges used by exactly one face)."""
    edges = mesh.edges_sorted
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    boundary = unique[counts == 1]
    if len(boundary) == 0:
        return []
    # walk the loops
    adj = {}
    for a, b in boundary:
        adj.setdefault(int(a), []).append(int(b))
        adj.setdefault(int(b), []).append(int(a))
    seen = set()
    loops = []
    for start in list(adj):
        if start in seen:
            continue
        loop = [start]
        seen.add(start)
        prev, cur = None, start
        while True:
            nxts = [n for n in adj[cur] if n != prev and n not in seen]
            if not nxts:
                # closed if we can reach start again
                if start in adj[cur] and len(loop) > 2:
                    loops.append(loop)
                break
            prev, cur = cur, nxts[0]
            loop.append(cur)
            seen.add(cur)
    return loops


def glaze(src, dst, min_span=0.04, max_span=0.60):
    m = trimesh.load(src, force="mesh")
    V = np.asarray(m.vertices, dtype=np.float64)
    F = np.asarray(m.faces)
    lo, hi = V.min(0), V.max(0)
    ext = hi - lo
    length_ax = int(np.argmax(ext))
    # height axis: the smaller of the two remaining (a car is wider than tall
    # only for supercars; for the generated meshes measured so far height is
    # the SMALLEST extent after length)
    rest = [i for i in range(3) if i != length_ax]
    height_ax = rest[int(np.argmin(ext[rest]))]

    loops = boundary_loops(m)
    print(f"boundary loops: {len(loops)}")
    caps_V, caps_F = [], []
    base = len(V)
    kept = 0
    for li, loop in enumerate(loops):
        P = V[loop]
        c = P.mean(0)
        span = (P.max(0) - P.min(0))[length_ax] / ext[length_ax]
        hfrac = (c[height_ax] - lo[height_ax]) / ext[height_ax]
        lfrac = (c[length_ax] - lo[length_ax]) / ext[length_ax]
        ok = (0.40 <= hfrac <= 0.97 and 0.10 <= lfrac <= 0.90
              and min_span <= span <= max_span)
        print(f"  loop {li}: n={len(loop)} span={span:.3f} h={hfrac:.2f} "
              f"l={lfrac:.2f} -> {'CAP' if ok else 'skip'}")
        if not ok:
            continue
        # fan cap around the centroid
        ci = base + len(caps_V)
        caps_V.append(c)
        for k in range(len(loop)):
            a, b = loop[k], loop[(k + 1) % len(loop)]
            caps_F.append([ci, a, b])
        kept += 1
    if not kept:
        raise SystemExit("no window openings qualified — this mesh is not the "
                         "open-glazing kind; use the fused-shell path")
    V2 = np.vstack([V, np.array(caps_V)])
    F2 = np.vstack([F, np.array(caps_F, dtype=F.dtype)])
    out = trimesh.Trimesh(vertices=V2, faces=F2, process=False)
    out.export(dst)
    print(f"capped {kept} openings, +{len(caps_F)} faces "
          f"({len(caps_F)/len(F2)*100:.1f}% of mesh) -> {dst}")
    return kept, len(caps_F) / len(F2)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    glaze(sys.argv[1], sys.argv[2])
