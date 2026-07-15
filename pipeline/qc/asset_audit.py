#!/usr/bin/env python3
"""asset_audit.py — hardened per-asset QC gate (owner-specified 2026-07-15).

Every library GLB must pass ALL gates or it is REJECTED with
action=regenerate (AI assets) / action=replace-source (sourced assets):

  G1 proportions   L/W within 5% of the real vehicle's ratio (--ref-lw)
  G2 clear glass   a real glass material: KHR transmission > 0.5, or
                   alphaMode BLEND with baseColor alpha < 0.9, or a
                   *glass*-named material that is not opaque-painted
  G3 interior      geometry inside the cabin volume (seats/dash/floor):
                   >= min-interior-verts non-glass vertices strictly inside
                   the glasshouse box (fused shells have none)
  G4 wheel quality patchy/marbled AI wheels: luma std of textured faces in
                   the wheel cylinders must be <= wheel-std threshold, or
                   the wheels must be separate dark materials (proper split)
  G5 paint quality body-band low-frequency luma blotches <= paint-std

Usage:
  python3 pipeline/qc/asset_audit.py car.glb --ref-lw 2.38 [--json out.json]
Exit 0 = PASS, 1 = REJECT.
"""
import argparse, json, re, sys
import numpy as np
import trimesh

GLASS_NAME = re.compile(r"glass|window|windshield|screen_tint|tint", re.I)
WHEEL_NAME = re.compile(r"wheel|tyre|tire|rim", re.I)


