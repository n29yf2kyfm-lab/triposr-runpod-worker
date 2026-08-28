#!/usr/bin/env python3
"""surgical_fix.py — targeted repairs that KEEP the generator's good parts.

Born from the premium.py lesson on the Tripo v3.1 Golf (2026-08-28): the
constructed-kit chain fixed placement (liner spread 224mm -> 0.2mm after
de-yaw) but REPLACED features the generator had already produced well — a
legible textured plate became a blank white slab, textured gloss-black
alloys became flat silver primitives. On a dense textured generator the
right operation is surgery on the two real faults, not wholesale
construction. The owner's words: "fix it — gone worse."

The two faults, both measured before this tool existed:

  * THE HOLLOW CABIN (supersedes the "mirrored plate text" diagnosis, which
    was wrong twice over). First wrong: "89,680 carpaint faces sit inside
    the cabin" — that box count was 76% EXTERIOR ROOF (86,265 faces with
    n_y>0.5 at yf~0.95); the true inward-facing population is 233 faces.
    The contaminated-slab sin the council flagged, recommitted the same
    evening while diagnosing. Second wrong: the mirrored text is BACKFACES.
    carpaint is single-sided and Cycles ignores culling (the recorded
    use_backface_culling lesson), so OUR renders show the texture's back;
    compliant viewers cull it. But the A/B at the rear quarter showed the
    compliant view is WORSE: with the inner shell culled the car is HOLLOW
    — far-side arch, suspension and backdrop visible straight through the
    glass. That is what customers were being served, and our rig hid it.
    FIX: construct a CABIN OCCLUDER — the convex hull of the glazing,
    shrunk toward its centroid, near-black — so the eye lands on a dark
    interior instead of passing through the car. Kills the see-through AND
    the mirrored text in every viewer, compliant or not.

  * PALE HEADLAMPS. The lamp apertures hold 36,623 carpaint faces against
    4,568 Lamp_Lens (L/R 0.96 — BOTH lamps, not a left-side problem), and
    the baked texture there is pale grey-green. No detector threshold can
    label geometry that isn't there.
    FIX: in the lamp end-zones, rebind carpaint faces whose TEXEL is pale
    and low-saturation (the lamp graphic; the body is dark) to Lamp_Lens,
    then tint Lamp_Lens's baseColorFactor to a dark smoke — the factor
    MULTIPLIES the texture, so internal detail survives while the lamp
    reads as a dark lens, symmetric by construction.

Everything else — plate, rims, badge, grille, glass material — is left
exactly as the generator made it.

Run: python3 surgical_fix.py <in.glb> <out.glb> [--smoke 0.30]
"""
import argparse
import json
import struct
import sys

