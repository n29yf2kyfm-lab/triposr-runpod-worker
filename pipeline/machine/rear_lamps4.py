#!/usr/bin/env python3
"""rear_lamps4.py — FOUR separate lamp SOLIDS, shrink-wrapped, with thickness.

The reviewer's verdict on every previous pass stands: strips painted onto
the shell are not components. This stage builds the geometry-replacement
step that was missing:

  * four separate meshes — left outer, left hatch, right outer, right hatch
  * built ONCE on the right side, mirrored for the left (symmetry by
    construction, the rear_kit3 lesson)
  * SHRINK-WRAPPED onto the real body: every grid vertex pulls to the
    nearest body surface with a small outward offset, so the OUTER unit
    genuinely wraps the rear corner onto the quarter panel — the wrap is
    what a (y,z)->x heightfield could never do, and why v31-v34 lamps
    stopped dead at the tail face
  * LENS THICKNESS: outer skin + inner skin + stitched perimeter wall =
    a closed solid with a clean perimeter, not a floating sheet

ANCHORS ARE FROZEN (reviewer instruction 2026-08-18) — measured by the
selection stage on the gseg Golf canonical frame and used only as
landmarks: lamp band y 0.83..1.04 (H=1.65), tail face x ~ -2.13..-1.70,
corner |z| ~ 0.87 at lamp height. Do not re-derive them from labels.

Run: python3 rear_lamps4.py <car.glb> <out.npz> [plate_passthrough.npz]
"""
import sys
import numpy as np
import trimesh
from scipy import ndimage
from scipy.spatial import cKDTree

CAR, OUT = sys.argv[1], sys.argv[2]
PLATE_SRC = sys.argv[3] if len(sys.argv) > 3 else None

# ---- frozen anchors, as FRACTIONS of the car's own measured frame ----
# (the landmark POSITIONS are frozen per review; absolutes derive from the
# body so the stage survives dimensional alignment)
YF_LO, YF_HI = 0.505, 0.625       # lamp band, fraction of height
CORNER_F = 0.795                  # corner |z|, fraction of half-width
OFF = 0.005                       # lens stand-off from body
THICK = 0.016                     # lens solid thickness

sc = trimesh.load(CAR, force="scene")
body = [g for n, g in sc.geometry.items() if "carpaint" in n]
if not body:
    raise SystemExit("no carpaint node in the car GLB")
bm = trimesh.util.concatenate(body)
cent = bm.triangles_center
fn = bm.face_normals
_v = bm.vertices
GY = float(_v[:, 1].min()); Hc = float(np.percentile(_v[:, 1], 99.8)) - GY
HW = float(np.percentile(np.abs(_v[:, 2]), 99.7))
XMIN = float(_v[:, 0].min())
Y_LO, Y_HI = GY + YF_LO * Hc, GY + YF_HI * Hc
CORNER_Z = CORNER_F * HW
PIVOT = np.array([XMIN + 0.21, 0.0, CORNER_Z - 0.13])
print(f"frame H {Hc:.3f} halfW {HW:.3f} -> band y {Y_LO:.2f}..{Y_HI:.2f}, "
      f"corner {CORNER_Z:.2f}, pivot {PIVOT.round(2)}")

# rear-third surface at lamp height, with margin — the shrink-wrap target
zone = (cent[:, 0] < XMIN + 0.60) & (cent[:, 1] > Y_LO - 0.12) & (cent[:, 1] < Y_HI + 0.12)
P_all = cent[zone]; N_all = fn[zone]
tree = cKDTree(P_all)
print(f"shrink-wrap target: {len(P_all)} faces in the rear lamp band")


def wrap(points):
    """Pull each point to the body surface; return positions + normals."""
    d, idx = tree.query(points, k=10)
    w = 1.0 / np.clip(d, 1e-4, None)
    pos = (P_all[idx] * w[..., None]).sum(1) / w.sum(1)[:, None]
    nrm = (N_all[idx] * w[..., None]).sum(1)
    nrm /= np.clip(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9, None)
    far = d.min(1)
    return pos, nrm, far


def grid_smooth(A, shape, sigma=1.4):
    out = np.empty_like(A)
    for k in range(A.shape[1]):
        out[:, k] = ndimage.gaussian_filter(
            A[:, k].reshape(shape), sigma, mode="nearest").ravel()
    return out