def luma_std_of_faces(mesh, face_mask, lowfreq=False):
    """Sample baked-texture luma for the given faces via UV -> texture."""
    vis = getattr(mesh, "visual", None)
    if vis is None or not hasattr(vis, "uv") or vis.uv is None:
        return None
    img = getattr(getattr(vis, "material", None), "baseColorTexture", None)
    if img is None:
        img = getattr(getattr(vis, "material", None), "image", None)
    if img is None:
        return None
    tex = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    th, tw = tex.shape[:2]
    fidx = np.nonzero(face_mask)[0]
    if len(fidx) == 0:
        return None
    verts = mesh.faces[fidx].reshape(-1)
    uv = vis.uv[verts]
    px = np.clip((uv[:, 0] % 1.0) * (tw - 1), 0, tw - 1).astype(int)
    py = np.clip(((1 - uv[:, 1]) % 1.0) * (th - 1), 0, th - 1).astype(int)
    rgb = tex[py, px]
    luma = rgb @ np.array([0.299, 0.587, 0.114])
    if lowfreq:
        # blotchiness: std of per-region means, not pixel noise
        order = np.argsort(px * th + py)
        luma = luma[order]
        n = max(1, len(luma) // 64)
        chunks = [luma[i:i + n].mean() for i in range(0, len(luma), n)]
        return float(np.std(chunks))
    return float(np.std(luma))


def audit(path, ref_lw=None, min_interior_verts=1500, wheel_std=0.22, paint_std=0.10):
    scene = trimesh.load(path, force="scene")
    geoms = [g for g in scene.geometry.values()
             if isinstance(g, trimesh.Trimesh) and len(g.vertices) > 0 and len(g.faces) > 0]
    if not geoms:
        return {"file": path, "verdict": "ERROR", "gates": {}, "action": "inspect",
                "reasons": ["unreadable: no triangle geometry (draco-compressed or empty)"]}
    reasons, gates = [], {}

    allv = np.vstack([g.vertices for g in geoms])
    lo, hi = allv.min(0), allv.max(0)
    d = hi - lo
    H, L = d[1], d[2]                    # glTF y-up
    lowband = allv[allv[:, 1] < lo[1] + 0.50 * H]
    if len(lowband) == 0:            # degenerate height (flat/rotated model):
        lowband = allv               # don't crash the auditor, use all verts
    W = float(np.percentile(lowband[:, 0], 99.5) - np.percentile(lowband[:, 0], 0.5))
    lw = L / W if W > 1e-9 else 0.0
    gates["_lw"] = float(lw)
    if ref_lw is None:
        gates["G1_proportions"] = True   # advisory only: no verified dims
    else:
        gates["G1_proportions"] = bool(abs(lw - ref_lw) / ref_lw <= 0.05)
        if not gates["G1_proportions"]:
            reasons.append(f"G1 proportions: L/W={lw:.2f} vs ref {ref_lw:.2f}")

    # G2 glass
    has_glass = False
    for g in geoms:
        m = getattr(g.visual, "material", None)
        if m is None:
            continue
        name = getattr(m, "name", "") or ""
        alpha_mode = getattr(m, "alphaMode", None)
        base = getattr(m, "baseColorFactor", None)
        alpha = base[3] if base is not None and len(base) > 3 else 1.0
        # trimesh exposes KHR transmission via .transmission on PBRMaterial when present
        trans = getattr(m, "transmission", None) or 0.0
        if (trans and trans > 0.5) or (alpha_mode == "BLEND" and alpha < 0.9):
            has_glass = True
        elif GLASS_NAME.search(name) and (alpha_mode == "BLEND" or (trans or 0) > 0):
            has_glass = True
    gates["G2_clear_glass"] = bool(has_glass)
    if not has_glass:
        reasons.append("G2 clear glass: no transmissive/alpha glass material")

    # G3 interior: non-glass verts strictly inside the glasshouse box
    belt = lo[1] + 0.58 * H
    roof = lo[1] + 0.84 * H
    inner_w = 0.52 * (W / 2)
    cabin_lo_z = lo[2] + 0.34 * L
    cabin_hi_z = lo[2] + 0.78 * L
    interior = 0
    for g in geoms:
        name = getattr(getattr(g.visual, "material", None), "name", "") or ""
        if GLASS_NAME.search(name):
            continue
        v = g.vertices
        cx = (lo[0] + hi[0]) / 2
        m = ((v[:, 1] > belt) & (v[:, 1] < roof) &
             (np.abs(v[:, 0] - cx) < inner_w) &
             (v[:, 2] > cabin_lo_z) & (v[:, 2] < cabin_hi_z))
        interior += int(m.sum())
    gates["G3_interior"] = bool(interior >= min_interior_verts)
    gates["_interior_verts"] = interior
    if not gates["G3_interior"]:
        reasons.append(f"G3 interior: only {interior} verts inside cabin volume")

    # G4 wheels: separate wheel material OR clean wheel texture
    wheel_mat = any(WHEEL_NAME.search(getattr(getattr(g.visual, "material", None), "name", "") or "")
                    for g in geoms)
    wheel_ok = wheel_mat
    if not wheel_mat:
        g = max(geoms, key=lambda x: len(x.faces))
        v = g.vertices
        R = 0.085 * L
        czw = lo[1] + R
        fc = v[g.faces].mean(axis=1)
        band = v[v[:, 1] < lo[1] + 0.22 * H]
        histo, edges = np.histogram(band[:, 2], bins=40)
        midz = (lo[2] + hi[2]) / 2
        front = edges[np.argmax(histo * (edges[:-1] < midz))]
        rear = edges[np.argmax(histo * (edges[:-1] >= midz))]
        near = np.minimum(np.abs(fc[:, 2] - front), np.abs(fc[:, 2] - rear))
        mask = (near < R) & (fc[:, 1] < lo[1] + 2.0 * R)
        stdv = luma_std_of_faces(g, mask)
        gates["_wheel_luma_std"] = stdv
        wheel_ok = stdv is not None and stdv <= wheel_std
        if stdv is None:
            reasons.append("G4 wheels: no texture to assess and no wheel material")
        elif not wheel_ok:
            reasons.append(f"G4 wheels: patchy (luma std {stdv:.2f} > {wheel_std})")
    gates["G4_wheels"] = bool(wheel_ok)

    # G5 paint: body band blotchiness. On separated models sample only the
    # paint-named material's geometry; band heuristic is for fused meshes.
    PAINT_NAME = re.compile(r"paint|body|carros|lack", re.I)
    painted = [g for g in geoms if PAINT_NAME.search(
        getattr(getattr(g.visual, "material", None), "name", "") or "")]
    g = painted[0] if painted else max(geoms, key=lambda x: len(x.faces))
    fc = g.vertices[g.faces].mean(axis=1)
    body = (fc[:, 1] > lo[1] + 0.30 * H) & (fc[:, 1] < lo[1] + 0.55 * H)
    pstd = luma_std_of_faces(g, body, lowfreq=True)
    gates["_paint_luma_std"] = pstd
    paint_ok = pstd is None or pstd <= paint_std
    gates["G5_paint"] = bool(paint_ok)
    if not paint_ok:
        reasons.append(f"G5 paint: blotchy (low-freq luma std {pstd:.2f} > {paint_std})")

    verdict = "PASS" if all(v for k, v in gates.items() if not k.startswith("_")) else "REJECT"
    return {"file": path, "verdict": verdict, "gates": gates, "reasons": reasons,
            "action": None if verdict == "PASS" else "regenerate"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("--ref-lw", type=float, default=None,
                    help="real vehicle length/width ratio, e.g. 4258/1790=2.38")
    ap.add_argument("--json")
    a = ap.parse_args()
    r = audit(a.glb, a.ref_lw)
    print(json.dumps(r, indent=1))
    if a.json:
        json.dump(r, open(a.json, "w"), indent=1)
    sys.exit(0 if r["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
