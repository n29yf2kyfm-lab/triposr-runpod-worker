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

DEPTH_BACK = 0.060
DEPTH_FRONT = 0.150
KEEP = ("Tail_Lens", "Tail_Housing", "Lamp_Lens",     # constructed / front lamps
        "Tyre_Rubber", "Rim_Alloy")                   # wheels are another gate's scope
# measured: without the wheel exclusion the bumper footprint, which sweeps to
# theta ~ +-88 deg to reach both flank tangents, clipped 211 rear-tyre sidewall
# faces. Small, but it is a hole in a component this gate must not touch.
DROP_NODES = ("Rear_Plate", "Rear_Plate_Recess")      # replaced by the new build

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
        for _ in range(dilate):
            ok = ok | np.roll(ok, 1, 0) | np.roll(ok, -1, 0) | np.roll(ok, 1, 1) | np.roll(ok, -1, 1)
        self.M = np.where(np.isfinite(M), M, 0.0); self.ok = ok

    def query(self, y, q):
        iy = ((y - self.y0) / self.dy).astype(int); iq = ((q - self.q0) / self.dq).astype(int)
        good = (iy >= 0) & (iy < self.M.shape[0]) & (iq >= 0) & (iq < self.M.shape[1])
        iy = np.clip(iy, 0, self.M.shape[0] - 1); iq = np.clip(iq, 0, self.M.shape[1] - 1)
        return self.M[iy, iq], self.ok[iy, iq] & good


HC = Cover(HVo[..., 1].ravel(), HVo[..., 2].ravel(), HVo[..., 0].ravel(), 0.006, 0.006)
_bf = P_bmp.frame(BVo[..., 1].ravel()); byc, bzc = _bf[2], _bf[3]
bth = np.degrees(np.arctan2(BVo[..., 2].ravel() - bzc, BVo[..., 0].ravel() - byc))
brr = np.hypot(BVo[..., 0].ravel() - byc, BVo[..., 2].ravel() - bzc)
BC = Cover(BVo[..., 1].ravel(), bth, brr, 0.006, 0.7)


def in_strip(p):
    """True for face centres inside EITHER panel's footprint + depth window."""
    hit = np.zeros(len(p), bool)
    xs, ok = HC.query(p[:, 1], p[:, 2])
    hit |= ok & (p[:, 0] > xs - DEPTH_BACK) & (p[:, 0] < xs + DEPTH_FRONT)
    _f = P_bmp.frame(p[:, 1]); xc, zc = _f[2], _f[3]
    th = np.degrees(np.arctan2(p[:, 2] - zc, p[:, 0] - xc))
    rr = np.hypot(p[:, 0] - xc, p[:, 2] - zc)
    rs, ok2 = BC.query(p[:, 1], th)
    hit |= ok2 & (rr > rs - DEPTH_BACK) & (rr < rs + DEPTH_FRONT)
    return hit


sc = trimesh.load(INP, force="scene", process=False)
G = dict(sc.geometry)
rep = {"DEPTH_BACK": DEPTH_BACK, "DEPTH_FRONT": DEPTH_FRONT, "stripped": {}}
out = trimesh.Scene()
RENAME = {"Rear_Hatch": "Rear_Upper_Legacy_Melt", "Rear_Bumper": "Rear_Bumper_Legacy_Melt"}
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
    ng = g.submesh([np.flatnonzero(~kill)], append=True, repair=False)
    ng.visual = g.visual.__class__(uv=(g.visual.uv[np.unique(g.faces[~kill])]
                                       if getattr(g.visual, "uv", None) is not None else None),
                                   material=g.visual.material) \
        if hasattr(g.visual, "material") else g.visual
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
    uvp = np.load("build/uv_paint.npy")
    paint_mat = G["carpaint"].visual.material
    glass_mat = G["Rear_Glass"].visual.material
    dark = PBRMaterial(name="Shut_Line_Dark", baseColorFactor=[0.030, 0.030, 0.034, 1.0],
                       metallicFactor=0.0, roughnessFactor=0.85)
    plate_mat = PBRMaterial(name="Rear_Plate", baseColorFactor=[0.878, 0.878, 0.851, 1.0],
                            metallicFactor=0.0, roughnessFactor=0.35)

    def add(nm, V, F, mat, textured):
        m = trimesh.Trimesh(vertices=np.asarray(V, np.float64),
                            faces=np.asarray(F, np.int64), process=False)
        # WRAP THE MATERIAL IN A FRESH TextureVisuals: reassigning an existing
        # TextureVisuals onto a mesh with a different vertex count silently
        # drops the binding on export (premium.py's recorded trap).
        uv = np.tile(uvp, (len(m.vertices), 1)) if textured else None
        m.visual = TextureVisuals(uv=uv, material=mat)
        out.add_geometry(m, geom_name=nm, node_name=nm)
        return int(len(F))

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
json.dump(rep, open("measurements/strip_report.json", "w"), indent=1)
print(json.dumps({k: v for k, v in rep["stripped"].items() if v.get("removed", 0) > 0}, indent=1))
print("TOTAL FACES REMOVED", total_removed)