def envelope(pos, nrm, shape, body_pts, r_lat=0.012, cap=0.045):
    """Push each grid point out to the local body MAXIMUM along its normal.

    The smoothed wrap is a low-pass of a bumpy surface, so relief above
    the mean pokes through the lens (measured on v37: rear outer R 61% of
    lens points occluded by body, median 19mm). Riding the outward
    envelope instead makes poke-through impossible by construction; the
    lens follows the panel's real local relief. `cap` stops a distant
    fixture (spoiler lip, arch flare) being mistaken for panel relief.
    The offset FIELD is lightly smoothed so single-triangle spikes do not
    print through to the lens face.
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


def solid_from_grid(pos, nrm, shape, off, t):
    """Closed lens solid: outer skin, inner skin, perimeter wall."""
    ny, nx = shape
    n = ny * nx
    outer = pos + nrm * (off + t)
    inner = pos + nrm * off
    V = np.vstack([outer, inner])
    F = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i; b = a + 1; c = a + nx; d2 = c + 1
            F += [[a, c, d2], [a, d2, b]]                # outer skin
            A, B, C, D = a + n, b + n, c + n, d2 + n
            F += [[A, D, C], [A, B, D]]                  # inner skin (reversed)
    # perimeter wall
    edge = ([j * nx for j in range(ny)] +                       # left col down
            [(ny - 1) * nx + i for i in range(1, nx)] +          # bottom row
            [j * nx + (nx - 1) for j in range(ny - 2, -1, -1)] + # right col up
            [i for i in range(nx - 2, 0, -1)])                   # top row back
    for e in range(len(edge)):
        a, b = edge[e], edge[(e + 1) % len(edge)]
        F += [[a, b, b + n], [a, b + n, a + n]]
    m = trimesh.Trimesh(vertices=V, faces=np.array(F), process=True)
    m.fix_normals()
    return m


def taper(u, lo_out, hi_out, lo_in, hi_in):
    """Vertical band interpolated from inboard (u=0) to outboard (u=1)."""
    return lo_in + u * (lo_out - lo_in), hi_in + u * (hi_out - hi_in)


# ---- RIGHT OUTER unit: angular sweep around the corner pivot ----
NTH, NYO = 34, 12
thetas = np.radians(np.linspace(206, 74, NTH))     # inboard tail -> quarter wrap
pts = []
nrm_con = []                       # CONSTRUCTION normals — see below
for k, th in enumerate(thetas):
    u = k / (NTH - 1)
    ylo, yhi = taper(u, Y_LO, Y_HI, Y_LO + 0.02, Y_HI - 0.03)
    dirv = np.array([np.cos(th), 0.0, np.sin(th)])
    for yy in np.linspace(ylo, yhi, NYO):
        p = PIVOT + 0.24 * dirv
        pts.append([p[0], yy, p[2]])
        nrm_con.append(dirv)
pts = np.array(pts)
pos, _, far = wrap(pts)
pos, _, far = wrap(pos)            # second pass from on-surface: unclumps
print(f"outer unit: wrap distances mean {far.mean()*1000:.0f}mm max {far.max()*1000:.0f}mm")
# NEVER use body normals for orientation: 46% of body faces in the lamp
# band have FLIPPED normals (measured 2026-08-18 — the melt zone is
# fragment soup), so wrap-averaged normals pointed 202/240 tail grid
# points INTO the car and every lens before this fix was built inside-out.
# The outward direction is known BY CONSTRUCTION: the radial sweep dir.
nrm = np.array(nrm_con)
pos = grid_smooth(pos, (NTH, NYO))
pos = envelope(pos, nrm, (NTH, NYO), P_all)
outer_R = solid_from_grid(pos, nrm, (NTH, NYO), OFF, THICK)
ext = outer_R.vertices.max(0) - outer_R.vertices.min(0)
print(f"outer unit solid: {len(outer_R.faces)} faces, "
      f"{ext[0]:.2f}d x {ext[1]:.2f}h x {ext[2]:.2f}w, watertight={outer_R.is_watertight}")

# ---- RIGHT HATCH unit: flat zone on the tailgate, inboard of the shut gap ----
NZ, NYH = 20, 10
zsteps = np.linspace(0.20 * HW / 0.89, 0.475 * HW / 0.89, NZ)
pts = []
for k, zz in enumerate(zsteps):
    u = k / (NZ - 1)
    ylo, yhi = taper(u, Y_LO + 0.01, Y_HI - 0.03, Y_LO + 0.04, Y_HI - 0.065)
    for yy in np.linspace(ylo, yhi, NYH):
        pts.append([XMIN - 0.40, yy, zz])                  # start behind the car
pts = np.array(pts)
# rear-FACING surface only, and lookup in (y,z): each grid point keeps its
# own (y,z) and takes only x + normal from the surface
rf = (fn[:, 0] < -0.30) & (cent[:, 0] < XMIN + 0.25) & \
     (cent[:, 1] > Y_LO - 0.12) & (cent[:, 1] < Y_HI + 0.12)
P_rf = cent[rf]; N_rf = fn[rf]
t2 = cKDTree(P_rf[:, 1:3])
d2, i2 = t2.query(pts[:, 1:3], k=8)
w2 = 1.0 / np.clip(d2, 1e-4, None)
px = (P_rf[i2, 0] * w2).sum(1) / w2.sum(1)
pos = np.stack([px, pts[:, 1], pts[:, 2]], 1)
far = d2.min(1)
print(f"hatch unit: (y,z) lookup distances mean {far.mean()*1000:.0f}mm max {far.max()*1000:.0f}mm")
# construction normal: the hatch face looks straight rearward (-x); body
# normals are untrustworthy here (46% flipped in the melt zone)
nrm = np.tile([-1.0, 0.0, 0.0], (len(pos), 1))
pos = grid_smooth(pos, (NZ, NYH))
pos = envelope(pos, nrm, (NZ, NYH), P_rf)
hatch_R = solid_from_grid(pos, nrm, (NZ, NYH), OFF, THICK)
ext = hatch_R.vertices.max(0) - hatch_R.vertices.min(0)
print(f"hatch unit solid: {len(hatch_R.faces)} faces, "
      f"{ext[0]:.2f}d x {ext[1]:.2f}h x {ext[2]:.2f}w, watertight={hatch_R.is_watertight}")


def mirror(m):
    mm = m.copy()
    mm.vertices = mm.vertices * np.array([1.0, 1.0, -1.0])
    mm.faces = mm.faces[:, ::-1]
    mm.fix_normals()
    return mm


outer_L, hatch_L = mirror(outer_R), mirror(hatch_R)

out = {}
for tag, m in (("ro", outer_R), ("rh", hatch_R),
               ("lo", outer_L), ("lh", hatch_L)):
    out[f"{tag}_v"] = m.vertices
    out[f"{tag}_f"] = m.faces
# symmetry evidence
dz = abs(outer_R.vertices[:, 2].max() + outer_L.vertices[:, 2].min())
print(f"SYMMETRY: outer L/R mirrored exactly (span check {dz*1000:.1f}mm)")

# number plate + frame on the rear-facing surface at plate height
pz_zone = (fn[:, 0] < -0.30) & (cent[:, 0] < XMIN + 0.30) & \
    (np.abs(cent[:, 2]) < 0.30) & \
    (cent[:, 1] > GY + 0.18 * Hc) & (cent[:, 1] < GY + 0.40 * Hc)
if pz_zone.sum() > 100:
    pc = cent[pz_zone].mean(0)
    def rect(w, hh, proud):
        c = np.array([pc[0] - proud, pc[1], 0.0])
        p = [c + [0, -hh/2, -w/2], c + [0, -hh/2, w/2],
             c + [0, hh/2, w/2], c + [0, hh/2, -w/2]]
        return np.array(p), np.array([[0, 2, 1], [0, 3, 2]])
    out["frame_v"], out["frame_f"] = rect(0.56, 0.16, 0.012)
    out["plate_v"], out["plate_f"] = rect(0.52, 0.115, 0.016)
    print(f"plate anchored at x={pc[0]:.2f} y={pc[1]:.2f}")

if PLATE_SRC:
    src = np.load(PLATE_SRC)
    for k in ("plate_v", "plate_f", "frame_v", "frame_f"):
        if k in src:
            out[k] = src[k]
    print("plate + frame passed through from", PLATE_SRC)

out["parametric"] = np.array([2])
np.savez(OUT, **out)
print("wrote", OUT)
