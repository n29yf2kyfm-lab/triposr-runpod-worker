#!/usr/bin/env python3
"""assemble2.py — v10 COMPONENT assembly: constructed panes + donor wheels.

The v10 review standard: stop repairing neural-blob components, replace
them. This assembler builds the car from:
  * body     — original geometry + baked texture, material `carpaint`
  * interior — original geometry, dark matte (reads as cabin through glass)
  * lamp     — original geometry, dark gloss lens
  * glass    — CONSTRUCTED panes from glass_panes.py (the blob glass faces
               are dropped entirely; the panes sit on each window's fitted
               quadric with a clean outline)
  * wheels   — DONOR geometry (audited catalogue wheel, GR Supra FL; the
               wheel_swap.py method: donor contributes geometry only,
               tyre/rim split by radius, our materials). Original
               wheel-labeled faces become a near-black Arch_Cavity — deleting
               them holes the shell; a dark cavity reads as arch shadow.

Run: python3 assemble2.py <canon.glb> <labels.npy> <panes.npz> <donor.glb>
                          <donor_geom> <out.glb>
"""
import sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

sys.path.insert(0, __file__.rsplit("/", 3)[0] + "/pipeline/trellis")
from wheel_swap import load_donor, CAVITY_MAT

CANON, LAB, PANES, DONOR, DGEOM, OUT = sys.argv[1:7]
REAR = sys.argv[7] if len(sys.argv) > 7 else None   # rear_kit.py npz
BODY, GLASS, WHEEL, LAMP, UNSEEN = 0, 1, 2, 3, 4

sc = trimesh.load(CANON, force="scene")
m = trimesh.util.concatenate([g for g in sc.geometry.values()])
label = np.load(LAB).copy()
cent = m.triangles_center

# the outermost two rings of blob-glass faces are the WINDOW SURROUND, not
# glass: keep them as body so the aperture edge stays body-coloured and the
# constructed pane tucks behind a solid rim (dropping them left a dark gap
# ring around every window — measured on the v10 first cut's clay)
adj = m.face_adjacency
for _ in range(2):
    gm_ = label == GLASS
    ring = np.zeros(len(label), bool)
    edge = gm_[adj[:, 0]] != gm_[adj[:, 1]]
    ring[adj[edge, 0]] = True
    ring[adj[edge, 1]] = True
    flip = ring & gm_
    label[flip] = BODY
print(f"aperture rim: {int((np.load(LAB) == GLASS).sum() - (label == GLASS).sum())} "
      f"glass border faces kept as body surround")

out = trimesh.Scene()

# body keeps the baked texture (grille/badge/lamp graphics live there).
# Floating chips inside window apertures (census: 8,644 in the left side
# window) get painted by the respray and read as white dots on the glass —
# drop flagged candidates that sit in SMALL components; the aperture
# surround ring is connected to the main shell and always survives.
pzc = np.load(PANES)
cand = set(pzc["body_cand"].tolist()) if "body_cand" in pzc else set()
idx = np.where(label == BODY)[0]
if cand:
    import scipy.sparse as sp2
    adj2 = m.face_adjacency
    bm = label == BODY
    same2 = bm[adj2[:, 0]] & bm[adj2[:, 1]]
    g2 = sp2.csr_matrix((np.ones(int(same2.sum())),
                         (adj2[same2, 0], adj2[same2, 1])),
                        shape=(len(label), len(label)))
    from collections import Counter as C2
    _, comp2 = sp2.csgraph.connected_components(g2 + g2.T, directed=False)
    sizes2 = C2(comp2[bm])
    chips = np.array([i for i in idx
                      if i in cand and sizes2[comp2[i]] < 300])
    idx = np.array([i for i in idx if i not in set(chips.tolist())])
    print(f"body: dropped {len(chips)} floating aperture chips")
body = m.submesh([idx], append=True)
if hasattr(body.visual, "material") and body.visual.material is not None:
    body.visual.material.name = "carpaint"
out.add_geometry(body, node_name="carpaint", geom_name="carpaint")

