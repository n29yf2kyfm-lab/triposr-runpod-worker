#!/usr/bin/env python3
"""ai_parts.py: a car an image-to-3D generator made as one fused shell (Tripo, Hunyuan3D, Meshy: the windows
painted on, nothing separate) cut into the parts the machine rigs: four wheels, the doors, bonnet and tailgate,
and the glass as its own see-through material, so the doors open, the windows are clear and the cabin shows.

    python3 pipeline/realcar/ai_parts.py IN.glb OUTLINES.json OUT.glb
    python3 pipeline/realcar/glbmachine.py add OUT.glb --make ... --model ... --years ... --doors 5 --licence ...

OUTLINES (ai_parts/<car>.json) holds the car's panel and window outlines in metres, traced from the shut lines
and seals the generator printed into its texture (see the Golf Mk4's). The parts are named the way the rigger
reads them: door_front_left ..., bonnet, tailgate, wheel_*, window_* and windscreen (glazing: clear, and a door's
window travels with its door), tailgate_rear_window (the rear glass, on the tailgate)."""
import json
import sys

import numpy as np
import trimesh

GLASS = {"name": "window_glass", "baseColorFactor": [0.30, 0.42, 0.38, 0.45], "alphaMode": "BLEND",
         "metallicFactor": 0.0, "roughnessFactor": 0.05, "doubleSided": True}


def inside(poly, a, b):
    """Which points (a, b) lie inside POLY [[a, b], ...] (even-odd rule)."""
    P = np.asarray(poly, float)
    hit = np.zeros(len(a), bool)
    for (a0, b0), (a1, b1) in zip(P, np.roll(P, -1, 0)):
        crosses = (b0 > b) != (b1 > b)
        at = a0 + (b - b0) * (a1 - a0) / ((b1 - b0) if b1 != b0 else 1e-12)
        hit ^= crosses & (a < at)
    return hit


