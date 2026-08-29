#!/usr/bin/env python3
"""glass_polish.py — get the paint OFF the windows, and make the paint premium.

Owner, final stage on the Tripo v3.1 Golf (2026-08-29): "polish all window,
no paints on window, plus paint work premium". Two defects, both measured
before this tool existed.

1. PAINT ON THE WINDOWS — 5,960 carpaint faces (0.74% of carpaint) whose
   centroids fall INSIDE a glazing outline, spread over all six panes
   (windscreen 2,101, front-right 1,147, front-left 1,048 ...). They are
   what reads as smeared streaks across the glass and down the pillars.

   NOTE THE METRIC. An earlier attempt (pane_clean.py) judged this by the
   perimeter shape factor P/sqrt(A) and made four of six panes WORSE, so it
   was recorded as a failure and not shipped. Shape factor answers "is the
   outline tidy"; the owner's complaint is "is there paint on my window".
   Those are different questions and only the second one is measured here:
   count carpaint faces inside each pane's filled outline, and drive it to
   zero. Perimeter tidiness needs CONSTRUCTED panes (glass_panes.py), which
   is a different job from this one.

2. PAINT THAT IS NOT PAINT — carpaint shipped with NO metallicFactor and NO
   roughnessFactor, so the glTF defaults apply: metallic 1.0, roughness
   1.0. The body has been rendering as rough bare metal this whole time.
   This is the recorded flat-shell trap ("carpaint previously shipped glTF
   DEFAULTS metallic=1") and it was still live. The production brief's
   values are metallic 0, roughness 0.18-0.30, clearcoat 1.0 at 0.05-0.12.

Both are safe operations: the rebind moves faces between existing
materials, and the PBR fix is a JSON edit. Neither creates geometry.

Run: python3 glass_polish.py <in.glb> <out.glb> [--rough 0.24] [--clearcoat 0.08]
"""
import argparse
import json
import struct

import numpy as np
import trimesh
from scipy import ndimage


def panes(gl, tol=1e-5, min_faces=200):
    V = np.round(gl.vertices / tol).astype(np.int64)
    uq, inv = np.unique(V, axis=0, return_inverse=True)
    F = inv[gl.faces]
    F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]
    w = trimesh.Trimesh(vertices=uq * tol, faces=F, process=False)
    return sorted([c for c in w.split(only_watertight=False)
                   if len(c.faces) > min_faces], key=lambda c: -c.area)