flat_mats = {
    UNSEEN: ("interior", PBRMaterial(name="interior",
             baseColorFactor=[26, 26, 29, 255], metallicFactor=0.0,
             roughnessFactor=0.9)),
    LAMP: ("Lamp_Lens", PBRMaterial(name="Lamp_Lens",
           baseColorFactor=[15, 15, 17, 255], metallicFactor=0.0,
           roughnessFactor=0.08)),
    WHEEL: ("Arch_Cavity", PBRMaterial(**CAVITY_MAT)),
}
# inner-skin interior fragments hugging the pane surfaces poke through the
# glass as white dots (v10 left flank) — glass_panes flags them, drop here
pz0 = np.load(PANES)
skin_drop = set(pz0["drop"].tolist()) if "drop" in pz0 else set()
for key, (name, mat) in flat_mats.items():
    idx = np.where(label == key)[0]
    if key == UNSEEN and skin_drop:
        idx = np.array([i for i in idx if i not in skin_drop])
        print(f"interior: dropped {len(skin_drop)} inner-skin faces")
    if not len(idx):
        continue
    sub = trimesh.Trimesh(vertices=m.vertices, faces=m.faces[idx], process=True)
    sub.visual = trimesh.visual.TextureVisuals(material=mat)
    out.add_geometry(sub, node_name=name, geom_name=name)

# constructed simplified cabin (review item 2): a shrunken hull of the
# greenhouse band, dark matte. The neural interior has holes — bright
# studio light leaks through them and reads as white dots on the glass;
# a solid occluder guarantees a uniform dark cabin behind every pane.
# hull of the GLASS FACES' centroids: that IS the greenhouse envelope, so
# the occluder follows the windscreen rake by construction and can never
# reach the bonnet (v12's greenhouse-band hull poked through it as a grey
# wedge — the band included bonnet-height verts at the nose). Shrunk inward
# so the cabin reads recessed, near-black so it stays dark under the key.
hull = trimesh.convex.convex_hull(cent[np.load(LAB) == GLASS])
hc = hull.vertices.mean(0)
# NEAR-FLUSH, uniform 3% shrink. The white-dot saga (v11-v15, three wrong
# theories, census and all): the dots are a VIEW-DEPENDENT through-path —
# straight-on side views render clean, oblique views skim over the
# occluder's shoulder wherever an anisotropic shrink pulls it off the
# glass, and the bright backdrop shines through gaps in the neural roof
# lining. A near-BLACK matte occluder sitting almost flush behind every
# pane closes the path from all angles and reads as correct dark glass
# (v11's mistake was 22-grey — a LIT slab, not the flush placement).
hull.vertices = hc + (hull.vertices - hc) * 0.93   # a touch deeper (v20):
hull.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
    name="cabin_occluder", baseColorFactor=[14, 14, 17, 255],  # + two shades
    metallicFactor=0.0, roughnessFactor=1.0))      # lighter, so the glass
                                                   # reads tinted-with-depth
                                                   # instead of flat grey
out.add_geometry(hull, node_name="cabin_occluder", geom_name="cabin_occluder")
print(f"cabin occluder: {len(hull.faces)} tris")

# constructed glazing: clear centre + ceramic FRIT band around each pane
# (real-glass look; the frit also seals every aperture-edge artefact).
# The frit material name must NOT contain "glass" — the render worker
# forces transmission onto glass-named materials and would clear the band.
pz = np.load(PANES)
frit_mask = pz["frit"] if "frit" in pz else np.zeros(len(pz["faces"]), bool)
for sel, name, mat in (
        (~frit_mask, "glass", PBRMaterial(
            name="glass", baseColorFactor=[20, 24, 28, 90], metallicFactor=0.0,
            roughnessFactor=0.05, alphaMode="BLEND", doubleSided=True)),
        (frit_mask, "frit_band", PBRMaterial(
            name="frit_band", baseColorFactor=[8, 8, 9, 255],
            metallicFactor=0.0, roughnessFactor=0.55, doubleSided=True))):
    if not sel.any():
        continue
    part = trimesh.Trimesh(vertices=pz["vertices"], faces=pz["faces"][sel],
                           process=True)
    part.visual = trimesh.visual.TextureVisuals(material=mat)
    out.add_geometry(part, node_name=name, geom_name=name)
if "bs_vertices" in pz:
    back = trimesh.Trimesh(vertices=pz["bs_vertices"], faces=pz["bs_faces"],
                           process=True)
    back.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
        name="aperture_backstop", baseColorFactor=[10, 10, 12, 255],
        metallicFactor=0.0, roughnessFactor=1.0, doubleSided=True))
    out.add_geometry(back, node_name="aperture_backstop",
                     geom_name="aperture_backstop")
    print(f"aperture backstop: {len(back.faces)} tris")

