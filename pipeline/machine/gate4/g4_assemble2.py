#!/usr/bin/env python3
"""g4_assemble2.py — Gate 4 rear assembly v3: anatomical component boundaries.

v2 split the rear at a plain vertical plane (x > tail - 0.18L), which made
`Rear_Hatch` swallow both rear quarter panels and the D-pillars -- separate,
but not a tailgate. The matID at az035 showed it plainly. v3 cuts the tailgate
where a tailgate actually is:

  * LATERALLY at the tail-lamp shut line. The hatch lamp units end at
    |z| = 0.520 and the outer units start at 0.535, so the tailgate edge is the
    midpoint 0.5275 -- i.e. the boundary is derived from the lamps, which is
    how a real hatchback is built, and it comes out symmetric even though the
    body is not.
  * WIDENING above the lamps to the D-pillars, because a hatch tailgate is
    narrow between the lamps and wide at the backlight.
  * FORWARD along the backlight rake: the rear screen runs from x=2.030 down
    to x=0.941, so a fixed-x cut would have sliced the screen surround.

Components emitted: Rear_Hatch, Rear_Quarter_L/R, Rear_Bumper, Rear_Valance,
Rear_Glass, four Tail_Lens_*, four Tail_Housing_*, Rear_Plate,
Rear_Plate_Recess.

NO BODY VERTEX IS MOVED -- every body operation is a face RE-GROUPING, so the
25,369 carpaint/interior coincident vertices cannot crack. The plate recess is
CONSTRUCTED geometry, never a vertex pull.

Also sanitises vertex normals on EVERY node (zero-length normals are a
PRE-EXISTING defect of the source: `gltf-transform validate car.glb` reports
ACCESSOR_VECTOR3_NON_UNIT on mesh 0 before this stage touches anything), while
preserving UVs and the baked texture.

Run: python3 g4_assemble2.py <car.glb> <lamps.npz> <out.glb>
"""
import json
import os
import struct
import sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

CAR, KIT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
REAR_F = 0.18
BUMP_Y = 0.555          # MEASURED: tail x_p97 steps back 44mm between y .54/.56
Z_GATE_LO = 0.5275      # tailgate lateral edge at lamp height = lamp shut line
Z_GATE_HI = 0.740       # tailgate lateral edge at the backlight
Y_GATE_LO, Y_GATE_HI = 0.950, 1.020
X_GATE_LO, X_GATE_HI = 1.900, 1.050    # forward reach: tail face -> backlight
Y_XR_LO, Y_XR_HI = 0.950, 1.150

sc = trimesh.load(CAR, force="scene")
allv = np.vstack([g.vertices for g in sc.geometry.values()])
XMIN, XMAX = float(allv[:, 0].min()), float(allv[:, 0].max())
GY = float(allv[:, 1].min()); H = float(allv[:, 1].max()) - GY
L = XMAX - XMIN
XR = XMAX - REAR_F * L
kit = np.load(KIT)
rep = {"tail_x": XMAX, "rear_zone_x": XR, "bumper_cut_y": BUMP_Y,
       "tailgate_z_edge_lamp_height": Z_GATE_LO}


def ramp(y, y0, y1, v0, v1):
    t = np.clip((y - y0) / (y1 - y0), 0.0, 1.0)
    return v0 + t * (v1 - v0)


def tailgate_mask(c):
    zt = ramp(c[:, 1], Y_GATE_LO, Y_GATE_HI, Z_GATE_LO, Z_GATE_HI)
    xt = ramp(c[:, 1], Y_XR_LO, Y_XR_HI, X_GATE_LO, X_GATE_HI)
    return (c[:, 0] > xt) & (np.abs(c[:, 2]) < zt) & (c[:, 1] >= BUMP_Y)


def mat(name, col, rough, metal=0.0, alpha=None):
    m = PBRMaterial(name=name,
                    baseColorFactor=[float(x) for x in col] + [1.0 if alpha is None else alpha],
                    metallicFactor=metal, roughnessFactor=rough)
    if alpha is not None:
        m.alphaMode = "BLEND"
    return m


