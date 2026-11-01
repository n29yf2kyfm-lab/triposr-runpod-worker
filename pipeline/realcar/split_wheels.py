#!/usr/bin/env python3
"""split_wheels.py: a car made as one fused piece (an image-to-3D generator's: Tripo, Hunyuan3D, Meshy) cut
into its body and four wheels named wheel_*, so the rigger can find the wheels and the machine can rig it.

    python3 pipeline/realcar/split_wheels.py IN.glb OUT.glb LENGTH_M TYRE_RADIUS_M TRACK_M TYRE_WIDTH_M
    python3 pipeline/realcar/glbmachine.py add OUT.glb --make ... --model ... --years ... --doors 5 --licence ...

The car's real length gives the file's scale; the wheels' centres are where the mesh touches the ground at each
end; a triangle wholly inside a tyre-sized cylinder round an axle, outboard of the track's inner face, is the
wheel's. (A Golf Mk4: 4.149 0.3173 1.513 0.195.)"""
import sys, json
import numpy as np, trimesh
src, dst, LEN, RT, TRACK, TW = sys.argv[1], sys.argv[2], *map(float, sys.argv[3:7])
m = trimesh.load(src, force="mesh", process=False)
V, F = m.vertices, m.faces
lo, hi = V.min(0), V.max(0)
ax = int(np.argmax(hi - lo))                      # length axis
up = 1
side = [a for a in (0, 1, 2) if a not in (ax, up)][0]
s = (hi[ax] - lo[ax]) / LEN                         # model units per metre
ground = lo[up]
r = RT * s
low = V[:, up] < ground + 0.12 * r                  # where the tyres touch the ground
zl = V[low, ax]
mid = (lo[ax] + hi[ax]) / 2
centres = [zl[zl > mid].mean(), zl[zl < mid].mean()]
wb = abs(centres[0] - centres[1]) / s
yc = ground + r
x_in = (TRACK / 2 - TW / 2 - 0.035) * s
print(json.dumps({"axis_len": ax, "scale_per_m": round(s, 4), "wheel_centres_along": [round(c, 4) for c in centres],
                  "wheelbase_m": round(wb, 3), "r_model": round(r, 4), "x_in": round(x_in, 4)}))
tri = V[F]                                          # (n,3,3)
groups = {}
names = []
for zc, end in zip(centres, ("a", "b")):
    for sgn, sd in ((1, "p"), (-1, "n")):
        d = np.hypot(tri[:, :, up] - yc, tri[:, :, ax] - zc)
        inside = (d < r * 1.04).all(1) & ((tri[:, :, side] * sgn) > x_in).all(1)
        groups[f"wheel_{end}{sd}"] = np.where(inside)[0]
taken = np.zeros(len(F), bool)
for k, ix in groups.items():
    taken[ix] = True
    print(k, len(ix), "triangles")
groups["body"] = np.where(~taken)[0]
scene = trimesh.Scene()
for k, ix in groups.items():
    sub = m.submesh([ix], append=True, repair=False)
    scene.add_geometry(sub, node_name=k, geom_name=k)
scene.export(dst)
print("wrote", dst)