import numpy as np
import trimesh


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--smoke", type=float, default=0.30,
                    help="Lamp_Lens baseColorFactor tint (multiplies texture)")
    ap.add_argument("--pale-luma", type=float, default=110.0,
                    help="texel luma above which a lamp-zone face counts pale")
    a = ap.parse_args()

    sc = trimesh.load(a.inp, force="scene")
    cp = sc.geometry["carpaint"]
    uv = getattr(cp.visual, "uv", None)
    tex = getattr(cp.visual.material, "baseColorTexture", None)
    if uv is None or tex is None:
        raise SystemExit("REFUSED: carpaint has no texture/uv — this surgery "
                         "is for textured generator output")

    allv = np.vstack([g.vertices for g in sc.geometry.values()])
    x0, x1 = allv[:, 0].min(), allv[:, 0].max()
    y0, y1 = allv[:, 1].min(), allv[:, 1].max()
    L, H = x1 - x0, y1 - y0
    c = cp.triangles_center
    n = cp.face_normals
    xf = (c[:, 0] - x0) / L
    yf = (c[:, 1] - y0) / H

    # ---- fault 1: the hollow cabin — construct an occluder -------------
    # hull of the glazing, shrunk toward its own centroid so it sits just
    # behind every pane; near-black so the eye reads "dark interior".
    glass = sc.geometry.get("glass")
    if glass is None:
        raise SystemExit("REFUSED: no glass geometry to build the occluder from")
    hull = trimesh.Trimesh(vertices=glass.vertices).convex_hull
    ctr = hull.vertices.mean(0)
    hull.vertices = ctr + (hull.vertices - ctr) * 0.94
    # drop the hull floor to the sill so footwells don't glow: extend down
    hv = hull.vertices.copy()
    hv[:, 1] = np.maximum(hv[:, 1] - 0.10, y0 + 0.25 * H)
    occ = trimesh.Trimesh(vertices=np.vstack([hull.vertices, hv]),
                          faces=None).convex_hull
    occ.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(
            name="Cabin_Occluder", baseColorFactor=[14, 14, 16, 255],
            metallicFactor=0.0, roughnessFactor=0.92, doubleSided=True))
    print(f"cabin occluder: {len(occ.faces)} faces from the glazing hull")

    # ---- fault 2: pale lamp-zone faces --------------------------------
    img = np.asarray(tex.convert("RGB"), dtype=np.float32)
    ih, iw = img.shape[:2]
    fuv = uv[cp.faces].mean(1)                     # face UV centroid
    px = np.clip((fuv[:, 0] * (iw - 1)).astype(int), 0, iw - 1)
    py = np.clip(((1.0 - fuv[:, 1]) * (ih - 1)).astype(int), 0, ih - 1)
    texel = img[py, px]
    luma = texel @ np.array([0.2126, 0.7152, 0.0722])
    sat = texel.max(1) - texel.min(1)
    lamp_zone = ((xf > 0.82) | (xf < 0.18)) & (yf > 0.30) & (yf < 0.62)
    pale = lamp_zone & (luma > a.pale_luma) & (sat < 60)
    print(f"pale lamp-zone carpaint faces rebound to Lamp_Lens: {int(pale.sum())}")
    if pale.sum() == 0:
        raise SystemExit("REFUSED: no pale lamp faces found — writing an "
                         "unchanged copy would be a no-op dressed as a fix")

    # ---- rebuild the scene with the two rebinds ------------------------
    lamp = sc.geometry.get("Lamp_Lens")
    keep = ~pale

    def submesh(mask, like, name):
        m = cp.copy()
        m.update_faces(mask)
        m.remove_unreferenced_vertices()
        mat = like.visual.material
        muv = getattr(m.visual, "uv", None)
        m.visual = trimesh.visual.TextureVisuals(uv=muv, material=mat)
        return m

    out = trimesh.Scene()
    for node in sc.graph.nodes_geometry:
        T, gn = sc.graph[node]
        if gn == "carpaint":
            body = submesh(keep, cp, "carpaint")
            out.add_geometry(body, geom_name="carpaint", node_name=node,
                             transform=T)
        elif gn not in out.geometry:
            out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=node,
                             transform=T)
    out.add_geometry(occ, geom_name="Cabin_Occluder", node_name="Cabin_Occluder")
    if pale.sum():
        lskin = submesh(pale, lamp, "Lamp_Skin")
        out.add_geometry(lskin, geom_name="Lamp_Skin", node_name="Lamp_Skin")
    out.export(a.out, include_normals=True)

    # ---- tint Lamp_Lens (and Lamp_Skin, same material) dark smoke ------
    with open(a.out, "rb") as fh:
        data = fh.read()
    ln = struct.unpack("<I", data[12:16])[0]
    j = json.loads(data[20:20 + ln])
    rest = data[20 + ln:]
    tinted = 0
    for m in j.get("materials", []):
        nm = (m.get("name") or "")
        if "Lamp" in nm:
            pbr = m.setdefault("pbrMetallicRoughness", {})
            pbr["baseColorFactor"] = [a.smoke, a.smoke * 1.05, a.smoke * 1.15, 1.0]
            pbr["roughnessFactor"] = 0.15
            pbr["metallicFactor"] = 0.0
            tinted += 1
    if not tinted:
        raise SystemExit("REFUSED: no Lamp material found to tint")
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    with open(a.out, "wb") as fh:
        fh.write(b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + len(rest)))
        fh.write(struct.pack("<I", len(js)) + b"JSON" + js)
        fh.write(rest)
    print(f"Lamp materials tinted to smoke {a.smoke}: {tinted}")

    # verify the rebinds landed in the written file
    sc2 = trimesh.load(a.out, force="scene")
    for want in ["Cabin_Occluder"] + (["Lamp_Skin"] if pale.sum() else []):
        if want not in sc2.geometry:
            raise SystemExit(f"REFUSED: {want} missing from the export")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
