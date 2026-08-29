#!/usr/bin/env python3
"""lamp_split.py — the headlamp and the tail lamp are not the same material.

THE DEFECT. The owner: "front headlamp needs cleaning up". It renders as a
flat pale smear with no lens depth, while the tail lamps look right. Both
are bound to ONE material, `Lamp_Lens`, which is TEXTURED — so each end
simply shows whatever Tripo baked, and what it baked at the nose is a
blow-out. Measured on the four-image Golf, sampling the mesh's own
baseColorTexture at face-centre UVs:

    FRONT lamp   11,729 faces   luma mean 158.9   RGB 158.6/158.9/158.9
    REAR lamp     9,281 faces   luma mean  92.3   RGB 124.5/ 83.4/ 85.1
    body paint                  luma mean  71.4

The nose lamp is a NEUTRAL WHITE patch at more than twice the brightness of
the bodywork. A real headlamp reads mostly DARK — clear glass over a dark
housing — with small bright reflector and DRL elements inside it. The tail
is genuinely red and genuinely darker, and is fine.

WHY ONE MATERIAL CANNOT BE FIXED IN PLACE: darkening `Lamp_Lens` to rescue
the headlamp would drag the tail lamps down with it, and a glTF factor
MULTIPLIES the texture, so there is no value that helps one end without
hurting the other. The material has to be split first.

The split is by x sign, which is safe because nose_fix runs earlier in the
chain and guarantees the nose is at +x — that is the whole reason it exists
and it refuses when its cues disagree.

THE FRONT KEEPS ITS TEXTURE, TINTED DOWN. The bake is not uniform — p10 40.9
against p90 212.0 — so there IS internal structure in there; it is simply
sitting three stops too bright. A baseColorFactor scales it while preserving
that relative structure, which is what gives the lens its internals back.
This is deliberately NOT headlight_kit: constructing lens/reflector/
projector solids was tried on this car and produced pale slivers over the
existing lamp, and was reverted.

Neither name matches the render worker's glazing regex
(glass|window|windscreen|windshield|screen|vidro|glas|scheibe|fenster), so
the worker cannot force transmission onto a headlamp.

Run: python3 lamp_split.py <in.glb> <out.glb> [--tint 0.30] [--rough 0.10]
                           [--clearcoat 0.06] [--material Lamp_Lens]
"""
import argparse

import numpy as np
import trimesh

FRONT, REAR = "Lamp_Front", "Lamp_Rear"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--material", default="Lamp_Lens")
    ap.add_argument("--tint", type=float, default=0.30)
    ap.add_argument("--rough", type=float, default=0.10)
    ap.add_argument("--clearcoat", type=float, default=0.06)
    a = ap.parse_args()

    sc = trimesh.load(a.inp, force="scene")
    if a.material not in sc.geometry:
        raise SystemExit(f"REFUSED: no {a.material!r} geometry; this file has "
                         f"{sorted(sc.geometry)}")
    node = [n for n in sc.graph.nodes_geometry
            if sc.graph[n][1] == a.material][0]
    T, _ = sc.graph[node]
    g = sc.geometry[a.material]
    world = trimesh.transform_points(g.triangles_center, T)
    mid = 0.5 * (world[:, 0].min() + world[:, 0].max())
    front = world[:, 0] > mid
    print(f"{a.material}: {len(g.faces)} faces -> front {int(front.sum())}, "
          f"rear {int((~front).sum())} (split at x={mid:.3f})")
    if front.sum() < 200 or (~front).sum() < 200:
        raise SystemExit("REFUSED: one end has almost no lamp faces — the "
                         "split would invent a lamp that is not there")

    base = g.visual.material
    gf = g.submesh([np.where(front)[0]], append=True)
    gr = g.submesh([np.where(~front)[0]], append=True)

    mf = trimesh.visual.material.PBRMaterial(
        name=FRONT, baseColorTexture=getattr(base, "baseColorTexture", None),
        baseColorFactor=[a.tint, a.tint, a.tint * 1.02, 1.0],
        metallicFactor=0.0, roughnessFactor=a.rough)
    mr = trimesh.visual.material.PBRMaterial(
        name=REAR, baseColorTexture=getattr(base, "baseColorTexture", None),
        metallicFactor=0.0, roughnessFactor=0.18)
    gf.visual = trimesh.visual.TextureVisuals(
        uv=getattr(gf.visual, "uv", None), material=mf)
    gr.visual = trimesh.visual.TextureVisuals(
        uv=getattr(gr.visual, "uv", None), material=mr)

    out = trimesh.Scene()
    for n in sc.graph.nodes_geometry:
        Tn, gn = sc.graph[n]
        if gn == a.material:
            continue
        if gn not in out.geometry:
            out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=n,
                             transform=Tn)
    out.add_geometry(gf, geom_name=FRONT, node_name=FRONT, transform=T)
    out.add_geometry(gr, geom_name=REAR, node_name=REAR, transform=T)
    out.export(a.out, include_normals=True)

    chk = trimesh.load(a.out, force="scene")
    for nm in (FRONT, REAR):
        if nm not in chk.geometry:
            raise SystemExit(f"REFUSED: {nm} missing from the written file")
        if getattr(chk.geometry[nm].visual, "uv", None) is None:
            raise SystemExit(f"REFUSED: {nm} lost its UVs — a textured lamp "
                             f"without UVs renders as flat colour")
    print(f"wrote {a.out}: {FRONT} tinted x{a.tint} rough {a.rough}, "
          f"{REAR} left as baked")


if __name__ == "__main__":
    main()
