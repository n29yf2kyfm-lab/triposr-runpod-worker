#!/usr/bin/env python3
"""strip_assemble.py — remove the melted rear skins, fit the rebuilt panels.

THE CUT IS A FACE DELETION, NEVER A VERTEX PULL. CLAUDE.md records vertex-pull
carving twice as a failure (lamp_recess.py tore stretched-triangle shards; the
Golf gap work dented panels), and 25,369 carpaint vertices on this car are
exactly coincident with interior vertices, so moving one geometry alone opens a
crack in 25,369 places. Deleting faces moves nothing.

THE FOOTPRINT IS THE REBUILT PANEL'S OWN COVERAGE, rasterised from its grid and
dilated one cell. That direction matters: if the cut were taken from the OLD
component's outline it would remove melt in the D-pillar corners the new panel
deliberately does not reach, and open a hole there. Taking it from the panel
guarantees strip is a subset of what gets covered again.

DEPTH comes from layer_probe, not from taste: the melt tailgate and bumper are
thin closed shells -- a second surface within 20 mm on ~92% of rays and within
40 mm on 99.7% (bumper), with essentially nothing else inside 100 mm. 60 mm
therefore takes the whole shell and reaches nothing that should stay.

Run: python3 strip_assemble.py <in.glb> <out.glb> [stripped_only.glb]
"""
import json, sys
import numpy as np, trimesh
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from patchlib import Patch

INP, OUT = sys.argv[1], sys.argv[2]
STRIPPED_ONLY = sys.argv[3] if len(sys.argv) > 3 else None

import os
DEPTH_BACK = 0.060
DEPTH_FRONT = 0.150
# ADAPTATION 2026-08-21 (six-gate merge): env overrides, Gate-4 values as
# defaults.  See rear_zone.py for why.
KEEP = tuple(x for x in os.environ.get(
    "REAR2_KEEP",
    "Tail_Lens,Tail_Housing,Lamp_Lens,Tyre_Rubber,Rim_Alloy").split(",") if x)
# measured: without the wheel exclusion the bumper footprint, which sweeps to
# theta ~ +-88 deg to reach both flank tangents, clipped 211 rear-tyre sidewall
# faces. Small, but it is a hole in a component this gate must not touch.
DROP_NODES = tuple(x for x in os.environ.get(
    "REAR2_DROP", "Rear_Plate,Rear_Plate_Recess").split(",") if x)
PAINT_NODE = os.environ.get("REAR2_PAINT_NODE", "carpaint")
GLASS_NODE = os.environ.get("REAR2_GLASS_NODE", "Rear_Glass")

d = np.load("build/panels.npz")
NV, NU = int(d["NV"]), int(d["NU"])
HVo = d["HVo"]                                        # hatch outer grid (NV,NU,3)
BNV, BNU = int(d["BNV"]), int(d["BNU"])
BVo = d["BV"][:BNV * BNU].reshape(BNV, BNU, 3)
P_bmp = Patch("measurements/fit_bumper.npz")


