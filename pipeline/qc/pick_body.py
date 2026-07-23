#!/usr/bin/env python3
"""pick_body.py — identify a GLB's real body-paint material.

The render worker's auto-detect and early ingest guesses both mis-pick on many
models: they grab a grille, a tiny bright accent, or the black underbody /
chassis, so the "recolour" lands on the wrong surface and every DVLA colour
looks identical (caught by pipeline/qc/recolour_audit.py). This picks the body
the way a person would: the largest saturated, non-excluded, non-textured panel
(the source paint), with a light-neutral fallback for white/silver shells.

Returns the material NAME to feed as paintMaterialNames, or None when no flat
paint material is isolable (textured / merged body) — those stay single-neutral.

  from pipeline.qc.pick_body import pick_body
  name = pick_body("car.glb")            # -> "primary" | "CARPAINT" | None

Note: exclusion is token-aware, not substring — 'rim' must not fire inside
'p-rim-ary' nor 'tire' inside 'en-tire', while 'CarPaintBadge' still splits to
'badge' and is excluded.
"""
import json, struct, re, sys

EXC = ('glass', 'window', 'windscreen', 'windshield', 'vitre', 'wheel', 'tyre', 'tire',
       'rim', 'llanta', 'neumatic', 'light', 'lamp', 'phare', 'feu', 'headlight', 'tail',
       'chrome', 'mirror', 'miroir', 'plate', 'plaque', 'grille', 'grill', 'calandre',
       'interior', 'interieur', 'seat', 'siege', 'dash', 'trim', 'logo', 'badge', 'rubber',
       'brake', 'disc', 'caliper', 'shadow', 'plastic', 'noir', 'black', 'emiss', 'carbon',
       'vetro', 'glas')
BODYISH = ('body', 'car', 'carross', 'shell', 'paint', 'exterior', 'lack')


def _tokens(name):
    # split original name on non-letters AND camelCase, lowercase the pieces
    return set(t.lower() for t in re.findall(r"[A-Za-z]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)))


def _excluded(name):
    toks = _tokens(name)
    return any(k in toks for k in EXC)


def pick_body(glb):
    try:
        d = open(glb, "rb").read()
        jl = struct.unpack("<I", d[12:16])[0]
        j = json.loads(d[20:20 + jl])
    except Exception:
        return None
    acc = j.get("accessors", [])
    tris = {}                                          # material index -> triangle count (area proxy)
    for me in j.get("meshes", []):
        for pr in me.get("primitives", []):
            mi = pr.get("material")
            if mi is None:
                continue
            ia = pr.get("indices")
            n = (acc[ia]["count"] // 3) if ia is not None else 0
            tris[mi] = tris.get(mi, 0) + n
    best = None; bestscore = 0; lbest = None; lbestarea = 0
    for idx, m in enumerate(j.get("materials", [])):
        name = m.get("name") or ""; low = name.lower()
        pmr = m.get("pbrMetallicRoughness") or {}
        if pmr.get("baseColorTexture"):
            continue                                   # textured body -> single-neutral
        if _excluded(name):
            continue
        bc = (pmr.get("baseColorFactor") or [1, 1, 1, 1])[:3]
        chroma = max(bc) - min(bc); val = max(bc); area = tris.get(idx, 0)
        if val >= 0.1 and chroma >= 0.12:
            # largest saturated panel: chroma-weighted area so a tiny bright accent
            # can't outscore the main painted shell
            score = area * (0.5 + chroma)
            if score > bestscore:
                bestscore = score; best = name
        # fallback: light near-neutral panels (white/silver bodies) named like a body
        if val >= 0.45 and area > lbestarea and any(k in low for k in BODYISH):
            lbestarea = area; lbest = name
    return best or lbest


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(f"{pick_body(p)}\t{p}")
