#!/usr/bin/env python3
"""wheel_stage.py — STAGE 1, built as car-agnostic software.

Owner standard (2026-08-18): the machine must be able to do ANY car.
This module replaces wheel_master.py + wheel_gate.py, whose sources
carried the Golf's numbers as literals. Here:

  * every car-specific value comes from a CarSpec JSON (see carspec.py)
    or is MEASURED from the geometry and tagged "approximate"
  * wheel positions come from GEOMETRIC ARCH DETECTION on the body shell
    (sill-interruption profile), not from labelled helper nodes — a raw
    body with visible wheel openings is enough
  * the master wheel assembly is parametrised by the tyre spec string
    (e.g. "225/45R17"); rim/hub/disc/caliper scale from it
  * the numeric gates are computed FROM THE EXPORTED FILE and written to
    wheel_qc.json with per-value provenance

Pipeline: strip old wheel system -> detect arches -> (self-test vs
spec.expect when present) -> cut fused melt from tyre swept volumes ->
build master -> instance 4x (right = translation, left = 180deg yaw,
det +1) -> liners -> export -> verify.

Run: python3 wheel_stage.py <in.glb> <spec.json|-> <out.glb> <qc.json>
     ('-' = no spec: everything measured, all approximate)
"""
import json
import os
import struct
import sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

from carspec import CarSpec

SEG = 96                      # radial resolution of revolved parts
GROUND_EPS = 1e-4


# ---------------------------------------------------------------- geometry
def ring(profile, seg=SEG):
    """Revolve a CLOSED (r, z) profile loop around +Z -> watertight solid."""
    profile = np.asarray(profile, float)
    npts = len(profile)
    th = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    V = np.empty((seg * npts, 3))
    for i, t in enumerate(th):
        V[i * npts:(i + 1) * npts, 0] = profile[:, 0] * np.cos(t)
        V[i * npts:(i + 1) * npts, 1] = profile[:, 0] * np.sin(t)
        V[i * npts:(i + 1) * npts, 2] = profile[:, 1]
    F = []
    for i in range(seg):
        i2 = (i + 1) % seg
        for k in range(npts):
            k2 = (k + 1) % npts
            a, b = i * npts + k, i * npts + k2
            c2, d = i2 * npts + k, i2 * npts + k2
            F += [[a, b, d], [a, d, c2]]
    m = trimesh.Trimesh(vertices=V, faces=F, process=True)
    m.fix_normals()
    assert m.is_watertight, "ring profile must revolve watertight"
    return m


def arc_sweep(profile, th0, th1, seg=48):
    profile = np.asarray(profile, float)
    npts = len(profile)
    th = np.radians(np.linspace(th0, th1, seg))
    V = np.empty((seg * npts, 3))
    for i, t in enumerate(th):
        V[i * npts:(i + 1) * npts, 0] = profile[:, 0] * np.cos(t)
        V[i * npts:(i + 1) * npts, 1] = profile[:, 0] * np.sin(t)
        V[i * npts:(i + 1) * npts, 2] = profile[:, 1]
    F = []
    for i in range(seg - 1):
        for k in range(npts):
            k2 = (k + 1) % npts
            a, b = i * npts + k, i * npts + k2
            c2, d2 = (i + 1) * npts + k, (i + 1) * npts + k2
            F += [[a, b, d2], [a, d2, c2]]
    for base, flip in ((0, False), ((seg - 1) * npts, True)):
        for k in range(1, npts - 1):
            tri = [base, base + k, base + k + 1]
            F.append(tri[::-1] if flip else tri)
    m = trimesh.Trimesh(vertices=V, faces=F, process=True)
    m.fix_normals()
    return m


def build_master(tyre):
    """Master wheel assembly from parsed tyre dims. Origin at hub centre,
    axis +Z, outboard +Z, scale 1. Proportions scale from the tyre."""
    R, w2, Rr = tyre["radius_m"], tyre["width_m"] / 2, tyre["rim_r_m"]
    lip = Rr * 1.031
    barrel_in = Rr * 0.862
    parts = {}
    parts["TYRE_MASTER"] = ring([
        (Rr * 0.95, +w2), (R * 0.90, +w2), (R * 0.965, +w2 * 0.93),
        (R, +w2 * 0.66), (R, -w2 * 0.66), (R * 0.965, -w2 * 0.93),
        (R * 0.90, -w2), (Rr * 0.95, -w2)])
    bw = w2 * 0.78
    barrel = ring([(lip, +bw * 1.14), (Rr, +bw), (Rr, -bw), (lip, -bw * 1.14),
                   (lip, -bw * 1.21), (barrel_in, -bw * 1.07),
                   (barrel_in, +bw * 1.07), (lip, +bw * 1.21)])
    spokes = []
    dish_z = w2 * 0.41
    for k in range(10):
        b = trimesh.creation.box(extents=[barrel_in - Rr * 0.30, Rr * 0.157, Rr * 0.111])
        b.apply_translation([Rr * 0.31 + (barrel_in - Rr * 0.30) / 2, 0, dish_z])
        b.apply_transform(trimesh.transformations.rotation_matrix(
            k * 2 * np.pi / 10, [0, 0, 1]))
        spokes.append(b)
    sring = ring([(barrel_in + 0.002, dish_z * 1.27), (Rr * 0.787, dish_z * 0.88),
                  (Rr * 0.787, dish_z * 0.61), (barrel_in + 0.002, dish_z * 0.88)])
    parts["RIM_MASTER"] = trimesh.util.concatenate([barrel, sring] + spokes)
    hub_r = Rr * 0.315
    hub = trimesh.creation.cylinder(radius=hub_r, height=w2 * 0.27, sections=48)
    hub.apply_translation([0, 0, dish_z * 0.96])
    cap = trimesh.creation.cylinder(radius=hub_r * 0.44, height=0.010, sections=48)
    cap.apply_translation([0, 0, dish_z * 1.35])
    lugs = []
    for k in range(5):
        lg = trimesh.creation.cylinder(radius=hub_r * 0.13, height=0.014, sections=16)
        a = k * 2 * np.pi / 5
        lg.apply_translation([hub_r * 0.82 * np.cos(a), hub_r * 0.82 * np.sin(a),
                              dish_z * 1.26])
        lugs.append(lg)
    parts["HUB_MASTER"] = trimesh.util.concatenate([hub, cap] + lugs)
    Rd = Rr * 0.718
    parts["BRAKE_DISC_MASTER"] = ring([(Rd * 0.516, -0.008), (Rd, -0.008),
                                       (Rd, -0.030), (Rd * 0.516, -0.030)])
    cal = trimesh.creation.box(extents=[Rd * 0.48, Rd * 0.77, 0.052])
    cal.apply_translation([Rd * 0.855, 0, -0.019])
    cal.apply_transform(trimesh.transformations.rotation_matrix(
        np.radians(115), [0, 0, 1]))
    parts["BRAKE_CALIPER_MASTER"] = cal
    return parts