class Cover:
    """rasterised panel coverage: (y, q) -> panel surface value + a mask."""

    def __init__(self, Y, Q, VAL, dy, dq, dilate=1):
        self.y0, self.q0, self.dy, self.dq = Y.min() - 2 * dy, Q.min() - 2 * dq, dy, dq
        ny = int((Y.max() - self.y0) / dy) + 4
        nq = int((Q.max() - self.q0) / dq) + 4
        acc = np.zeros((ny, nq)); cnt = np.zeros((ny, nq))
        iy = ((Y - self.y0) / dy).astype(int); iq = ((Q - self.q0) / dq).astype(int)
        np.add.at(acc, (iy, iq), VAL); np.add.at(cnt, (iy, iq), 1.0)
        M = np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)
        ok = cnt > 0
        for _ in range(dilate + 6):
            bad = ~np.isfinite(M)
            if not bad.any(): break
            a2 = np.zeros_like(M); c2 = np.zeros_like(M)
            for sh, ax in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
                R = np.roll(M, sh, axis=ax); m = np.isfinite(R)
                a2[m] += R[m]; c2[m] += 1
            M = np.where(bad & (c2 > 0), a2 / np.maximum(c2, 1), M)
        # THE RASTER MUST BE SOLID, and the first version was not. Cells are
        # 6 mm while the panel grid's nodes are 7-9 mm apart, so marking only
        # the cells that contain a node left a DOTTED mask -- and a face landing
        # in one of the gaps was never tested and never cut. Measured cost: 172
        # legacy-melt faces survived INSIDE the panel footprint and stood up to
        # 48 mm PROUD of the rebuilt skin, visible as dark shards on the lower
        # tailgate at 3x. Closing + hole-filling makes the interior solid
        # WITHOUT pushing the outline outward, which a plain dilation would.
        from scipy import ndimage
        st = np.ones((3, 3), bool)
        ok = ndimage.binary_closing(ok, structure=st, iterations=2)
        ok = ndimage.binary_fill_holes(ok)
        self.ok_core = ok.copy()
        for _ in range(dilate):
            ok = ok | np.roll(ok, 1, 0) | np.roll(ok, -1, 0) | np.roll(ok, 1, 1) | np.roll(ok, -1, 1)
        # A wider mask for the PROUD test only. Anything standing through the
        # panel is wrong wherever it is, and removing it cannot open a hole in
        # the panel's own area -- while widening the BACK window would widen the
        # visible seam. So the two windows get different footprints on purpose.
        okf = ok.copy()
        for _ in range(4):
            okf = okf | np.roll(okf, 1, 0) | np.roll(okf, -1, 0) | np.roll(okf, 1, 1) | np.roll(okf, -1, 1)
        self.M = np.where(np.isfinite(M), M, 0.0); self.ok = ok; self.ok_front = okf

    def query(self, y, q):
        iy = ((y - self.y0) / self.dy).astype(int); iq = ((q - self.q0) / self.dq).astype(int)
        good = (iy >= 0) & (iy < self.M.shape[0]) & (iq >= 0) & (iq < self.M.shape[1])
        iy = np.clip(iy, 0, self.M.shape[0] - 1); iq = np.clip(iq, 0, self.M.shape[1] - 1)
        return self.M[iy, iq], self.ok[iy, iq] & good, self.ok_front[iy, iq] & good


HC = Cover(HVo[..., 1].ravel(), HVo[..., 2].ravel(), HVo[..., 0].ravel(), 0.006, 0.006)
_bf = P_bmp.frame(BVo[..., 1].ravel()); byc, bzc = _bf[2], _bf[3]
bth = np.degrees(np.arctan2(BVo[..., 2].ravel() - bzc, BVo[..., 0].ravel() - byc))
brr = np.hypot(BVo[..., 0].ravel() - byc, BVo[..., 2].ravel() - bzc)
BC = Cover(BVo[..., 1].ravel(), bth, brr, 0.006, 0.7)


def in_strip(p):
    """True for face centres inside EITHER panel's footprint + depth window."""
    hit = np.zeros(len(p), bool)
    xs, ok, okf = HC.query(p[:, 1], p[:, 2])
    hit |= ok & (p[:, 0] > xs - DEPTH_BACK) & (p[:, 0] <= xs + 0.0015)
    hit |= okf & (p[:, 0] > xs + 0.0015) & (p[:, 0] < xs + DEPTH_FRONT)
    _f = P_bmp.frame(p[:, 1]); xc, zc = _f[2], _f[3]
    th = np.degrees(np.arctan2(p[:, 2] - zc, p[:, 0] - xc))
    rr = np.hypot(p[:, 0] - xc, p[:, 2] - zc)
    rs, ok2, okf2 = BC.query(p[:, 1], th)
    hit |= ok2 & (rr > rs - DEPTH_BACK) & (rr <= rs + 0.0015)
    hit |= okf2 & (rr > rs + 0.0015) & (rr < rs + DEPTH_FRONT)
    return hit