def cut(src, outlines, dst):
    o = json.load(open(outlines))
    m = trimesh.load(src, force="mesh", process=False)
    V, F = np.asarray(m.vertices), np.asarray(m.faces)
    lo, hi = V.min(0), V.max(0)
    ax = int(np.argmax(hi - lo))
    if ax != 2:
        raise SystemExit("the car's length must lie along the file's Z (turn it first)")
    s = (hi[2] - lo[2]) / o["length"]
    # the rear: where the red of the tail lights is (texture at each face's centre)
    tex = np.asarray(m.visual.material.baseColorTexture.convert("RGB"), np.float32) / 255
    uv = np.asarray(m.visual.uv)[F].mean(1)
    H, W = tex.shape[:2]
    col = tex[np.clip(((1 - uv[:, 1] % 1) * (H - 1)).astype(int), 0, H - 1), np.clip((uv[:, 0] % 1 * (W - 1)).astype(int), 0, W - 1)]
    v = col.max(1)
    C = V[F].mean(1)
    red = (col[:, 0] > 0.45) & (col[:, 1] < 0.25) & (col[:, 2] < 0.25)
    f = -1.0 if C[red, 2].mean() > (lo[2] + hi[2]) / 2 else 1.0        # nose to +Z (a half turn keeps it right-handed)
    X, Y, Z = f * C[:, 0] / s, (C[:, 1] - lo[1]) / s, f * C[:, 2] / s
    N = np.asarray(m.face_normals) * [f, 1, f]
    label = np.array(["body"] * len(F), dtype=object)
    free = lambda: label == "body"                                      # noqa: E731

    # wheels: a tyre-sized cylinder round each axle, outboard of the track's inner face
    r = o["tyre_radius"]
    low = Y < 0.12 * r
    axles = [Z[low & (Z > 0)].mean(), Z[low & (Z < 0)].mean()]
    tri = V[F]
    for zc, end in zip(axles, ("front", "rear")):
        for sgn, side in ((1, "left"), (-1, "right")):
            d = np.hypot((tri[:, :, 1] - lo[1]) / s - r, f * tri[:, :, 2] / s - zc)
            sel = (d < r * 1.04).all(1) & ((f * tri[:, :, 0] / s * sgn) > o["track"] / 2 - o["tyre_width"] / 2 - 0.035).all(1)
            label[sel & free()] = f"wheel_{end}_{side}"
    side_of = np.where(X > 0, "left", "right")
    outward = np.sign(N[:, 0]) == np.sign(X)
    # glass first, so it is taken out of the panels round it
    for key, nm in (("window_front", "window_front"), ("window_rear", "window_rear"), ("window_rear_quarter", "window_quarter")):
        sel = free() & (np.abs(X) > 0.45) & (np.abs(N[:, 0]) > 0.35) & outward & inside(o[key], Z, Y)
        label[sel] = [f"{nm}_{sd}" for sd in side_of[sel]]
    ws = o["windscreen"]
    sel = free() & (N[:, 2] > 0.25) & (N[:, 1] > 0.2) & (np.abs(X) < ws["half_width"]) & (Y > ws["y"][0]) & (Y < ws["y"][1]) \
        & (Z > ws["z"][0]) & (Z < ws["z"][1]) & (v > 0.14)
    label[sel] = "windscreen"
    sel = free() & (N[:, 2] < -0.3) & (Z < -1.4) & inside(o["rear_window"], X, Y) & ~((v < 0.15) & (Y < 1.12))
    label[sel] = "tailgate_rear_window"
    # glass the outlines just missed (the windscreen's edges where it wraps into the A-pillars, a window's
    # corners): the glass-coloured faces next to it, by the tint the generator painted its glass
    tint = (col[:, 1] > col[:, 0] + 0.03) & (col[:, 1] >= col[:, 2]) & (v < 0.6)
    sel = free() & tint & (N[:, 2] > 0.05) & (np.abs(X) < ws["half_width"] + 0.1) & (Y > ws["y"][0]) & (Y < ws["y"][1]) \
        & (Z > ws["z"][0]) & (Z < ws["z"][1] + 0.05)
    label[sel] = "windscreen"
    for key, nm in (("door_front", "window_front"), ("door_rear", "window_rear")):
        sel = free() & tint & (np.abs(X) > 0.45) & (Y > 0.95) & inside(o[key], Z, Y)
        names = np.where((nm == "window_rear") & (Z[sel] < -0.998), "window_quarter", nm)
        label[sel] = [f"{n}_{sd}" for n, sd in zip(names, side_of[sel])]
    sel = free() & tint & (Z < -1.4) & (Y > 1.0) & inside(o["tailgate"], X, Y)
    label[sel] = "tailgate_rear_window"
    # the panels
    for key, nm in (("door_front", "door_front"), ("door_rear", "door_rear")):
        sel = free() & (np.abs(X) > 0.5) & inside(o[key], Z, Y)
        label[sel] = [f"{nm}_{sd}" for sd in side_of[sel]]
    sel = free() & (N[:, 1] > 0.25) & (Y > o["bonnet_low"]) & inside(o["bonnet"], Z, X)
    label[sel] = "bonnet"
    sel = free() & (N[:, 2] < -0.15) & (Z < -1.5) & inside(o["tailgate"], X, Y)
    label[sel] = "tailgate"

    scene = trimesh.Scene()
    counts = {}
    glass = None
    for nm in sorted(set(label)):
        ix = np.where(label == nm)[0]
        counts[nm] = int(len(ix))
        sub = m.submesh([ix], append=True, repair=False)
        if nm.startswith("window") or nm in ("windscreen", "tailgate_rear_window"):
            if glass is None:
                glass = trimesh.visual.material.PBRMaterial(**GLASS)
            sub.visual = trimesh.visual.TextureVisuals(uv=sub.visual.uv, material=glass)
        scene.add_geometry(sub, node_name=nm, geom_name=nm)
    scene.export(dst)
    return {"scale_per_m": round(float(s), 4), "nose": "+Z" if f > 0 else "-Z (turned)",
            "wheelbase_m": round(float(axles[0] - axles[1]), 3), "parts": counts, "wrote": dst}


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    print(json.dumps(cut(*sys.argv[1:]), indent=1))