# ---------------------------------------------------------------- detection
def detect_arches(v, report, strict=True):
    """Find the four wheel openings GEOMETRICALLY: the wheel arch is where
    the side skin's lower edge (the sill line) jumps upward. No labels.

    Returns dict with front/rear axle x (symmetrised), per-side raw values,
    and the measured arch apex height (an upper bound related to tyre fit).
    """
    gy = float(v[:, 1].min())
    H = float(np.percentile(v[:, 1], 99.8)) - gy
    HW = float(np.percentile(np.abs(v[:, 2]), 99.7))
    L0, L1 = float(v[:, 0].min()), float(v[:, 0].max())
    nb = 120
    edges = np.linspace(L0, L1, nb + 1)
    sides = {}
    for sname, zsign in (("right", 1), ("left", -1)):
        pts = v[(np.sign(v[:, 2]) == zsign) & (np.abs(v[:, 2]) > 0.62 * HW)
                & (v[:, 1] < gy + 0.62 * H)]
        prof = np.full(nb, np.nan)
        idx = np.clip(np.searchsorted(edges, pts[:, 0]) - 1, 0, nb - 1)
        for b in range(nb):
            sel = idx == b
            if sel.any():
                prof[b] = pts[sel, 1].min()
        ok = ~np.isnan(prof)
        base = np.nanpercentile(prof[ok], 30)          # sill height
        lift = prof - base
        lifted = ok & (lift > 0.15 * H)   # openings lift ~0.3H; bumper/trim clearance ~0.08H — 0.15H separates them (measured: 0.05H merged the left rear arch into the tail)
        # CLOSE small gaps: hanging melt teeth inside an opening drop single
        # bins back to sill level and split/truncate the run (measured: a
        # tooth at x=1.264 cut the front arch run short and biased the
        # centre 90mm rearward, tripping the self-test). Fill gaps <= 2 bins.
        # fill gaps of <= 3 consecutive unlifted bins BETWEEN lifted bins,
        # in ONE deterministic pass (an iterative version compounded and
        # merged separate openings — self-test caught front x at 0.04 with
        # 2.4m asymmetry). Melt teeth measured up to 3 bins wide.
        # ERODE single-bin noise lifts first: an isolated lifted bin between
        # the rear arch and the tail let gap-filling chain them into one
        # 32-bin mega-run (runs printout, left side). Open-then-close.
        lifted = lifted.copy()
        b = 0
        while b < nb:
            if lifted[b]:
                r0 = b
                while b < nb and lifted[b]:
                    b += 1
                if (b - r0) < 2:
                    lifted[r0:b] = False
            else:
                b += 1
        closed = lifted.copy()
        b = 0
        while b < nb:
            if not closed[b]:
                g0 = b
                while b < nb and not closed[b]:
                    b += 1
                if g0 > 0 and b < nb and (b - g0) <= 3:
                    closed[g0:b] = True
            else:
                b += 1
        runs, cur = [], None
        for b in range(nb):
            if closed[b]:
                cur = [b, b] if cur is None else [cur[0], b]
            else:
                if cur and cur[1] - cur[0] >= 3:
                    runs.append(cur)
                cur = None
        if cur and cur[1] - cur[0] >= 3:
            runs.append(cur)
        # SELECTION: one opening per car half — "two longest" failed when a
        # merged rear mega-run displaced the front arch (self-test caught
        # it). A wheel opening also cannot exceed 25% of car length; longer
        # runs are contamination and are reported, not used.
        Lcar = L1 - L0
        maxbins = int(0.25 * nb)
        midx = (L0 + L1) / 2
        cands = []
        for r in runs:
            cx = (edges[r[0]] + edges[r[1] + 1]) / 2
            cands.append({"b": r, "x": cx, "len": r[1] - r[0] + 1})
        dbg = [f"x={c['x']:+.2f} len={c['len']}" for c in cands]
        print(f"  side {sname}: runs {dbg}")
        cams = []
        for half, sel in (("front", lambda c: c["x"] > midx),
                          ("rear", lambda c: c["x"] <= midx)):
            pool = [c for c in cands if sel(c) and c["len"] <= maxbins]
            if not pool:
                msg = (f"arch detection: no plausible {half} opening on side "
                       f"{sname} (runs: {dbg})")
                if strict:
                    raise SystemExit(msg + " — inspect the body input")
                print(msg + " — falling back to fused-wheel detection")
                return None
            best = max(pool, key=lambda c: c["len"])
            b0, b1 = best["b"]
            # centre estimator = APEX POSITION, not extent midpoint: melt
            # occludes the openings asymmetrically (measured: extent
            # midpoints were 89-108mm off with 90-108mm L/R asymmetry),
            # but melt hangs at the opening EDGES — the apex survives.
            # Side-averaged apex-x reproduced the labelled positions to
            # 8mm on this body.
            pk = b0 + int(np.nanargmax(prof[b0:b1 + 1]))
            cams.append({"x": float((edges[pk] + edges[pk + 1]) / 2),
                         "apex_y": float(np.nanmax(prof[b0:b1 + 1]))})
        sides[sname] = sorted(cams, key=lambda c: -c["x"])
    if any(len(s) < 2 for s in sides.values()):
        raise SystemExit(f"arch detection failed: found "
                         f"{ {k: len(s) for k, s in sides.items()} } openings "
                         "(need 2 per side) — inspect the body input")
    front = {k: s[0] for k, s in sides.items()}
    rear = {k: s[1] for k, s in sides.items()}
    det = {
        "method": "sill-interruption profile (geometric, label-free)",
        "front_x": round((front["right"]["x"] + front["left"]["x"]) / 2, 4),
        "rear_x": round((rear["right"]["x"] + rear["left"]["x"]) / 2, 4),
        "front_x_per_side": {k: round(c["x"], 4) for k, c in front.items()},
        "rear_x_per_side": {k: round(c["x"], 4) for k, c in rear.items()},
        "front_asym_mm": round(1000 * abs(front["right"]["x"] - front["left"]["x"]), 1),
        "rear_asym_mm": round(1000 * abs(rear["right"]["x"] - rear["left"]["x"]), 1),
        "arch_apex_y_mean": round(float(np.mean([c["apex_y"] for c in
                                   list(front.values()) + list(rear.values())])), 4),
        "ground_y": round(gy, 5), "half_width": round(HW, 4),
    }
    report["arch_detection"] = det
    print(f"arches: front x {det['front_x']} (asym {det['front_asym_mm']}mm), "
          f"rear x {det['rear_x']} (asym {det['rear_asym_mm']}mm), "
          f"apex_y mean {det['arch_apex_y_mean']}")
    return det