def clean_mesh(m, name=""):
    """Make one geometry glTF-clean: no zero-area faces, no unreferenced
    vertices, unit vertex normals.

    ALL THREE were introduced by the assembly and none by the source. The
    source rear_v3 measures zeroN=0, nonunit=0, loose=0; the first assembly
    measured 80,000 zero-length normals, because each rebuilt node carried the
    panel's FULL vertex array (outer skin + inner skin) while its faces used
    only one of them -- so every vertex of the other half was unreferenced and
    got a zero normal. `gltf-transform validate` reported ERRORS and the render
    still looked fine, which is precisely the class CLAUDE.md warns about:
    "a geometry operator that only writes positions ships a broken file -- run
    the validator on the OUTPUT and DIFF IT AGAINST THE INPUT, every time."

    Normals are welded by position before averaging (normals_fix's rule) so
    seams between duplicated border vertices shade continuously.
    """
    V = np.asarray(m.vertices, np.float64); F = np.asarray(m.faces, np.int64)
    tri = V[F]
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    F = F[area > 1e-12]
    used = np.unique(F)
    remap = np.full(len(V), -1, np.int64); remap[used] = np.arange(len(used))
    V2 = V[used]; F2 = remap[F]
    uv = getattr(m.visual, "uv", None)
    uv2 = np.asarray(uv)[used] if uv is not None and len(uv) == len(V) else None
    scale = float(np.ptp(V2, axis=0).max()) or 1.0
    key = np.round(V2 / (1e-6 * scale)).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    t2 = V2[F2]
    fn = np.cross(t2[:, 1] - t2[:, 0], t2[:, 2] - t2[:, 0])
    fa = np.linalg.norm(fn, axis=1)
    fnn = fn / np.maximum(fa, 1e-20)[:, None]
    acc = np.zeros((int(inv.max()) + 1, 3))
    for k in range(3):
        np.add.at(acc, inv[F2[:, k]], fnn * fa[:, None])
    N = acc[inv]
    L = np.linalg.norm(N, axis=1, keepdims=True)
    N = np.where(L > 1e-12, N / np.clip(L, 1e-12, None), np.array([0.0, 1.0, 0.0]))
    out = trimesh.Trimesh(vertices=V2, faces=F2, process=False)
    out.vertex_normals = N
    return out, uv2


sc = trimesh.load(INP, force="scene", process=False)
G = dict(sc.geometry)
rep = {"DEPTH_BACK": DEPTH_BACK, "DEPTH_FRONT": DEPTH_FRONT, "stripped": {}}
out = trimesh.Scene()
RENAME = json.loads(os.environ.get("REAR2_RENAME", json.dumps(
    {"Rear_Hatch": "Rear_Upper_Legacy_Melt",
     "Rear_Bumper": "Rear_Bumper_Legacy_Melt"})))
total_removed = 0
for name, g in G.items():
    if name in DROP_NODES:
        rep["stripped"][name] = {"before": int(len(g.faces)), "removed": int(len(g.faces)),
                                 "after": 0, "note": "node replaced by rebuilt geometry"}
        total_removed += len(g.faces); continue
    if name.startswith(KEEP):
        out.add_geometry(g, geom_name=name, node_name=name); continue
    fc = g.triangles_center
    kill = in_strip(fc)
    rep["stripped"][name] = {"before": int(len(g.faces)), "removed": int(kill.sum()),
                             "after": int((~kill).sum()),
                             "pct": round(float(kill.mean() * 100), 2)}
    total_removed += int(kill.sum())
    if (~kill).sum() == 0: continue
    keepf = np.flatnonzero(~kill)
    tmp = trimesh.Trimesh(vertices=g.vertices, faces=g.faces[keepf], process=False)
    tmp.visual = g.visual
    ng, uv2 = clean_mesh(tmp, name)
    if hasattr(g.visual, "material"):
        from trimesh.visual import TextureVisuals as _TV
        ng.visual = _TV(uv=uv2, material=g.visual.material)
    nm = RENAME.get(name, name)
    out.add_geometry(ng, geom_name=nm, node_name=nm)