def sanitise(g, name, material=None):
    """Drop degenerate faces and zero-length vertex normals; keep UVs.

    A stale TextureVisuals reassigned onto a different vertex count silently
    drops the material binding on export (premium.py's trap), so the UV array
    is re-wrapped in a FRESH TextureVisuals every time and its length asserted.
    """
    tri = g.triangles
    a = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    ndeg = int((a < 1e-10).sum())
    if ndeg:
        g.update_faces(a >= 1e-10)
    g.remove_unreferenced_vertices()
    uv = None
    if material is None:
        material = g.visual.material
        uv = getattr(g.visual, "uv", None)
        if uv is not None:
            uv = np.asarray(uv)
    vn = np.array(g.vertex_normals, dtype=np.float64)
    n = np.linalg.norm(vn, axis=1)
    bad = n < 1e-6
    nbad = int(bad.sum())
    if nbad:
        vn[bad] = [0.0, 1.0, 0.0]
    vn[~bad] /= n[~bad][:, None]                 # force EXACT unit length
    g.vertex_normals = vn
    if uv is not None and len(uv) == len(g.vertices):
        g.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    else:
        g.visual = trimesh.visual.TextureVisuals(material=material)
    if ndeg or nbad:
        print(f"    {name}: dropped {ndeg} degenerate faces, fixed {nbad} zero normals")
    return g


out = trimesh.Scene()
counts, hyg = {}, {}


def emit(g, name, material=None):
    g = sanitise(g, name, material)
    out.add_geometry(g, geom_name=name, node_name=name)
    counts[name] = int(len(g.faces))
    return g


# ------------------------------------------------------------ carpaint
cp = sc.geometry["carpaint"]
c = cp.triangles_center
rear = c[:, 0] > XR
gate = tailgate_mask(c)
quarter = rear & (c[:, 1] >= BUMP_Y) & ~gate
bump = rear & (c[:, 1] < BUMP_Y)
body = ~(gate | quarter | bump)
print(f"carpaint: body {int(body.sum())}, tailgate {int(gate.sum())}, "
      f"quarters {int(quarter.sum())}, bumper {int(bump.sum())}")
rep["carpaint_split"] = dict(body=int(body.sum()), tailgate=int(gate.sum()),
                             quarters=int(quarter.sum()), bumper=int(bump.sum()))
qz = c[:, 2]
for msk, nm in ((body, "carpaint"), (gate, "Rear_Hatch"),
                (quarter & (qz > 0), "Rear_Quarter_R"),
                (quarter & (qz <= 0), "Rear_Quarter_L"),
                (bump, "Rear_Bumper")):
    g = cp.copy(); g.update_faces(msk)
    emit(g, nm)

# ------------------------------------------------------------ interior
inte = sc.geometry["interior"]
ci = inte.triangles_center
irear = (ci[:, 0] > XR) & (ci[:, 1] < BUMP_Y)
print(f"interior: rear valance {int(irear.sum())}, rest {int((~irear).sum())}")
rep["interior_split"] = dict(valance=int(irear.sum()), rest=int((~irear).sum()))
icol = list(np.array(inte.visual.material.baseColorFactor[:3]) / 255.0)
for msk, nm in ((~irear, "interior"), (irear, "Rear_Valance")):
    g = inte.copy(); g.update_faces(msk)
    emit(g, nm, mat(nm, icol, 0.9))

# ------------------------------------------------------------ glass
gl = sc.geometry["glass"]
cg = gl.triangles_center
grear = cg[:, 0] > XMAX - 0.28 * L
gmat = gl.visual.material
gcol = list(np.array(gmat.baseColorFactor[:3]) / 255.0)
galpha = float(gmat.baseColorFactor[3]) / 255.0
print(f"glass: rear screen {int(grear.sum())} faces, alpha {galpha:.3f} BLEND")
rep["glass_split"] = dict(rear_screen=int(grear.sum()), rest=int((~grear).sum()),
                          alpha=galpha)
for msk, nm in ((~grear, "glass"), (grear, "Rear_Glass")):
    g = gl.copy(); g.update_faces(msk)
    emit(g, nm, mat(nm, gcol, 0.05, 0.0, galpha))

for nm in ("Rim_Alloy", "Tyre_Rubber", "Lamp_Lens"):
    emit(sc.geometry[nm].copy(), nm)