def detect_fused_wheels(v, report):
    """FUSED-WHEEL MODE: the wheels are moulded into the shell, so there
    are no arch openings — but the tyres touch the ground. Cluster the
    ground-contact band along x: two clusters = the axles. Track comes
    from the contact patches' own z centroids. Everything derived here is
    APPROXIMATE by definition and tagged so.
    """
    gy = float(v[:, 1].min())
    H = float(np.percentile(v[:, 1], 99.8)) - gy
    HW = float(np.percentile(np.abs(v[:, 2]), 99.7))
    band = v[v[:, 1] < gy + 0.05 * H]
    if len(band) < 100:
        raise SystemExit("fused-wheel detection: no ground-contact band")
    L0, L1 = float(v[:, 0].min()), float(v[:, 0].max())
    nb = 80
    edges = np.linspace(L0, L1, nb + 1)
    hist, _ = np.histogram(band[:, 0], bins=edges)
    on = hist > max(3, 0.02 * hist.max())
    runs, cur = [], None
    for b in range(nb):
        if on[b]:
            cur = [b, b] if cur is None else [cur[0], b]
        else:
            if cur:
                runs.append(cur); cur = None
    if cur:
        runs.append(cur)
    runs = sorted(runs, key=lambda r: -hist[r[0]:r[1] + 1].sum())[:2]
    if len(runs) < 2:
        raise SystemExit(f"fused-wheel detection: found {len(runs)} ground "
                         "clusters (need 2 axles) — inspect the body input")
    cs = []
    for r in sorted(runs, key=lambda r: -(edges[r[0]])):
        m = (band[:, 0] >= edges[r[0]]) & (band[:, 0] <= edges[r[1] + 1])
        pts = band[m]
        cs.append({"x": float(pts[:, 0].mean()),
                   "track": float(np.abs(pts[:, 2]).mean() * 2),
                   "n": int(m.sum())})
    det = {"method": "FUSED-WHEEL ground-contact clustering (APPROXIMATE)",
           "front_x": round(cs[0]["x"], 4), "rear_x": round(cs[1]["x"], 4),
           "front_asym_mm": -1, "rear_asym_mm": -1,
           "track_front_measured": round(cs[0]["track"], 4),
           "track_rear_measured": round(cs[1]["track"], 4),
           "arch_apex_y_mean": round(gy + 0.37 * H, 4),
           "ground_y": round(gy, 5), "half_width": round(HW, 4)}
    report["arch_detection"] = det
    print(f"FUSED mode: axles x {det['front_x']}/{det['rear_x']}, "
          f"contact tracks {det['track_front_measured']}/{det['track_rear_measured']}")
    return det


