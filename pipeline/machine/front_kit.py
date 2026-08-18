#!/usr/bin/env python3
"""front_kit.py — front rebuild: headlamp solids, grilles, plate (Phase 7).

Same construction discipline as the rear: components are DESIGNED at
measured positions, shrink-wrapped onto the real nose surface, built once
on the right and mirrored, with lens thickness. The painted-on front the
straight-front view exposed gets genuine geometry:

  * Head_Lens_R / Head_Lens_L — corner-wrapping headlamp solids
  * Grille_Upper — slim bar between the lamps
  * Grille_Lower — main lower intake panel
  * Front_Plate + Front_Plate_Frame

Run: python3 front_kit.py <car.glb> <out.npz>
"""
import json
import sys
import numpy as np
import trimesh
from scipy import ndimage
from scipy.spatial import cKDTree

CAR, OUT = sys.argv[1], sys.argv[2]
OFF, THICK = 0.005, 0.015

sc = trimesh.load(CAR, force="scene")
cp = [g for n, g in sc.geometry.items() if "carpaint" in n][0]
cent = cp.triangles_center
fn = cp.face_normals
v = cp.vertices
GY = float(v[:, 1].min())
H = float(np.percentile(v[:, 1], 99.8)) - GY
HW = float(np.percentile(np.abs(v[:, 2]), 99.7))
XMAX = float(v[:, 0].max())
print(f"frame: H {H:.3f} halfW {HW:.3f} nose x {XMAX:.2f}")

# nose surface (normals face +X) for wrapping
zone = (cent[:, 0] > XMAX - 0.65) & (cent[:, 1] > GY + 0.10 * H) & \
       (cent[:, 1] < GY + 0.62 * H)
P_all = cent[zone]; N_all = fn[zone]
tree = cKDTree(P_all)
print(f"nose wrap target: {len(P_all)} faces")


def wrap(points):
    d, idx = tree.query(points, k=10)
    w = 1.0 / np.clip(d, 1e-4, None)
    pos = (P_all[idx] * w[..., None]).sum(1) / w.sum(1)[:, None]
    nrm = (N_all[idx] * w[..., None]).sum(1)
    nrm /= np.clip(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9, None)
    return pos, nrm, d.min(1)


def grid_smooth(A, shape, sigma=1.4):
    o = np.empty_like(A)
    for k in range(A.shape[1]):
        o[:, k] = ndimage.gaussian_filter(A[:, k].reshape(shape), sigma,
                                          mode="nearest").ravel()
    return o


def envelope(pos, nrm, shape, body_pts, r_lat=0.012, cap=0.045):
    """Ride the outward MAXIMUM of local body relief (see rear_lamps4).

    Measured on v37: head lens L had 77% of its points occluded by body
    (median 34mm) because the smoothed wrap is the low-pass of a bumpy
    nose. The envelope makes poke-through impossible by construction.
    """
    t = cKDTree(body_pts)
    r = float(np.hypot(cap, r_lat))
    off = np.zeros(len(pos))
    for k, ids in enumerate(t.query_ball_point(pos, r)):
        if not ids:
            continue
        d = body_pts[ids] - pos[k]
        proj = d @ nrm[k]
        lat = np.linalg.norm(d - np.outer(proj, nrm[k]), axis=1)
        m = (lat < r_lat) & (proj > 0) & (proj < cap)
        if m.any():
            off[k] = proj[m].max()
    # smooth spreads lifts to neighbours; max() keeps every measured
    # constraint satisfied — plain smoothing ERODES peaks and the relief
    # pokes back through (measured on v38: lamps fragmented into shards)
    sm = ndimage.gaussian_filter(off.reshape(shape), 0.8, mode="nearest").ravel()
    off = np.maximum(off, sm)
    print(f"  envelope: {np.count_nonzero(off)} pts lifted, "
          f"median {np.median(off[off>0])*1000:.0f}mm max {off.max()*1000:.0f}mm"
          if (off > 0).any() else "  envelope: flush already")
    return pos + nrm * (off + 0.002)[:, None]


def solid(pos, nrm, shape, off, t):
    ny, nx = shape
    n = ny * nx
    V = np.vstack([pos + nrm * (off + t), pos + nrm * off])
    F = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i; b = a + 1; c = a + nx; d2 = c + 1
            F += [[a, c, d2], [a, d2, b], [a + n, d2 + n, c + n], [a + n, b + n, d2 + n]]
    edge = ([j * nx for j in range(ny)] + [(ny - 1) * nx + i for i in range(1, nx)] +
            [j * nx + (nx - 1) for j in range(ny - 2, -1, -1)] + [i for i in range(nx - 2, 0, -1)])
    for e in range(len(edge)):
        a, b = edge[e], edge[(e + 1) % len(edge)]
        F += [[a, b, b + n], [a, b + n, a + n]]
    m = trimesh.Trimesh(vertices=V, faces=np.array(F), process=True)
    m.fix_normals()
    return m


parts = []

