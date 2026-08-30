#!/usr/bin/env python3
"""libmeasure.py — measure ONE library car; emit a JSON row of reference data.

OWNER ORDER 2026-08-30, verbatim intent: "get all the library and measure
them all as reference — glass, pillar, everything — make an average and a
proper pipeline. No more guessing. Tripo is the mesh; we do the rest."

This is the per-car half. It never fabricates: every measure that cannot be
made on a car is emitted as null with a reason, and the aggregator works on
whatever survives. Robust statistics downstream (median, p10-p90) are the
defence against the junk that a 1,044-car sweep will inevitably contain —
scans, clay shells, mislabelled glazing — so this tool prefers an honest
null over a clever recovery.

Frame: measured in the file's own axes. Length axis = longest horizontal
extent (catalogue cars are length-on-Z, machine cars length-on-X — both
have Y up). All positions are FRACTIONS of length from the NOSE and
fractions of height from the floor, so rows are comparable across scale
conventions (the catalogue spans five orders of magnitude of authored
scale — measured 2026-08-21).

Nose = the end whose extreme 6% is LOWER (a bonnet end sits lower than a
tailgate end). Recorded with the margin so weak calls can be filtered.

Draco: trimesh silently returns ZERO vertices on Draco files (recorded
trap), so files declaring KHR_draco_mesh_compression are decompressed via
gltf-transform first, and a zero-vertex share check backstops it.

Run: python3 libmeasure.py <car.glb> [--id assetId]   -> JSON on stdout
"""
import json
import os
import struct
import subprocess
import sys
import tempfile

import numpy as np
import trimesh

GLASSY = ("glass", "window", "windscreen", "windshield", "screen",
          "vidro", "glas", "scheibe", "fenster")
# names that CONTAIN a glassy substring and are not glazing — every entry
# here was paid for on a real car (see CLAUDE.md: touchscreen, glass_surr,
# icon sheets, mirror glass)
NOT_GLASS = ("surr", "icon", "button", "instrument", "dash", "aircondit",
             "mirror", "rearview", "touchscreen", "sunscreen", "lamp",
             "light", "headl", "taill", "fog", "washer",
             # the mk7 control car scored scuttle 0.051 (headlamp lenses at
             # the nose voting as windscreen) and glass/L^2 0.317 vs its
             # known 0.181 (GlassInside_* double-skin counted twice) before
             # these three:
             "inside", "inner", "interior",
             # red glass is a tail lamp on every car ever made
             "glassred", "redglass", "red_glass", "glass_red")
TYREY = ("tyre", "tire", "pneu", "rubber")
RIMY = ("rim", "wheel", "alloy", "felge", "llanta", "cerchio")


def gltf_json(path):
    d = open(path, "rb").read()
    if d[:4] != b"glTF":
        return {}
    n = struct.unpack("<I", d[12:16])[0]
    return json.loads(d[20:20 + n])


def is_glass(name):
    s = name.lower()
    return any(g in s for g in GLASSY) and not any(x in s for x in NOT_GLASS)


def load_parts(path):
    """[(material_name, world-space Trimesh)] with node transforms baked."""
    j = gltf_json(path)
    mats = [m.get("name", "") or "" for m in j.get("materials", [])]
    mesh2mat = {}
    for i, me in enumerate(j.get("meshes", [])):
        pr = me.get("primitives", [{}])[0]
        nm = me.get("name", f"mesh_{i}")
        mi = pr.get("material")
        mesh2mat[nm] = mats[mi] if mi is not None and mi < len(mats) else ""
    sc = trimesh.load(path, force="scene")
    out = []
    for node in sc.graph.nodes_geometry:
        T, g = sc.graph[node]
        m = sc.geometry[g]
        if not isinstance(m, trimesh.Trimesh) or len(m.faces) == 0:
            continue                    # Path3D / point clouds break .area
        m = m.copy()
        if T is not None:
            m.apply_transform(T)
        # material: glTF mesh name first, then trimesh's own record, then
        # the geometry name itself (assembled machine cars name nodes by
        # material)
        mat = mesh2mat.get(g) or getattr(
            getattr(m.visual, "material", None), "name", "") or g
        out.append((str(mat), m))
    return out