# ---------------------------------------------------------------- stage
def main():
    inp, spec_path, out_path, qc_path = sys.argv[1:5]
    spec = CarSpec.empty() if spec_path == "-" else CarSpec.load(spec_path)
    report = {"stage": "wheel_stage (car-agnostic)", "input": inp,
              "spec": spec.path, "identity": spec.identity()}

    sc = trimesh.load(inp, force="scene")
    strip = tuple(spec.label("wheel_strip_prefixes",
                  ["Tyre_Rubber", "Rim_Alloy", "disc_", "cal_",
                   "WHEEL_", "Arch_Cavity", "LINER_"]))
    body_label = spec.label("body", "carpaint")
    out = trimesh.Scene()
    removed = []
    stripped_pts = []
    for node in sc.graph.nodes_geometry:
        T, gn = sc.graph[node]
        if any(node.startswith(p) or gn.startswith(p) for p in strip):
            removed.append(node)
            # a fused generated car carries its ONLY axle evidence in the
            # wheel-labelled blob geometry (the body's own underbody is a
            # continuous ground smear — measured on the Yaris hybrid: one
            # ground cluster, both detectors blind). Stripped geometry is
            # kept as DETECTION EVIDENCE only; it never reaches the output.
            g = sc.geometry[gn]
            stripped_pts.append(trimesh.transform_points(g.vertices, T)
                                if T is not None else g.vertices)
            continue
        if gn not in out.geometry:
            out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=node,
                             transform=T)
        else:
            out.graph.update(frame_to=node, matrix=T, geometry=gn)
    report["removed_nodes"] = sorted(set(removed))
    print(f"stripped {len(removed)} old wheel-system nodes")

    skin_names = spec.label("body_skin_nodes", [body_label])
    skin_names = [n for n in skin_names if n in out.geometry]
    if not skin_names:
        # unknown mesh naming (first different-car run crashed here with a
        # bare numpy error): fall back to EVERYTHING that survived the
        # strip, and say so — the spec can name skin nodes once known
        skin_names = list(out.geometry)
        print(f"note: configured body nodes not found; using all "
              f"{len(skin_names)} geometries as skin: {skin_names[:8]}"
              + (" ..." if len(skin_names) > 8 else ""))
    if not skin_names:
        raise SystemExit("no geometry left after strip — nothing to detect on")
    skin_pts = np.vstack([out.geometry[n].vertices for n in skin_names])
    # CANONICAL ORIENTATION: the machine works length-on-X, y-up. Raw
    # generator meshes arrive with length on Z (measured: Hi3DGen ships
    # z-long). Detect by horizontal extents and rotate the WHOLE scene
    # into canon; the transform is recorded in the QC.
    ex = skin_pts[:, 0].max() - skin_pts[:, 0].min()
    ez = skin_pts[:, 2].max() - skin_pts[:, 2].min()
    if ez > ex * 1.15:
        ROT = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])
        for gname in list(out.geometry):
            g = out.geometry[gname]
            g.apply_transform(ROT)
        skin_pts = np.vstack([out.geometry[n].vertices for n in skin_names])
        report["canonicalised"] = "rotated 90deg about Y (length was on Z)"
        print("canonicalised: length was on Z, rotated to X")
    # Z-CENTRING GUARD: everything downstream assumes the car straddles
    # z=0 — detect_arches splits sides by sign(z), placement is +-track/2.
    # A corner-origin mesh (z in [0, W], measured on the Yaris hybrid:
    # wheels placed around the LEFT EDGE, arch detector saw one side)
    # passes every other check silently. Recentre and record.
    zmid = float((skin_pts[:, 2].max() + skin_pts[:, 2].min()) / 2)
    zw = float(skin_pts[:, 2].max() - skin_pts[:, 2].min())
    if abs(zmid) > 0.05 * zw:
        for gname in list(out.geometry):
            out.geometry[gname].apply_translation([0.0, 0.0, -zmid])
        skin_pts = np.vstack([out.geometry[n].vertices for n in skin_names])
        report["z_recentred"] = round(zmid, 4)
        print(f"z-centring guard: mesh straddled z={zmid:+.3f}, recentred to 0")
    print(f"body skin for detection: {skin_names[:6]}"
          + (" ..." if len(skin_names) > 6 else "") + f" ({len(skin_pts)} verts)")
    det = detect_arches(skin_pts, report, strict=False)
    fused_mode = det is None
    if fused_mode:
        # include stripped wheel-labelled geometry as evidence: its tyres
        # touch the road at the two axles, which is exactly the signal the
        # ground-contact clustering needs. Canonicalise it the same way.
        det_pts = skin_pts
        if stripped_pts:
            spx = np.vstack(stripped_pts)
            if report.get("canonicalised"):
                spx = trimesh.transform_points(spx, ROT)
            if report.get("z_recentred"):
                spx = spx - [0.0, 0.0, report["z_recentred"]]
            det_pts = np.vstack([skin_pts, spx])
            report["fused_detection_evidence"] = (
                f"skin + {len(spx)} verts from stripped wheel-labelled nodes")
        det = detect_fused_wheels(det_pts, report)

    exp = spec.expect()
    if exp.get("axle_x"):
        tol = float(exp.get("tolerance_m", 0.06))
        dF = abs(det["front_x"] - exp["axle_x"]["front"])
        dR = abs(det["rear_x"] - exp["axle_x"]["rear"])
        st = "PASS" if (dF < tol and dR < tol) else "FAIL"
        report["detector_self_test"] = {
            "expected": exp["axle_x"], "tolerance_m": tol,
            "delta_front_m": round(dF, 4), "delta_rear_m": round(dR, 4),
            "result": st}
        print(f"detector self-test vs spec.expect: {st} "
              f"(dF {dF*1000:.0f}mm, dR {dR*1000:.0f}mm)")
        if st == "FAIL":
            raise SystemExit("detector self-test FAILED — refusing to place wheels")

    tyre = spec.tyre()
    if tyre is None:
        if fused_mode:
            gyH = det["ground_y"]
            Hcar = float(np.percentile(skin_pts[:, 1], 99.8)) - gyH
            R = 0.218 * Hcar
            src = ("APPROXIMATE — 0.218 x body height heuristic "
                   "(fused wheels: no openings to fit; ratio from real "
                   "hatch proportions)")
        else:
            apex = det["arch_apex_y_mean"] - det["ground_y"]
            R = apex / 1.18
            src = "APPROXIMATE — fitted from arch openings (no spec supplied)"
        tyre = {"spec": f"measured R={R:.3f}", "source": src,
                "width_m": R * 0.71, "radius_m": R, "rim_r_m": R * 0.68,
                "aspect": None}
        print(f"no tyre spec: {src.split(chr(10))[0]} R={R:.3f}")
    report["tyre"] = {k: (round(v, 5) if isinstance(v, float) else v)
                     for k, v in tyre.items()}

    tf, tf_src = spec.dim("track_front_m")
    tr, tr_src = spec.dim("track_rear_m")
    if tf is None and fused_mode and det.get("track_front_measured"):
        tf, tf_src = det["track_front_measured"], \
            "APPROXIMATE — measured from fused ground-contact patches"
    if tf is None:
        tf, tf_src = det["half_width"] * 2 * 0.855, \
            "APPROXIMATE — 0.855 x body width (no spec)"
    if tr is None and fused_mode and det.get("track_rear_measured"):
        tr, tr_src = det["track_rear_measured"], \
            "APPROXIMATE — measured from fused ground-contact patches"
    if tr is None:
        tr, tr_src = tf * 0.981, "APPROXIMATE — from front track (no spec)"
    # FLANK GUARD: spec tracks describe the REAL car; a generated body can
    # be narrower (perspective bake — measured on the Yaris hybrid: flank
    # half-width 0.776 vs real 0.8475, spec track left the tyres 40mm
    # proud of the body). The tyre's outer face must sit inside the body's
    # own arch-zone flank by a small inset; narrow the track when the spec
    # value would poke through, and record it as a deviation from spec.
    gy0 = float(skin_pts[:, 1].min())
    H0 = float(np.percentile(skin_pts[:, 1], 99.8)) - gy0
    Wt = tyre["width_m"] if tyre else 0.18
    for axle, dkey in (("front", "front_x"), ("rear", "rear_x")):
        zone = skin_pts[(np.abs(skin_pts[:, 0] - det[dkey]) < 0.45)
                        & (skin_pts[:, 1] < gy0 + 0.55 * H0)]
        if len(zone) < 200:
            continue
        flank = float(np.percentile(np.abs(zone[:, 2]), 97))
        tmax = 2 * (flank - 0.010 - Wt / 2)
        if axle == "front" and tf > tmax:
            report.setdefault("track_narrowed", {})["front"] = {
                "spec": round(tf, 4), "used": round(tmax, 4),
                "flank_half_width": round(flank, 4)}
            tf, tf_src = tmax, (tf_src + " — NARROWED to the body's own "
                                "arch-zone flank (generated body narrower "
                                "than spec width)")
            print(f"  flank guard: front track {report['track_narrowed']['front']['spec']}"
                  f" -> {tmax:.3f} (flank {flank:.3f})")
        if axle == "rear" and tr > tmax:
            report.setdefault("track_narrowed", {})["rear"] = {
                "spec": round(tr, 4), "used": round(tmax, 4),
                "flank_half_width": round(flank, 4)}
            tr, tr_src = tmax, (tr_src + " — NARROWED to the body's own "
                                "arch-zone flank (generated body narrower "
                                "than spec width)")
            print(f"  flank guard: rear track {report['track_narrowed']['rear']['spec']}"
                  f" -> {tmax:.3f} (flank {flank:.3f})")
    wb_spec, wb_src = spec.dim("wheelbase_m")
    wb_used = det["front_x"] - det["rear_x"]
    report["placement"] = {
        "track_front": {"value": round(tf, 4), "source": tf_src},
        "track_rear": {"value": round(tr, 4), "source": tr_src},
        "wheelbase_used": {"value": round(wb_used, 4),
                           "source": "ARCH-DERIVED (the body's own openings) — "
                                     "APPROXIMATE by definition"},
        "wheelbase_spec": ({"value": wb_spec, "source": wb_src,
                            "deviation_pct": round(100 * (wb_used / wb_spec - 1), 2)}
                           if wb_spec else "not in spec"),
    }

    gy = det["ground_y"]
    R, W = tyre["radius_m"], tyre["width_m"]
    if fused_mode:
        # contact-cluster ground is measured evidence (the original fused
        # tyres' own footprint) — it stays the placement authority here
        CY = gy + R
        report["ride_height"] = {
            "centre_y": round(float(CY), 5),
            "derivation": "fused contact-cluster ground + tyre R (measured)"}
    else:
        # RIDE HEIGHT FROM THE ARCH CEILING, not from min-y "ground".
        # (V53 finding, 2026-08-18, from independent verification: ground_y
        # = raw skin min keyed the whole car's stance to ONE junk melt
        # vertex 175mm below the bumper's real underside. The physical
        # constraint on the wheel is the ARCH CEILING — the lowest skin
        # directly above each wheel column. p5 of the column makes the
        # measure robust to melt teeth; verts below 0.8R can't be a
        # ceiling for a tyre of radius R and are excluded so under-sill
        # junk cannot fake one. 1.02 = apex-above-centre ratio measured on
        # the V41 body (APPROXIMATE): tyre top clears the ceiling by 2%R.)
        ceilings = {}
        for tag, (xc, zc) in (("FR", (det["front_x"], +tf / 2)),
                              ("FL", (det["front_x"], -tf / 2)),
                              ("RR", (det["rear_x"], +tr / 2)),
                              ("RL", (det["rear_x"], -tr / 2))):
            m = (np.abs(skin_pts[:, 0] - xc) < 0.35 * R) & \
                (np.abs(skin_pts[:, 2] - zc) < W / 2)
            ys = skin_pts[m, 1]
            ys = ys[ys > gy + 0.8 * R]
            if len(ys) < 20:
                ceilings = None
                break
            ceilings[tag] = float(np.percentile(ys, 5))
        # robust underside: lowest y with >= 30 verts in the 10mm above it,
        # so ONE junk vertex cannot define the ground (V53: it did)
        ys_all = np.sort(skin_pts[:, 1])
        nhead = min(2000, len(ys_all))
        upper = np.searchsorted(ys_all, ys_all[:nhead] + 0.010)
        dense = np.where(upper - np.arange(nhead) >= 30)[0]
        gy_rob = float(ys_all[dense[0]] if len(dense) else ys_all[0])
        Hsk = float(np.percentile(skin_pts[:, 1], 99.8)) - gy_rob
        if ceilings is None:
            CY = gy_rob + R
            report["ride_height"] = {
                "centre_y": round(float(CY), 5),
                "derivation": "FALLBACK robust underside + R — arch columns "
                              "held too few verts for a ceiling measure"}
        else:
            CY_tuck = min(ceilings.values()) - 1.02 * R
            # underside clearance the tuck would leave. Real cars run
            # ground-clearance/height ~5-13% (Golf 140/1456 = 9.6%); above
            # 15% the "lip" is judged a MELT WEB across the wheel zone —
            # the carve manufactures the opening there, so the body stands
            # on its own underside instead. Measured both ways on 3 bodies
            # 2026-08-18: Golf 4.6% (real lip, tuck), hybrid 21.7% (web,
            # ground), threshold 0.15 x H is APPROXIMATE and recorded.
            clr = gy_rob - (CY_tuck - R)
            if clr > 0.15 * Hsk:
                CY = gy_rob + R
                mode_note = (f"arch-tuck would float the underside "
                             f"{clr*1000:.0f}mm ({100*clr/Hsk:.1f}% of body "
                             "height > 15%) — ceiling judged melt web; "
                             "grounded to robust underside, carve opens the arch")
            elif clr < 0:
                # SUBMERGED underside (measured on the Yaris XP130 source:
                # -9mm): tucking would hang the body below the tyres'
                # contact plane, which is physically impossible — the
                # tyres are the lowest point of a car. Ground instead.
                CY = gy_rob + R
                mode_note = (f"arch-tuck would SUBMERGE the underside "
                             f"{-clr*1000:.0f}mm below the contact plane — "
                             "grounded to robust underside instead")
            else:
                CY = CY_tuck
                mode_note = (f"tucked to arch ceiling (underside clearance "
                             f"{clr*1000:.0f}mm = {100*clr/Hsk:.1f}% of body "
                             "height, plausible)")
            report["ride_height"] = {
                "centre_y": round(float(CY), 5),
                "mode": "tuck" if CY is CY_tuck or CY == CY_tuck else "grounded-web",
                "arch_ceilings": {k: round(v, 5) for k, v in ceilings.items()},
                "underside_robust_y": round(gy_rob, 5),
                "underside_clearance_if_tucked_m": round(float(clr), 5),
                "derivation": "min per-corner arch ceiling (p5 of wheel "
                              "column skin) - 1.02 x R vs robust-underside "
                              "grounding; " + mode_note,
                "ground_y_raw_min": round(float(gy), 5),
                "note": "raw min-y is reported but no longer used for "
                        "placement (junk-vertex immunity)"}
    print(f"ride height: wheel centre y {CY:.4f} "
          f"({report['ride_height']['derivation'].splitlines()[0]})")
    centres = {"FR": (det["front_x"], CY, +tf / 2),
               "FL": (det["front_x"], CY, -tf / 2),
               "RR": (det["rear_x"], CY, +tr / 2),
               "RL": (det["rear_x"], CY, -tr / 2)}

    # fused melt inside the tyre swept volumes (generic version of the
    # wheel_gate cut; margins scale with the tyre)
    total_cut = 0
    for sn in skin_names:
        g = out.geometry[sn]
        v = g.vertices
        f = g.faces
        kill = np.zeros(len(f), bool)
        for tag, (xc, yc, zc) in centres.items():
            inside = (np.abs(v[:, 2] - zc) < W / 2 + 0.005) & \
                     (np.linalg.norm(v[:, :2] - [xc, yc], axis=1) < R + 0.005) & \
                     (v[:, 1] < gy + 2.02 * R)
            kill |= inside[f].any(1)
        if kill.any():
            g.update_faces(~kill)
            g.remove_unreferenced_vertices()
            # cuts expose zero-area faces / isolated verts -> zero-length
            # vertex normals -> validator ACCESSOR_VECTOR3_NON_UNIT.
            tri = g.triangles
            area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                           tri[:, 2] - tri[:, 0]), axis=1)
            if (area < 1e-10).any():
                g.update_faces(area >= 1e-10)
                g.remove_unreferenced_vertices()
            vn = np.array(g.vertex_normals)
            bad = np.linalg.norm(vn, axis=1) < 1e-6
            if bad.any():
                vn[bad] = [0.0, 1.0, 0.0]
                g.vertex_normals = vn
            print(f"  {sn}: cut {kill.sum()} fused faces "
                  f"(+{(area < 1e-10).sum()} degenerate, {bad.sum()} zero-normals fixed)")
            total_cut += int(kill.sum())
    report["fused_faces_cut"] = total_cut
    if fused_mode:
        # POST-CARVE SELF-CHECK — direct: the carved cylinders must be
        # EMPTY of skin geometry. (An opening-based re-detection check
        # failed on a body whose melt arch-lip fringe hangs low enough to
        # keep the sill profile from "seeing" the new openings, while the
        # render showed a perfectly good carve — wrong criterion, changed.)
        sp2 = np.vstack([out.geometry[n].vertices for n in skin_names])
        resid = {}
        for tag, (xc, yc, zc) in centres.items():
            r = np.linalg.norm(sp2[:, :2] - [xc, yc], axis=1)
            resid[tag] = int(((np.abs(sp2[:, 2] - zc) < W / 2) & (r < R)).sum())
        ok = all(v == 0 for v in resid.values())
        report["carve_self_check"] = {"residual_skin_verts_in_carve": resid,
                                      "result": "PASS" if ok else "FAIL"}
        print(f"carve self-check (direct void): {resid} -> "
              f"{'PASS' if ok else 'FAIL'}")

    # ---------------- ground plane: clamp + canonicalise to y=0 ----------
    # Nothing but the tyres may sit below the road. The independent
    # verification (2026-08-18) found 954 underbody-melt verts up to 39mm
    # below the contact plane and a single bumper junk vertex AT it —
    # physically impossible geometry. Verts below the plane are CLAMPED to
    # it (recorded per node); a node needing more than 1% clamped means the
    # grounding itself is wrong, and the stage refuses instead of hiding it.
    plane = CY - R
    clamp_rep = {}
    for gname in list(out.geometry):
        g = out.geometry[gname]
        v2 = g.vertices.copy()
        below = v2[:, 1] < plane - 5e-4
        if not below.any():
            continue
        frac = below.sum() / len(v2)
        if frac > 0.01:
            raise SystemExit(
                f"REFUSED: {gname} has {frac:.1%} of verts below the "
                "contact plane — that is a grounding error, not junk")
        depth = float((plane - v2[below, 1]).max() * 1000)
        v2[below, 1] = plane
        g.vertices = v2
        tri = g.triangles
        area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                       tri[:, 2] - tri[:, 0]), axis=1)
        if (area < 1e-10).any():
            g.update_faces(area >= 1e-10)
            g.remove_unreferenced_vertices()
        vn = np.array(g.vertex_normals)
        bad = np.linalg.norm(vn, axis=1) < 1e-6
        if bad.any():
            vn[bad] = [0.0, 1.0, 0.0]
            g.vertex_normals = vn
        clamp_rep[gname] = {"verts_clamped": int(below.sum()),
                            "max_depth_mm": round(depth, 1)}
        print(f"  ground clamp: {gname} {below.sum()} verts "
              f"(max {depth:.1f}mm below road) raised to the plane")
    # canonical frame: tyre contact = y 0 exactly. The QC rig's checker
    # ground is fixed at y=0, so without this every render floats the car
    # by the old plane offset (39mm on V53 — measured).
    for gname in list(out.geometry):
        out.geometry[gname].apply_translation([0.0, -plane, 0.0])
    skin_pts = np.vstack([out.geometry[n].vertices for n in skin_names])
    CY -= plane
    centres = {t: (xc, CY, zc) for t, (xc, _, zc) in centres.items()}
    report["ground"] = {
        "contact_plane_canonical_y": 0.0,
        "shift_applied_m": round(float(plane), 5),
        "clamped": clamp_rep or "nothing below the plane"}

    MATS = {"TYRE_MASTER": ([12, 12, 14], 0.0, 0.90),
            "RIM_MASTER": ([120, 123, 128], 0.85, 0.35),
            "HUB_MASTER": ([50, 52, 58], 0.60, 0.45),
            "BRAKE_DISC_MASTER": ([120, 121, 124], 0.90, 0.40),
            "BRAKE_CALIPER_MASTER": ([150, 22, 26], 0.20, 0.50)}
    parts = build_master(tyre)
    for pname, m in parts.items():
        col, met, rgh = MATS[pname]
        m.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
            name=pname, baseColorFactor=col + [255], metallicFactor=met,
            roughnessFactor=rgh))
        out.add_geometry(m, node_name=f"WHEEL_FR__{pname}", geom_name=pname)
        print(f"  {pname}: {len(m.faces)}f watertight={m.is_watertight}")

    liner_name = spec.label("liner_name", "ARCH_LINER")
    lr = R * 1.11
    wall = arc_sweep([(lr - 0.008, -W * 0.6), (lr, -W * 0.6),
                      (lr, W * 0.6), (lr - 0.008, W * 0.6)], -15, 195)
    capp = arc_sweep([(R * 0.32, -W * 0.6), (lr - 0.008, -W * 0.6),
                      (lr - 0.008, -W * 0.565), (R * 0.32, -W * 0.565)], -15, 195)
    liner = trimesh.util.concatenate([wall, capp])
    liner.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
        name=liner_name, baseColorFactor=[16, 16, 18, 255],
        metallicFactor=0.0, roughnessFactor=0.95, doubleSided=True))
    out.add_geometry(liner, node_name="LINER_FR", geom_name=liner_name)

    YAW180 = trimesh.transformations.rotation_matrix(np.pi, [0, 1, 0])
    for tag, (xc, yc, zc) in centres.items():
        T = YAW180.copy() if zc < 0 else np.eye(4)
        T[:3, 3] = [xc, yc, zc]
        for pname in parts:
            out.graph.update(frame_to=f"WHEEL_{tag}__{pname}", matrix=T,
                             geometry=pname)
        out.graph.update(frame_to=f"LINER_{tag}", matrix=T, geometry=liner_name)

    out.export(out_path, include_normals=True)

    # ---------------- verify FROM THE EXPORTED FILE ----------------
    with open(out_path, "rb") as fh:
        fh.seek(12)
        ln, _ = struct.unpack("<II", fh.read(8))
        j = json.loads(fh.read(ln))
    missing = [m2.get("name") for m2 in j["meshes"]
               if any("NORMAL" not in p["attributes"] for p in m2["primitives"])]
    if missing:
        raise SystemExit(f"REFUSED: NORMAL missing on {missing[:4]}")
    node_mesh = [(n.get("name"), n.get("mesh")) for n in j["nodes"] if "mesh" in n]
    shared = all(len({mi for n, mi in node_mesh if n and n.endswith(f"__{p}")}) == 1
                 for p in parts)
    sc2 = trimesh.load(out_path, force="scene")
    qcw = {}
    for tag in centres:
        T, _ = sc2.graph[f"WHEEL_{tag}__TYRE_MASTER"]
        tv = trimesh.transform_points(sc2.geometry["TYRE_MASTER"].vertices, T)
        c = T[:3, 3]
        axis = T[:3, :3] @ [0, 0, 1]
        qcw[tag] = {
            "centre": [round(float(x), 5) for x in c],
            "diameter": round(2 * float(np.linalg.norm(tv[:, :2] - c[:2],
                                                       axis=1).max()), 5),
            "width": round(float(tv[:, 2].max() - tv[:, 2].min()), 5),
            "toe_deg": round(float(np.degrees(np.arctan2(abs(axis[0]),
                                                          abs(axis[2])))), 4),
            "camber_deg": round(float(np.degrees(np.arctan2(abs(axis[1]),
                                                             abs(axis[2])))), 4),
            "contact_vs_ground_mm": round(1000 * float(tv[:, 1].min()), 3)}
    if body_label in sc2.geometry:
        cpv = sc2.geometry[body_label].vertices
    else:
        cpv = np.vstack([sc2.geometry[n].vertices for n in sc2.geometry
                         if not n.endswith("_MASTER") and n != "ARCH_LINER"])
    hits = {}
    for tag, (xc, yc, zc) in centres.items():
        r = np.linalg.norm(cpv[:, :2] - [xc, yc], axis=1)
        hits[tag] = int(((np.abs(cpv[:, 2] - zc) < W / 2) &
                         (r > tyre["rim_r_m"] * 0.95) & (r < R)).sum())
    dias = [qcw[t]["diameter"] for t in qcw]
    wids = [qcw[t]["width"] for t in qcw]
    axf = np.array(qcw["FR"]["centre"]) - np.array(qcw["FL"]["centre"])
    axr = np.array(qcw["RR"]["centre"]) - np.array(qcw["RL"]["centre"])
    par = float(np.degrees(np.arccos(np.clip(
        abs(np.dot(axf, axr)) / (np.linalg.norm(axf) * np.linalg.norm(axr)),
        -1, 1))))
    report["wheels"] = qcw
    report["gates"] = {
        "diameter_spread_pct": round(100 * (max(dias) - min(dias)) / max(dias), 4),
        "width_spread_pct": round(100 * (max(wids) - min(wids)) / max(wids), 4),
        "toe_max_deg": max(q["toe_deg"] for q in qcw.values()),
        "camber_max_deg": max(q["camber_deg"] for q in qcw.values()),
        "axle_parallelism_deg": round(par, 4),
        "contact_spread_mm": round(max(q["contact_vs_ground_mm"]
                                       for q in qcw.values()) -
                                   min(q["contact_vs_ground_mm"]
                                       for q in qcw.values()), 3),
        "track_front_measured": round(abs(qcw["FR"]["centre"][2] -
                                          qcw["FL"]["centre"][2]), 4),
        "track_rear_measured": round(abs(qcw["RR"]["centre"][2] -
                                         qcw["RL"]["centre"][2]), 4),
        "wheelbase_measured": round(
            (qcw["FR"]["centre"][0] + qcw["FL"]["centre"][0]) / 2 -
            (qcw["RR"]["centre"][0] + qcw["RL"]["centre"][0]) / 2, 4),
        "tyre_body_intersections": hits,
        "tyre_outer_z": round(max(abs(q["centre"][2]) + W / 2
                                  for q in qcw.values()), 4),
        "body_half_width": round(float(np.percentile(np.abs(cpv[:, 2]), 99.7)), 4),
        "instancing_one_mesh_four_nodes": bool(shared)}
    if not fused_mode and report["ride_height"].get("arch_ceilings"):
        # tyre top must clear the measured arch ceiling at every corner —
        # a hard gate only in tuck mode; in grounded-web mode the carve
        # legitimately opened the arch above the (fake) ceiling, so the
        # numbers are recorded as information, not a verdict
        clr = {t: round(1000 * ((c - plane) - (CY + R)), 1)
               for t, c in report["ride_height"]["arch_ceilings"].items()}
        report["gates"]["arch_ceiling_clearance_mm"] = clr
        if report["ride_height"].get("mode") == "tuck":
            report["gates"]["arch_ceiling_clearance_result"] = \
                "PASS" if min(clr.values()) >= 0 else "FAIL"
        else:
            report["gates"]["arch_ceiling_clearance_result"] = \
                "N/A (grounded-web mode — carve manufactured the opening)"
    json.dump(report, open(qc_path, "w"), indent=1)
    print(json.dumps(report["gates"], indent=1))
    print(f"wrote {out_path} ({os.path.getsize(out_path)} bytes) + {qc_path}")


if __name__ == "__main__":
    main()