rep["total_faces_removed"] = total_removed
if STRIPPED_ONLY:
    out.export(STRIPPED_ONLY, include_normals=True)
    print("wrote", STRIPPED_ONLY)
# ---------------------------------------------------------------- assemble
if OUT != "/dev/null":
    from trimesh.visual.material import PBRMaterial
    from trimesh.visual import TextureVisuals
    # ADAPTATION 2026-08-21 (six-gate merge).  `build/uv_paint.npy` is a single
    # (1,2) UV picking one texel of Gate 4's TEXTURED carpaint, tiled over each
    # new painted panel so it takes the body colour from the texture.  The Gate
    # 7+8 rebound lineage's `carpaint` carries NO texture at all (0 images in
    # the file), so there is no texel to pick and a fabricated UV would be
    # meaningless.  Absent file -> uv=None, which is what an untextured PBR
    # material wants.  The paint material itself is unchanged either way.
    uvp = np.load("build/uv_paint.npy") if os.path.exists("build/uv_paint.npy") else None
    paint_mat = G[PAINT_NODE].visual.material
    glass_mat = G[GLASS_NODE].visual.material
    dark = PBRMaterial(name="Shut_Line_Dark", baseColorFactor=[0.030, 0.030, 0.034, 1.0],
                       metallicFactor=0.0, roughnessFactor=0.85)
    plate_mat = PBRMaterial(name="Rear_Plate", baseColorFactor=[0.878, 0.878, 0.851, 1.0],
                            metallicFactor=0.0, roughnessFactor=0.35)

    def add(nm, V, F, mat, textured):
        m = trimesh.Trimesh(vertices=np.asarray(V, np.float64),
                            faces=np.asarray(F, np.int64), process=False)
        m, _ = clean_mesh(m, nm)
        # WRAP THE MATERIAL IN A FRESH TextureVisuals: reassigning an existing
        # TextureVisuals onto a mesh with a different vertex count silently
        # drops the binding on export (premium.py's recorded trap).
        uv = (np.tile(uvp, (len(m.vertices), 1))
              if (textured and uvp is not None) else None)
        m.visual = TextureVisuals(uv=uv, material=mat)
        out.add_geometry(m, geom_name=nm, node_name=nm)
        return int(len(m.faces))

    HGRP, BGRP = d["HGRP"], d["BGRP"]
    HF, BF = d["HF"], d["BF"]
    h0 = HGRP[0]; b0 = BGRP[0]
    nf = {}
    nf["Hatch"] = add("Hatch", d["HV"], HF[:h0], paint_mat, True)
    nf["Hatch_Inner"] = add("Hatch_Inner", d["HV"], HF[h0:], dark, False)
    nf["Bumper_Rear"] = add("Bumper_Rear", d["BV"], BF[:b0], paint_mat, True)
    nf["Bumper_Rear_Inner"] = add("Bumper_Rear_Inner", d["BV"], BF[b0:], dark, False)
    nf["Plate_Rear"] = add("Plate_Rear", d["PV"], d["PF"], plate_mat, False)
    nf["Glass_Backlight"] = add("Glass_Backlight", d["GV"], d["GF"], glass_mat, False)
    rep["added"] = nf
    out.export(OUT, include_normals=True)
    print("wrote", OUT, {k: v for k, v in nf.items()})
    # RE-READ THE WRITTEN FILE and assert. Not the scene in memory: the export
    # is the step that has silently dropped normals on this programme before.
    import subprocess
    chk = subprocess.run([sys.executable, __file__.rsplit("/", 1)[0] + "/glb_assert.py",
                          OUT, INP],          # ADAPTATION: diff against the INPUT
                         capture_output=True, text=True)
    print(chk.stdout.strip() or chk.stderr.strip()[-800:])
    if "GLB_ASSERT_OK" not in chk.stdout:
        raise SystemExit("REFUSED: written file failed its own assertions")
json.dump(rep, open("measurements/strip_report.json", "w"), indent=1)
print(json.dumps({k: v for k, v in rep["stripped"].items() if v.get("removed", 0) > 0}, indent=1))
print("TOTAL FACES REMOVED", total_removed)