def measure(path, asset_id=""):
    r = {"assetId": asset_id, "ok": False}
    parts = load_parts(path)
    if not parts:
        r["error"] = "no geometry"
        return r
    allm = trimesh.util.concatenate([m for _, m in parts])
    v = np.asarray(allm.vertices)
    if len(v) < 1000:
        r["error"] = f"only {len(v)} vertices"
        return r
    if float((np.abs(v).sum(axis=1) < 1e-12).mean()) > 0.10:
        r["error"] = "zero-vertex share >10% — draco decode failure"
        return r
    lo, hi = v.min(axis=0), v.max(axis=0)
    ext = hi - lo
    LA = 0 if ext[0] >= ext[2] else 2          # length axis (Y is always up)
    WA = 2 if LA == 0 else 0
    L, W, H = float(ext[LA]), float(ext[WA]), float(ext[1])
    r.update(length_axis="xyz"[LA], L=L, W_over_L=W / L, H_over_L=H / L,
             faces=int(len(allm.faces)))
    if not (0.30 < W / L < 0.75 and 0.18 < H / L < 0.62):
        r["error"] = "proportions are not a car"
        return r

    # ---- nose: the lower extreme end --------------------------------------
    lf = (v[:, LA] - lo[LA]) / L
    end_a = float(v[lf < 0.06][:, 1].max())
    end_b = float(v[lf > 0.94][:, 1].max())
    nose_at_min = end_a < end_b
    fz = lf if nose_at_min else 1.0 - lf       # fraction from NOSE
    fy = (v[:, 1] - lo[1]) / H
    r["nose_margin_H"] = round(abs(end_a - end_b) / H, 3)

    # ---- roof profile -----------------------------------------------------
    prof = {}
    for k in range(20):
        s = fy[(fz >= k / 20) & (fz < (k + 1) / 20)]
        if len(s) > 50:
            prof[f"{k/20:.2f}"] = round(float(np.percentile(s, 99.9)), 3)
    r["roof_profile"] = prof

    # ---- glazing ----------------------------------------------------------
    gl = [m for n, m in parts if is_glass(n)]
    if gl:
        g = trimesh.util.concatenate(gl)
        gv = np.asarray(g.vertices)
        gfz = (gv[:, LA] - lo[LA]) / L
        if not nose_at_min:
            gfz = 1.0 - gfz
        gfy = (gv[:, 1] - lo[1]) / H
        r["glass_area_over_L2"] = round(float(g.area) / (L * L), 4)
        # UPPER-HALF FENCE: the mk7 control read beltline 0.194 H because
        # door glass extends INSIDE the door cavity — the pane below the
        # beltline is real geometry and must not vote (same fence carspec
        # needed on 2026-08-29 for the same reason)
        up = gfy > 0.45
        if up.sum() > 300:
            ws = (gfz < 0.5) & up
            bl = (gfz > 0.6) & up
            # PLAUSIBILITY BANDS instead of name whack-a-mole: the mk7
            # control scored scuttle 0.09 because its headlamp covers are
            # named GlassClear — and "clear" cannot be excluded by name
            # since on most cars GlassClear IS the glazing. A windscreen
            # base lives at 0.15-0.45 of length on every car; outside that
            # the measurement is contaminated and is REJECTED to null with
            # the raw value kept for the post-mortem.
            if ws.sum() > 100:
                band = gfy[ws] < np.percentile(gfy[ws], 6)
                s = round(float(np.median(gfz[ws][band])), 3)
                if 0.15 < s < 0.45:
                    r["scuttle_frac_from_nose"] = s
                    r["ws_base_frac_H"] = round(float(np.percentile(gfy[ws], 2)), 3)
                else:
                    r["scuttle_rejected"] = s
            if bl.sum() > 100:
                band = gfy[bl] < np.percentile(gfy[bl], 8)
                b = round(float(np.median(gfz[bl][band])), 3)
                if 0.75 < b < 0.99:
                    r["backlight_frac_from_nose"] = b
                else:
                    r["backlight_rejected"] = b
            # beltline off SIDE glass faces
            gc, gn = g.triangles_center, g.face_normals
            gcy = (gc[:, 1] - lo[1]) / H
            side = (np.abs(gn[:, WA]) > 0.6) & (gcy > 0.45)
            if side.sum() > 200:
                sy = gcy[side]
                r["beltline_frac"] = round(float(np.percentile(sy, 2)), 3)
                r["rail_frac"] = round(float(np.percentile(sy, 98)), 3)
                # ---- pillar widths: gaps in side-glass x coverage --------
                sx = np.sort(gc[side][:, LA])
                sxf = (sx - lo[LA]) / L
                if not nose_at_min:
                    sxf = np.sort(1.0 - sxf)
                # a PILLAR is a gap in side-glass coverage of 1-8% of L
                # inside the DLO span; wider gaps are missing glazing
                # labels, not pillars, and are excluded rather than
                # papered over
                gaps = []
                d = np.diff(sxf)
                for i in np.where(d > 0.010)[0]:
                    if 0.30 < sxf[i] < 0.92 and d[i] < 0.08:
                        gaps.append((round(float(sxf[i]), 3),
                                     round(float(d[i]), 4)))
                r["pillar_gaps_frac"] = gaps[:8]        # (position, width /L)
    else:
        r["glass"] = None

    # ---- wheels / stance --------------------------------------------------
    ty = [m for n, m in parts if any(t in n.lower() for t in TYREY)]
    if ty:
        t = np.vstack([np.asarray(m.vertices) for m in ty])
        r["tyre_radius_over_H"] = round(
            float((np.percentile(t[:, 1], 99) - t[:, 1].min()) / 2 / H), 3)
        # wheelbase from tyre x clusters
        txf = (t[:, LA] - lo[LA]) / L
        if not nose_at_min:
            txf = 1.0 - txf
        front = txf[txf < 0.5]
        rear = txf[txf >= 0.5]
        if len(front) > 50 and len(rear) > 50:
            r["axle_front_frac"] = round(float(np.median(front)), 3)
            r["axle_rear_frac"] = round(float(np.median(rear)), 3)
        floor = t[:, 1].min() - lo[1]
        r["tyre_drop_mm_per_L"] = round(float(floor / L * 1000), 2)

    # ---- material area shares --------------------------------------------
    shares = {}
    tot = float(allm.area)
    for n, m in parts:
        k = ("glass" if is_glass(n) else
             "tyre" if any(t in n.lower() for t in TYREY) else
             "rim" if any(t in n.lower() for t in RIMY) else "other")
        shares[k] = shares.get(k, 0.0) + float(m.area)
    r["area_share"] = {k: round(x / tot, 4) for k, x in shares.items()}
    r["ok"] = True
    return r


def maybe_decompress(path):
    j = gltf_json(path)
    exts = (j.get("extensionsRequired") or []) + (j.get("extensionsUsed") or [])
    if "KHR_draco_mesh_compression" not in exts:
        return path
    out = path + ".unc.glb"
    p = subprocess.run(["npx", "--yes", "@gltf-transform/cli", "copy",
                        path, out], capture_output=True, timeout=300)
    if p.returncode != 0 or not os.path.exists(out):
        return None
    return out


if __name__ == "__main__":
    path = sys.argv[1]
    aid = ""
    for i, a in enumerate(sys.argv):
        if a == "--id":
            aid = sys.argv[i + 1]
    p2 = maybe_decompress(path)
    if p2 is None:
        print(json.dumps({"assetId": aid, "ok": False,
                          "error": "draco decompress failed"}))
        sys.exit(0)
    try:
        row = measure(p2, aid)
    except Exception as e:
        row = {"assetId": aid, "ok": False,
               "error": f"{type(e).__name__}: {e}"}
    if p2 != path and os.path.exists(p2):
        os.remove(p2)
    print(json.dumps(row))