def inside_panes(cp, comps, res=0.006, band=0.03, close=5):
    """Body faces whose centroid lies inside a pane's filled outline."""
    cc = cp.triangles_center
    hit = np.zeros(len(cp.faces), bool)
    per_pane = []
    for c in comps:
        pts = c.triangles_center
        ctr = pts.mean(0)
        _, _, vt = np.linalg.svd(pts - ctr, full_matrices=False)
        n, e1 = vt[2], vt[0]
        e2 = np.cross(n, e1)
        d2 = np.stack([(pts - ctr) @ e1, (pts - ctr) @ e2], 1)
        lo = d2.min(0) - res * 3
        gw = np.ceil((d2.max(0) + res * 3 - lo) / res).astype(int) + 1
        if gw.max() > 4000:
            per_pane.append(0)
            continue
        ij = ((d2 - lo) / res).astype(int)
        msk = np.zeros(gw[::-1], bool)
        msk[ij[:, 1], ij[:, 0]] = True
        msk = ndimage.binary_fill_holes(
            ndimage.binary_closing(msk, np.ones((close, close), bool)))
        near = np.abs((cc - ctr) @ n) < band
        if not near.any():
            per_pane.append(0)
            continue
        b2 = np.stack([(cc[near] - ctr) @ e1, (cc[near] - ctr) @ e2], 1)
        bij = ((b2 - lo) / res).astype(int)
        ok = ((bij[:, 0] >= 0) & (bij[:, 0] < gw[0]) &
              (bij[:, 1] >= 0) & (bij[:, 1] < gw[1]))
        sel = np.zeros(len(b2), bool)
        sel[ok] = msk[bij[ok, 1], bij[ok, 0]]
        idx = np.where(near)[0][sel]
        hit[idx] = True
        per_pane.append(int(sel.sum()))
    return hit, per_pane


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--rough", type=float, default=0.24)
    ap.add_argument("--clearcoat", type=float, default=0.08)
    a = ap.parse_args()

    sc = trimesh.load(a.inp, force="scene")
    gl, cp = sc.geometry["glass"], sc.geometry["carpaint"]
    comps = panes(gl)
    hit0, per = inside_panes(cp, comps)
    print(f"panes: {len(comps)}")
    for i, k in enumerate(per):
        print(f"  pane {i}: {k} carpaint faces inside the outline")
    print(f"paint on windows BEFORE: {int(hit0.sum())} faces "
          f"({100*hit0.sum()/len(cp.faces):.2f}% of carpaint)")

    # NO ITERATION, AND THE VERIFICATION USES FIXED OUTLINES.
    # First cut re-measured against the MODIFIED glass, which is circular:
    # absorbing faces grows the pane, the grown pane's outline encloses more
    # body, so the count can never reach zero. Iterating on that signal ran
    # away — 5,960 -> 30,900 faces absorbed (3.8% of the body) and still
    # "1,783 inside". The aperture is a FIXED target computed once from the
    # input's panes; a single pass moves everything inside it, and the check
    # below asks the same fixed question again.
    hit = hit0
    if hit.sum() == 0:
        raise SystemExit("REFUSED: no paint found on any window — writing an "
                         "unchanged copy would be a no-op dressed as a fix")
    if hit.sum() > 0.05 * len(cp.faces):
        raise SystemExit(f"REFUSED: {int(hit.sum())} faces "
                         f"({100*hit.sum()/len(cp.faces):.1f}%) is too much of "
                         f"the body to move — the outlines are wrong, not the paint")

    moved = cp.submesh([np.where(hit)[0]], append=True)
    moved.visual = trimesh.visual.TextureVisuals(material=gl.visual.material)
    new_glass = trimesh.util.concatenate([gl, moved])
    new_glass.visual = trimesh.visual.TextureVisuals(material=gl.visual.material)
    body = cp.submesh([np.where(~hit)[0]], append=True)
    body.visual = trimesh.visual.TextureVisuals(
        uv=getattr(body.visual, "uv", None), material=cp.visual.material)

    out = trimesh.Scene()
    for node in sc.graph.nodes_geometry:
        T, gn = sc.graph[node]
        if gn == "glass":
            out.add_geometry(new_glass, geom_name="glass", node_name=node,
                             transform=T)
        elif gn == "carpaint":
            out.add_geometry(body, geom_name="carpaint", node_name=node,
                             transform=T)
        elif gn not in out.geometry:
            out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=node,
                             transform=T)
    out.export(a.out, include_normals=True)

    # ---- premium paint PBR, as a JSON edit on the written file ----------
    data = open(a.out, "rb").read()
    ln = struct.unpack("<I", data[12:16])[0]
    j = json.loads(data[20:20 + ln])
    rest = data[20 + ln:]
    done = False
    for m in j.get("materials", []):
        if m.get("name") != "carpaint":
            continue
        pbr = m.setdefault("pbrMetallicRoughness", {})
        before = (pbr.get("metallicFactor"), pbr.get("roughnessFactor"))
        pbr["metallicFactor"] = 0.0
        pbr["roughnessFactor"] = a.rough
        m.setdefault("extensions", {})["KHR_materials_clearcoat"] = {
            "clearcoatFactor": 1.0, "clearcoatRoughnessFactor": a.clearcoat}
        done = True
        print(f"carpaint PBR: metallic/rough {before} -> "
              f"(0.0, {a.rough}) + clearcoat 1.0 @ {a.clearcoat}")
        print("  (None meant the glTF DEFAULTS applied: metallic 1.0, "
              "roughness 1.0 — the body was rendering as rough bare metal)")
    if not done:
        raise SystemExit("REFUSED: no carpaint material to set premium PBR on")
    for ext in ("KHR_materials_clearcoat",):
        for key in ("extensionsUsed",):
            j.setdefault(key, [])
            if ext not in j[key]:
                j[key].append(ext)
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    with open(a.out, "wb") as fh:
        fh.write(b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + len(rest)))
        fh.write(struct.pack("<I", len(js)) + b"JSON" + js)
        fh.write(rest)

    # ---- verify on the WRITTEN file ------------------------------------
    sc2 = trimesh.load(a.out, force="scene")
    hit2, per2 = inside_panes(sc2.geometry["carpaint"], comps)   # ORIGINAL outlines
    print(f"paint on windows AFTER : {int(hit2.sum())} faces")
    if hit2.sum() > hit0.sum() * 0.25:
        raise SystemExit(f"REFUSED: paint-on-windows only fell "
                         f"{int(hit0.sum())} -> {int(hit2.sum())}; the fix did "
                         f"not fire")
    print(f"  reduction: {int(hit0.sum())} -> {int(hit2.sum())} "
          f"({100*(1-hit2.sum()/max(hit0.sum(),1)):.1f}% removed)")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
