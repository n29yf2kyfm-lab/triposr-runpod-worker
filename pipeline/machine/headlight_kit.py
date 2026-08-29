#!/usr/bin/env python3
"""headlight_kit.py — construct real headlamp units into a flat aperture.

WHY CONSTRUCTION, PROVEN NOT ASSUMED (Tripo v3.1 Golf, 2026-08-29). The
owner zoomed into the headlamp and asked for a surgical fix. Three stages of
measurement first, and they closed off every cheaper option:

  STAGE 1  the L lamp label sits in the WRONG PLACE — 980 faces at
           |z| 0.18-0.37 (grille/DRL area) against the R lamp's 3,895 at
           |z| 0.39-0.70. The left headlamp is effectively unlabelled.
  STAGE 2  learn the lamp's TEXEL signature on the R side, where the label
           is ground truth, and the answer kills the material route:
             R lamp texels  luma p10/p50/p90 = 155.5 / 160.6 / 160.9
             R body texels  luma p10/p50/p90 =  37.0 /  78.8 /  83.0
           The lamp's own texels span FIVE luma units. It is a flat pale
           patch: the texture holds no lens, no reflector, no LED
           signature. Geometry is flat too (clay shows both apertures as
           shallow depressions). NOTHING TO RECOVER — relabelling or
           tinting can only ever move a flat blob between materials, which
           is why the earlier smoked-lens attempt was rejected on sight.
  STAGE 3  the classifier (luma>130: 94.7% recall, 4.6% false positives,
           both measured on the labelled side) yields the aperture:
           R = 308 x 181 mm, which matches a real Mk7.5 headlamp.

WHAT IT BUILDS, per side, into that footprint:
  Head_Lens_*      outer lens, the aperture surface pushed 3mm proud,
                   dark smoked glass with clearcoat — reads as a lens
                   because there is something BEHIND it, which is the part
                   the flat blob could never do
  Head_Reflector_* bright dish 22mm behind the lens
  Head_Projector_* chrome barrel ring, the modern LED anchor
  Head_DRL_*       thin bright bar along the aperture's top edge

ORIENTATION COMES FROM CONSTRUCTION, NEVER FROM BODY NORMALS. The recorded
v37-v39 lamp failure: 46% of body faces in the lamp band carry flipped
normals (28% strongly inward), so a normal-averaged push direction extrudes
the lens INTO the car and only its crests show — which reads as "painted
patches" and gets worse the more stand-off you add. Here the push direction
is +x (the nose, pinned) with a lateral splay derived from the aperture's
own centroid. Positions still come from the real surface; only the
DIRECTION is synthetic.

Run: python3 headlight_kit.py <in.glb> <out.glb> [--luma 130] [--proud 3]
"""
import argparse

import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial


def texel_luma(geom, img):
    uv = getattr(geom.visual, "uv", None)
    if uv is None:
        return None
    ih, iw = img.shape[:2]
    fuv = uv[geom.faces].mean(1)
    px = np.clip((fuv[:, 0] * (iw - 1)).astype(int), 0, iw - 1)
    py = np.clip(((1 - fuv[:, 1]) * (ih - 1)).astype(int), 0, ih - 1)
    return img[py, px] @ np.array([0.2126, 0.7152, 0.0722])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--luma", type=float, default=130.0)
    ap.add_argument("--proud", type=float, default=0.003)
    a = ap.parse_args()

    sc = trimesh.load(a.inp, force="scene")
    cp = sc.geometry["carpaint"]
    lam = sc.geometry.get("Lamp_Lens")
    img = np.asarray(cp.visual.material.baseColorTexture.convert("RGB"), np.float32)

    allv = np.vstack([g.vertices for g in sc.geometry.values()])
    x1 = allv[:, 0].max()
    y0 = allv[:, 1].min()
    H = allv[:, 1].max() - y0

    # the R lamp label is ground truth for the unit's SIZE and BAND
    lc = lam.triangles_center
    Rlab = lc[(lc[:, 0] > x1 - 0.45) & (lc[:, 2] > 0.30) &
              (lc[:, 1] > y0 + 0.36 * H) & (lc[:, 1] < y0 + 0.58 * H)]
    if len(Rlab) < 200:
        raise SystemExit("REFUSED: no reliable R lamp label to size the unit from")
    z_lo, z_hi = np.abs(Rlab[:, 2]).min(), np.abs(Rlab[:, 2]).max()
    y_lo, y_hi = Rlab[:, 1].min(), Rlab[:, 1].max()
    print(f"unit band from the labelled R lamp: |z| {z_lo:.3f}-{z_hi:.3f} "
          f"({(z_hi-z_lo)*1000:.0f}mm), y {y_lo:.3f}-{y_hi:.3f} "
          f"({(y_hi-y_lo)*1000:.0f}mm)")

    # THE APERTURE LIVES IN BOTH GEOMETRIES, and gathering only carpaint gets
    # it exactly backwards. Measured on this car: the R lamp's bright faces
    # were already MOVED OUT of carpaint into Lamp_Lens by the seg chain, so
    # a carpaint-only search returned R=239 against L=3,935 — the opposite of
    # the real asymmetry, and it would have built the good side from scraps.
    # Search carpaint (unlabelled side) AND Lamp_Lens (labelled side).
    SRC = [("carpaint", cp)] + ([("Lamp_Lens", lam)] if lam is not None else [])
    parts, report = [], {}

    for side, sgn in (("R", +1.0), ("L", -1.0)):
        pieces = []
        for gname, g in SRC:
            lum = texel_luma(g, img)
            if lum is None:
                continue
            gc = g.triangles_center
            m = ((lum > a.luma) &
                 (gc[:, 0] > x1 - 0.45) &
                 (np.sign(gc[:, 2]) == sgn) &
                 (np.abs(gc[:, 2]) >= z_lo - 0.02) &
                 (np.abs(gc[:, 2]) <= z_hi + 0.02) &
                 (gc[:, 1] >= y_lo - 0.02) & (gc[:, 1] <= y_hi + 0.02))
            if m.sum():
                pieces.append((gname, int(m.sum()),
                               g.submesh([np.where(m)[0]], append=True)))
        n = sum(p[1] for p in pieces)
        report[side] = n
        print(f"  {side}: aperture {n} faces from "
              f"{{{', '.join(f'{g}:{k}' for g, k, _ in pieces)}}}")
        if n < 150:
            print(f"  {side}: only {n} aperture faces — unit SKIPPED this side")
            continue
        ap_mesh = (pieces[0][2] if len(pieces) == 1
                   else trimesh.util.concatenate([p[2] for p in pieces]))
        v = ap_mesh.vertices
        ctr = v.mean(0)
        # push direction: +x nose, splayed outboard by the aperture's own
        # lateral offset. Never averaged from body normals (see docstring).
        d = np.array([1.0, 0.0, np.sign(ctr[2]) * 0.35])
        d /= np.linalg.norm(d)

        lens = ap_mesh.copy()
        lens.vertices = v + d * a.proud
        lens.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
            name=f"Head_Lens_{side}", baseColorFactor=[26, 28, 34, 235],
            metallicFactor=0.0, roughnessFactor=0.08, alphaMode="BLEND",
            doubleSided=False))
        parts.append((f"Head_Lens_{side}", lens))

        refl = ap_mesh.copy()
        refl.vertices = v - d * 0.022
        refl.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
            name=f"Head_Reflector_{side}", baseColorFactor=[196, 198, 205, 255],
            metallicFactor=0.85, roughnessFactor=0.22, doubleSided=True))
        parts.append((f"Head_Reflector_{side}", refl))

        # projector barrel: ring on the aperture's inboard third, axis = d
        rad = min((z_hi - z_lo), (y_hi - y_lo)) * 0.30
        proj = trimesh.creation.annulus(r_min=rad * 0.45, r_max=rad,
                                        height=0.018)
        T = trimesh.geometry.align_vectors([0, 0, 1], d)
        proj.apply_transform(T)
        pc = ctr + d * -0.008
        pc[2] = np.sign(ctr[2]) * (z_lo + (z_hi - z_lo) * 0.34)
        proj.apply_translation(pc - proj.vertices.mean(0))
        proj.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
            name=f"Head_Projector_{side}", baseColorFactor=[228, 230, 236, 255],
            metallicFactor=0.95, roughnessFactor=0.10, doubleSided=True))
        parts.append((f"Head_Projector_{side}", proj))

        # DRL: thin bright slab along the aperture's top edge
        top = v[v[:, 1] > np.percentile(v[:, 1], 82)]
        drl = trimesh.creation.box(extents=[0.030, 0.012,
                                            (z_hi - z_lo) * 0.92])
        drl.apply_translation(np.array([top[:, 0].mean() + a.proud * 1.4,
                                        top[:, 1].mean(),
                                        np.sign(ctr[2]) * (z_lo + z_hi) / 2])
                              - drl.vertices.mean(0))
        drl.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
            name=f"Head_DRL_{side}", baseColorFactor=[236, 242, 255, 255],
            emissiveFactor=[0.55, 0.60, 0.72],
            metallicFactor=0.0, roughnessFactor=0.20, doubleSided=True))
        parts.append((f"Head_DRL_{side}", drl))
        print(f"  {side}: unit built -> lens + reflector + projector + DRL")

    if not parts:
        raise SystemExit("REFUSED: no side produced a unit — nothing written")
    if report.get("L", 0) < 150 or report.get("R", 0) < 150:
        print(f"WARNING: asymmetric build (R={report.get('R',0)}, "
              f"L={report.get('L',0)}) — a one-sided car is the defect we "
              f"are fixing, so check the render before shipping")

    out = trimesh.Scene()
    for node in sc.graph.nodes_geometry:
        T, gn = sc.graph[node]
        if gn not in out.geometry:
            out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=node,
                             transform=T)
    for name, g in parts:
        out.add_geometry(g, geom_name=name, node_name=name)
    out.export(a.out, include_normals=True)

    chk = trimesh.load(a.out, force="scene")
    missing = [n for n, _ in parts if n not in chk.geometry]
    if missing:
        raise SystemExit(f"REFUSED: parts missing from the export: {missing}")
    print(f"wrote {a.out} with {len(parts)} constructed lamp parts")


if __name__ == "__main__":
    main()