# ---- headlamp, right, corner sweep (then mirror) ----
Y_LO, Y_HI = GY + 0.415 * H, GY + 0.545 * H
PIVOT = np.array([XMAX - 0.22, 0.0, 0.795 * HW - 0.14])
NTH, NY = 26, 10
pts = []
nrm_con = []
for k, th in enumerate(np.radians(np.linspace(-26, 106, NTH))):
    u = 1 - k / (NTH - 1)
    span = (Y_HI - Y_LO)
    ylo = Y_LO + (1 - u) * 0.30 * span          # slimmer toward the grille
    yhi = Y_HI - (1 - u) * 0.05 * span
    dirv = np.array([np.cos(th), 0.0, np.sin(th)])
    for yy in np.linspace(ylo, yhi, NY):
        p = PIVOT + 0.24 * dirv
        pts.append([p[0], yy, p[2]])
        nrm_con.append(dirv)
pos, _, far = wrap(np.array(pts))
pos, _, far = wrap(pos)
print(f"headlamp wrap mean {far.mean()*1000:.0f}mm max {far.max()*1000:.0f}mm")
# construction normals (radial sweep dirs) — body normals are ~46% flipped
# in melt zones and built every earlier lens inside-out (see rear_lamps4)
nrm = np.array(nrm_con)
pos = grid_smooth(pos, (NTH, NY))
pos = envelope(pos, nrm, (NTH, NY), P_all)
hl_R = solid(pos, nrm, (NTH, NY), OFF, THICK)
hl_L = hl_R.copy(); hl_L.vertices = hl_L.vertices * [1, 1, -1]
hl_L.faces = hl_L.faces[:, ::-1]; hl_L.fix_normals()
ext = hl_R.vertices.max(0) - hl_R.vertices.min(0)
print(f"headlamp solid {ext[0]:.2f}d x {ext[1]:.2f}h x {ext[2]:.2f}w, wt={hl_R.is_watertight}")
parts += [("Head_Lens_R", hl_R, [22, 24, 26], 0.10),
          ("Head_Lens_L", hl_L, [22, 24, 26], 0.10)]

# ---- grilles: nose-facing (y,z)->x lookup panels ----
nf = (fn[:, 0] > 0.30) & (cent[:, 0] > XMAX - 0.45)
P_nf = cent[nf]; N_nf = fn[nf]
t2 = cKDTree(P_nf[:, 1:3])


def panel(name, z0, z1, y0f, y1f, nz, ny, col, rough):
    zs = np.linspace(z0, z1, nz)
    ys = np.linspace(GY + y0f * H, GY + y1f * H, ny)
    g = np.array([[0.0, yy, zz] for zz in zs for yy in ys])
    d2, i2 = t2.query(g[:, 1:3], k=8)
    w2 = 1.0 / np.clip(d2, 1e-4, None)
    px = (P_nf[i2, 0] * w2).sum(1) / w2.sum(1)
    pos = np.stack([px, g[:, 1], g[:, 2]], 1)
    pos = grid_smooth(pos, (nz, ny))
    nrm2 = np.tile([1.0, 0.0, 0.0], (len(pos), 1))   # nose faces +x
    m = solid(pos, nrm2, (nz, ny), 0.004, 0.012)
    parts.append((name, m, col, rough))
    print(f"  {name}: {len(m.faces)} faces, wt={m.is_watertight}")


panel("Grille_Upper", -0.34, 0.34, 0.385, 0.435, 18, 5, [14, 14, 15], 0.55)
panel("Grille_Lower", -0.44, 0.44, 0.155, 0.315, 22, 8, [13, 13, 14], 0.70)

# ---- front plate + frame ----
pz = (fn[:, 0] > 0.30) & (cent[:, 0] > XMAX - 0.35) & (np.abs(cent[:, 2]) < 0.30) & \
     (cent[:, 1] > GY + 0.17 * H) & (cent[:, 1] < GY + 0.33 * H)
pc = cent[pz].mean(0)


def rect(name, w, hh, proud, col):
    c = np.array([pc[0] + proud, pc[1], 0.0])
    p = np.array([c + [0, -hh/2, -w/2], c + [0, -hh/2, w/2],
                  c + [0, hh/2, w/2], c + [0, hh/2, -w/2]])
    m = trimesh.Trimesh(vertices=p, faces=[[0, 1, 2], [0, 2, 3]], process=False)
    parts.append((name, m, col, 0.55))


rect("Front_Plate_Frame", 0.56, 0.16, 0.010, [12, 12, 13])
rect("Front_Plate", 0.52, 0.115, 0.014, [228, 228, 220])
print(f"front plate at x={pc[0]:.2f} y={pc[1]:.2f}")

out = {}
manifest = []
for name, m, col, rough in parts:
    out[f"{name}_v"] = m.vertices
    out[f"{name}_f"] = m.faces
    manifest.append({"name": name, "v": f"{name}_v", "f": f"{name}_f",
                     "color": col, "metallic": 0.0, "rough": rough,
                     "doubleSided": True})
out["manifest"] = np.frombuffer(json.dumps(manifest).encode(), dtype=np.uint8)
np.savez(OUT, **out)
print("wrote", OUT, f"({len(parts)} parts)")