# rear kit: constructed tail lamp lenses + number plate (rear_kit.py)
if REAR:
    rz = np.load(REAR)
    for vk, fk, name, mat in (
            ("lens_v", "lens_f", "Tail_Lens", PBRMaterial(
                name="Tail_Lens", baseColorFactor=[52, 7, 9, 255],
                metallicFactor=0.0, roughnessFactor=0.12, doubleSided=True)),
            ("frame_v", "frame_f", "Plate_Frame", PBRMaterial(
                name="Plate_Frame", baseColorFactor=[12, 12, 13, 255],
                metallicFactor=0.0, roughnessFactor=0.6, doubleSided=True)),
            ("plate_v", "plate_f", "Number_Plate", PBRMaterial(
                name="Number_Plate", baseColorFactor=[228, 228, 220, 255],
                metallicFactor=0.0, roughnessFactor=0.55, doubleSided=True))):
        part = trimesh.Trimesh(vertices=rz[vk], faces=rz[fk], process=True)
        part.visual = trimesh.visual.TextureVisuals(material=mat)
        out.add_geometry(part, node_name=name, geom_name=name)
    print("rear kit: tail lenses + plate + frame added")

# donor wheels, positioned from the machine's own wheel labels
tyre_d, rim_d, d_dia, d_wid = load_donor(DONOR, DGEOM)
wc = cent[label == WHEEL]
x_mid = wc[:, 0].mean()
placed = 0
for sl in (1, -1):
    for sw in (1, -1):
        q = wc[((wc[:, 0] - x_mid) * sl > 0) & (wc[:, 2] * sw > 0)]
        if len(q) < 200:
            print(f"corner {sl:+d}/{sw:+d}: too few wheel faces — skipped")
            continue
        cx = float(np.median(q[:, 0]))
        cy = float(np.median(q[:, 1]))
        r = np.hypot(q[:, 0] - cx, q[:, 1] - cy)
        dia = float(np.clip(2 * np.percentile(r, 96), 0.50, 0.80))
        outer = float(np.percentile(np.abs(q[:, 2]), 98)) * sw
        s = dia / d_dia
        # brake kit (v20, per review: a wheel ASSEMBLY needs disc + caliper):
        # silver disc cylinder behind the spokes, red caliper block at the
        # leading top quarter — reads instantly as a real corner assembly
        zc_ = (outer - sw * 0.012) - sw * (d_wid * s) * 0.62
        disc = trimesh.creation.cylinder(radius=0.31 * dia, height=0.02,
                                         sections=48)
        disc.apply_transform(
            trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
        disc.apply_translation([cx, dia / 2, zc_])
        disc.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
            name="Brake_Disc", baseColorFactor=[120, 121, 124, 255],
            metallicFactor=0.9, roughnessFactor=0.45))
        out.add_geometry(disc, node_name=f"disc_{placed}",
                         geom_name=f"disc_{placed}")
        cal = trimesh.creation.box(extents=[0.16 * dia, 0.11 * dia, 0.055])
        cal.apply_translation([cx + 0.20 * dia * sl, dia / 2 + 0.20 * dia, zc_])
        cal.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
            name="Brake_Caliper", baseColorFactor=[150, 22, 26, 255],
            metallicFactor=0.2, roughnessFactor=0.5))
        out.add_geometry(cal, node_name=f"cal_{placed}",
                         geom_name=f"cal_{placed}")
        for part, nm in ((tyre_d, "Tyre_Rubber"), (rim_d, "Rim_Alloy")):
            inst = part.copy()
            inst.apply_scale(s)
            ang = np.pi / 2 if sw > 0 else -np.pi / 2
            inst.apply_transform(
                trimesh.transformations.rotation_matrix(ang, [0, 1, 0]))
            inst.apply_translation([cx, dia / 2,
                                    (outer - sw * 0.012) - sw * (d_wid * s) / 2])
            out.add_geometry(inst, node_name=f"{nm}_{placed}",
                             geom_name=f"{nm}_{placed}")
        placed += 1
        print(f"wheel {sl:+d}/{sw:+d}: x={cx:.2f} axle_y={cy:.2f} "
              f"dia={dia:.2f} outer_z={outer:+.2f}")
if placed < 4:
    raise SystemExit(f"only {placed}/4 wheels placed — refusing a "
                     f"{placed}-wheeled car")

out.export(OUT)
import os
print("assembled v10:", OUT, os.path.getsize(OUT), "bytes")