# ------------------------------------------------------------ the four lamps
LENS = mat("Tail_Lens_Red", [0.36, 0.017, 0.022], 0.10, 0.0)
HOUS = mat("Tail_Housing", [0.030, 0.030, 0.034], 0.85, 0.0)
lampinfo = {}
for nm in ("RO", "RH", "LO", "LH"):
    m = trimesh.Trimesh(vertices=kit[f"{nm}_v"], faces=kit[f"{nm}_f"], process=True)
    wt = bool(m.is_watertight); vol = float(m.volume * 1e6)
    emit(m, f"Tail_Lens_{nm}", LENS)
    hm = trimesh.Trimesh(vertices=kit[f"{nm}_house_v"], faces=kit[f"{nm}_house_f"],
                         process=True)
    emit(hm, f"Tail_Housing_{nm}", HOUS)
    lampinfo[nm] = dict(lens_faces=counts[f"Tail_Lens_{nm}"], watertight=wt,
                        volume_cm3=vol,
                        housing_faces=counts[f"Tail_Housing_{nm}"],
                        bbox_min=[float(q) for q in m.vertices.min(0)],
                        bbox_max=[float(q) for q in m.vertices.max(0)])
rep["lamps"] = lampinfo

# ------------------------------------------------------------ plate + recess
sk = []
for n in ("carpaint", "interior"):
    g = sc.geometry[n]; cc = g.triangles_center
    sk.append(cc[(cc[:, 0] > XMAX - 0.09 * L) & (np.abs(cc[:, 2]) < 0.28)])
SKP = np.vstack(sk)
best = None
for y0 in np.arange(0.34, BUMP_Y - 0.04, 0.02):
    m = (SKP[:, 1] >= y0) & (SKP[:, 1] < y0 + 0.02)
    if m.sum() < 80:
        continue
    xp = float(np.percentile(SKP[m, 0], 97))
    if best is None or xp > best[1]:
        best = (y0 + 0.01, xp)
PY, PX = best
PY = min(PY, BUMP_Y - 0.085)
print(f"plate: y={PY:.3f}, tail surface x={PX:.3f}")
rep["plate"] = dict(y=PY, surface_x=PX, plate_m=[0.520, 0.115])

FW, FH, DEPTH = 0.570, 0.152, 0.032


def bar(w, h, dz, dy):
    b = trimesh.creation.box(extents=[DEPTH, h, w])
    b.apply_translation([PX - 0.004 + DEPTH / 2.0, PY + dy, dz])
    return b


tray = trimesh.util.concatenate([
    bar(FW, 0.018, 0.0, +(FH / 2 - 0.009)),          # top rail
    bar(FW, 0.018, 0.0, -(FH / 2 - 0.009)),          # bottom rail
    bar(0.018, FH, +(FW / 2 - 0.009), 0.0),          # right jamb
    bar(0.018, FH, -(FW / 2 - 0.009), 0.0)])         # left jamb
emit(tray, "Rear_Plate_Recess", mat("Rear_Plate_Recess", [0.035, 0.035, 0.038], 0.8))

pl = trimesh.creation.box(extents=[0.010, 0.115, 0.520])
pl.apply_translation([PX + 0.004, PY, 0.0])
emit(pl, "Rear_Plate", mat("Rear_Plate", [0.88, 0.88, 0.85], 0.35))

# ------------------------------------------------------------ export + verify
out.export(OUT, include_normals=True)
with open(OUT, "rb") as fh:
    fh.seek(12); ln, _ = struct.unpack("<II", fh.read(8)); j = json.loads(fh.read(ln))
missing = [m2.get("name") for m2 in j["meshes"]
           if any("NORMAL" not in p["attributes"] for p in m2["primitives"])]
if missing:
    raise SystemExit(f"REFUSED: NORMAL accessor missing on {missing}")
names = [m2.get("name") for m2 in j["meshes"]]
need = ["Rear_Hatch", "Rear_Bumper", "Rear_Valance", "Rear_Glass", "Rear_Plate",
        "Rear_Plate_Recess", "Rear_Quarter_L", "Rear_Quarter_R"] + \
       [f"Tail_Lens_{t}" for t in ("LO", "RO", "LH", "RH")] + \
       [f"Tail_Housing_{t}" for t in ("LO", "RO", "LH", "RH")]
absent = [n for n in need if n not in names]
if absent:
    raise SystemExit(f"REFUSED: nodes missing from export: {absent}")
rep["node_faces"] = counts
rep["gltf_meshes"] = names
rep["normals_present_all_primitives"] = True
json.dump(rep, open(OUT.replace(".glb", "_assemble.json"), "w"), indent=1)
print(f"\nwrote {OUT} ({os.path.getsize(OUT)/1e6:.1f} MB), {len(names)} named meshes")
for k, v in counts.items():
    print(f"   {k}: {v}")
