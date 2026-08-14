#!/usr/bin/env python3
"""structured_car.py — build a car GLB with the owner's NAMED PART HIERARCHY.

The spec, verbatim from the owner (2026-08-14):

    <name>
    ├── body
    │   ├── hood │ roof │ trunk │ door_FL │ door_FR │ door_RL │ door_RR
    ├── bumpers
    │   ├── bumper_front │ bumper_rear
    ├── wheels
    │   ├── wheel_FL │ wheel_FR │ wheel_RL │ wheel_RR
    ├── glass │ headlights │ taillights │ interior │ number_plates

Why this is possible here and impossible on generator output: the parametric
builder PLACES the panel seams itself (bonnet shut at the cowl, door edges off
the axle positions, tailgate at the rear pillar), so every quad of the lofted
skin already knows which panel it belongs to. A generated mesh would need
segmentation to recover this — P3-SAM measurably cannot cut glazing out of a
fused shell, and the transfer route gives ragged boundaries. Authoring is the
only route that gets the tree exact, by construction.

Panels not in the owner's tree (front wings, rear quarters, sills, roof
pillars) go into `body/shell` — one honest extra child rather than quads
silently glued onto the wrong panel.

Reuses the section/curve engine from parametric_car.py: same dimensions in,
same silhouette out; this module only changes HOW the skin is grouped and adds
interior + number plates.

Usage:
    python3 pipeline/authoring/structured_car.py --make toyota --model yaris \
        --out yaris_structured.glb
    (same flags as parametric_car.py, plus --name for the root node)
"""
import argparse
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glb import GLB                                            # noqa: E402
from parametric_car import (Car, SPECS, STYLES, NU, NV, SHUT_W,    # noqa: E402
                            SHUT_DEPTH, wheel, disc)


def loft(car, nu=NU, nv=NV):
    """Same loft as parametric_car.build, but returns the labelled grid."""
    seams = car.shut_positions()
    us = list(np.linspace(0.012, 0.988, nu))
    for u, _ in seams:
        us += [u - SHUT_W, u - SHUT_W * 0.45, u + SHUT_W * 0.45, u + SHUT_W]
    us = np.array(sorted(us))
    NUu = len(us)
    P = np.zeros((NUu, nv, 3))
    REG = np.zeros((NUu, nv), dtype=int)
    for i, u in enumerate(us):
        sec, reg = car.section(u, nv)
        inset = 0.0
        reg_mask = np.zeros(nv, dtype=bool)
        for su, (r0, r1) in seams:
            if abs(u - su) <= SHUT_W * 0.5:
                inset = SHUT_DEPTH
                reg_mask = (reg >= r0) & (reg <= r1)
                break
        y, z = sec[:, 0].copy(), sec[:, 1].copy()
        if inset:
            cy = (y.max() + y.min()) / 2
            ny, nz = y - cy, z
            ln = np.hypot(ny, nz) + 1e-9
            y[reg_mask] -= inset * (ny / ln)[reg_mask]
            z[reg_mask] -= inset * (nz / ln)[reg_mask]
        P[i, :, 0] = car.L * (u - 0.5)
        P[i, :, 1] = y
        P[i, :, 2] = z
        REG[i] = reg

    # arch ring snap + arch mask (same fix as parametric v2)
    arch_r = car.RW * 1.16
    axles = [car.L * (car.u_front - 0.5), car.L * (car.u_rear - 0.5)]
    arch = np.zeros((NUu - 1, nv - 1), dtype=bool)
    for i in range(NUu - 1):
        flank = car.halfwidth(us[i]) * 0.5
        for j in range(nv - 1):
            if REG[i, j] > 3 or P[i, j, 2] < flank:
                continue
            x = P[i:i + 2, j:j + 2, 0].mean()
            y = P[i:i + 2, j:j + 2, 1].mean()
            if any(math.hypot(x - ax, y - car.RW) < arch_r * 0.995 for ax in axles):
                arch[i, j] = True

    # Project the OPENING'S BOUNDARY VERTICES onto the arch circle. Cutting
    # whole quads leaves a pixel staircase at the rim (v1); snapping every
    # nearby vertex lumps the wing (v4); the correct rule is: exactly the kept
    # vertices that border a removed quad get projected radially onto the
    # circle, everything else stays untouched.
    NUq, nvq = arch.shape
    for i in range(NUu):
        for j in range(nv):
            adj_removed = any(arch[ii, jj]
                              for ii in (i - 1, i) for jj in (j - 1, j)
                              if 0 <= ii < NUq and 0 <= jj < nvq)
            adj_kept = any(not arch[ii, jj]
                           for ii in (i - 1, i) for jj in (j - 1, j)
                           if 0 <= ii < NUq and 0 <= jj < nvq)
            if not (adj_removed and adj_kept):
                continue
            x, y = P[i, j, 0], P[i, j, 1]
            for ax in axles:
                d = math.hypot(x - ax, y - car.RW)
                if d < 1e-6 or abs(d - arch_r) > arch_r * 0.35:
                    continue
                k = arch_r / d
                P[i, j, 0] = ax + (x - ax) * k
                P[i, j, 1] = car.RW + (y - car.RW) * k
                break
    return P, REG, us, arch, axles, arch_r


def classify(car, us, REG, glassband):
    """Label every (station, section) quad with its panel name.

    The u boundaries come from the SAME seam positions the grooves are engraved
    at, so the panel edge and the visible shut line coincide exactly.
    """
    s = car.s
    arch_f = car.u_front + car.RW / car.L * 1.05
    arch_r_u = car.u_rear - car.RW / car.L * 1.05
    door_mid = (arch_f + arch_r_u) / 2
    cowl_seam = s["cowl"] + 0.005
    tail_seam = s["roof_r"] - 0.01

    NUu, nv = REG.shape
    names = np.empty((NUu - 1, nv - 1), dtype=object)
    for i in range(NUu - 1):
        u = 0.5 * (us[i] + us[i + 1])
        for j in range(nv - 1):
            r = REG[i, j]
            if glassband[i, j]:
                names[i, j] = "glass"
            elif u >= 0.965 or (u >= cowl_seam and r <= 1):
                names[i, j] = "bumper_front"
            elif u <= 0.035 or (u <= tail_seam and r <= 1):
                names[i, j] = "bumper_rear"
            elif u >= cowl_seam and r == 5:
                names[i, j] = "hood"
            elif u <= tail_seam and r >= 3:
                names[i, j] = "trunk"
            elif tail_seam < u < cowl_seam and r == 5:
                names[i, j] = "roof"
            elif arch_r_u <= u <= arch_f and 1 <= r <= 4:
                names[i, j] = "door_front" if u >= door_mid else "door_rear"
            else:
                names[i, j] = "shell"
    return names


def glass_mask(car, us, REG):
    s = car.s
    NUu, nv = REG.shape
    g = np.zeros((NUu - 1, nv - 1), dtype=bool)
    for i in range(NUu - 1):
        u = 0.5 * (us[i] + us[i + 1])
        if not (s["roof_r"] - 0.005 < u < s["cowl"] + 0.02):
            continue
        for j in range(nv - 1):
            r = REG[i, j]
            # SIDE glass (r==4) exists only between the A- and C-pillars — the
            # first structured build let it run to the cowl, which painted a
            # glass channel down the bonnet flank (seen in the side render).
            # The raked screen and backlight are the r==5 band outside the
            # roof span.
            if r == 4 and (s["roof_r"] + 0.02 < u < s["roof_f"] + 0.03):
                g[i, j] = True
            elif r == 5 and (u > s["roof_f"] or u < s["roof_r"] + 0.06):
                g[i, j] = True
    return g


def emit_grid(P, sel, side, us=None):
    """Mesh the selected quads for ONE side (+1 right, -1 left).

    When `us` is given, also returns per-vertex UVs in the skin's texture
    space: u along the car (the loft parameter itself), v = section fraction.
    Both sides share the map — mirror symmetry, like a real car's livery.
    """
    V, F, UV, idx = [], [], [], {}
    NUu, nv = P.shape[0], P.shape[1]

    def vid(i, j):
        key = (i, j)
        if key not in idx:
            p = P[i, j].copy()
            if side < 0:
                p[2] = -p[2]
            idx[key] = len(V)
            V.append(p)
            if us is not None:
                UV.append([us[i], 1.0 - j / (nv - 1)])
        return idx[key]

    for i in range(NUu - 1):
        for j in range(nv - 1):
            if not sel[i, j]:
                continue
            a, b = vid(i, j), vid(i + 1, j)
            c, d = vid(i + 1, j + 1), vid(i, j + 1)
            if side > 0:
                F += [[a, b, c], [a, c, d]]
            else:
                F += [[a, c, b], [a, d, c]]
    if not V:
        z = np.zeros((0, 3))
        return (z, np.zeros((0, 3), dtype=np.uint32),
                np.zeros((0, 2))) if us is not None else (z, np.zeros((0, 3), dtype=np.uint32))
    if us is not None:
        return np.array(V), np.array(F, dtype=np.uint32), np.array(UV)
    return np.array(V), np.array(F, dtype=np.uint32)


def caps(P):
    """Close nose and tail; returned per-end so they join the bumper groups."""
    out = []
    NUu, nv = P.shape[0], P.shape[1]
    for end, outward in ((NUu - 1, 1), (0, -1)):
        ring = [P[end, j].copy() for j in range(nv)]
        ring += [np.array([p[0], p[1], -p[2]]) for p in reversed(ring[1:-1])]
        V = ring + [np.mean(ring, axis=0)]
        c = len(ring)
        F = []
        for k in range(len(ring)):
            a, b = k, (k + 1) % len(ring)
            F.append([c, a, b] if outward > 0 else [c, b, a])
        out.append((np.array(V), np.array(F, dtype=np.uint32)))
    return out                                # [front, rear]


def arch_liners(car, us, axles, arch_r):
    V, F = [], []
    depth = car.TW * 1.15
    for ax in axles:
        for side in (1, -1):
            i_near = int(np.argmin(np.abs(car.L * (us - 0.5) - ax)))
            zo = car.halfwidth(us[i_near]) * 0.985 * side
            angs = np.linspace(math.pi * 0.02, math.pi * 0.98, 26)
            base = len(V)
            for a in angs:
                V.append([ax + arch_r * math.cos(a), car.RW + arch_r * math.sin(a), zo])
            for a in angs:
                V.append([ax + arch_r * 0.97 * math.cos(a),
                          car.RW + arch_r * 0.97 * math.sin(a), zo - depth * side])
            m = len(angs)
            for k in range(m - 1):
                a0, a1 = base + k, base + k + 1
                b0, b1 = base + m + k, base + m + k + 1
                F += ([[a0, b0, b1], [a0, b1, a1]] if side > 0 else
                      [[a0, b1, b0], [a0, a1, b1]])
    return np.array(V), np.array(F, dtype=np.uint32)


def interior_tub(car):
    """A simple dark cabin volume so the glazing shows a cabin, not the far side
    of the shell. Deliberately coarse — it reads as depth, and that is its job."""
    s = car.s
    u0, u1 = s["roof_r"] + 0.06, s["cowl"] - 0.02
    x0, x1 = car.L * (u0 - 0.5), car.L * (u1 - 0.5)
    floor = car.sill(0.5) + 0.03
    # cap the tub below the LOWEST roofline over its own span — v1 used the
    # mid-cabin roof height and the box poked through the raked rear screen
    roof_min = min(car.roofline(u0), car.roofline(u1))
    top = min(car.belt_y(0.5) + (car.roofline(0.5) - car.belt_y(0.5)) * 0.45,
              roof_min - 0.09)
    hw = car.halfwidth(0.5) * 0.74
    V = []
    for x in (x0, x1):
        for y in (floor, top):
            for z in (-hw, hw):
                V.append([x, y, z])
    F = [[0, 1, 3], [0, 3, 2], [4, 7, 5], [4, 6, 7],      # ends
         [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],      # sides
         [1, 5, 7], [1, 7, 3], [0, 2, 6], [0, 6, 4]]      # top/floor
    return np.array(V, dtype=float), np.array(F, dtype=np.uint32)


def plates(car):
    """Front and rear number-plate rectangles (UK 520x111mm)."""
    w, h = 0.520 / 2, 0.111 / 2
    out = []
    for x, y, nrm in ((car.L / 2 * 0.995, car.RW * 1.15, 1),
                      (-car.L / 2 * 0.995, car.RW * 1.30, -1)):
        V = np.array([[x, y - h, -w], [x, y - h, w], [x, y + h, w], [x, y + h, -w]])
        F = np.array([[0, 1, 2], [0, 2, 3]] if nrm > 0 else
                     [[0, 2, 1], [0, 3, 2]], dtype=np.uint32)
        out.append((V, F))
    return out                                # [front, rear]


def section_marks(REG, us):
    """Measure the skin's v-landmarks from the REAL grid, mid-cabin station.

    skin.py paints the swage line, sill band and handles at these fractions;
    measuring them from REG (instead of hardcoding) keeps paint and geometry
    agreeing for every body style. v runs 1 - j/(nv-1) to match emit_grid.
    """
    i = int(np.argmin(np.abs(us - 0.5)))
    row = REG[i]
    nv = len(row)

    def frac(j):
        return 1.0 - j / (nv - 1)
    sill_j = max(np.where(row <= 1)[0]) if (row <= 1).any() else 4
    belt_j = min(np.where(row == 4)[0]) if (row == 4).any() else nv // 2
    sh = np.where(row == 3)[0]
    shoulder_j = int(sh.mean()) if len(sh) else (sill_j + belt_j) // 2
    return {"sill": frac(sill_j), "belt": frac(belt_j),
            "shoulder": frac(shoulder_j)}


def build_structured(car, out, root_name=None, textured=True):
    from skin import paint_skin

    g = GLB(generator=f"structured_car/{car.name}")

    P, REG, us, arch, axles, arch_r = loft(car)

    if textured:
        base_png, normal_png = paint_skin(car, section_marks(REG, us))
        t_base = g.texture(base_png)
        t_norm = g.texture(normal_png)
        m_paint = g.material("Material_0", [0.72, 0.73, 0.75, 1.0], 0.10, 0.28,
                             base_tex=t_base, normal_tex=t_norm)
    else:
        m_paint = g.material("Material_0", [0.72, 0.73, 0.75, 1.0], 0.10, 0.28)
    m_glass = g.material("Glass_Tint", [0.03, 0.04, 0.05, 0.26], 0.0, 0.05, blend=True)
    m_tyre = g.material("Tyre_Rubber", [0.026, 0.026, 0.030, 1.0], 0.0, 0.92)
    m_rim = g.material("Rim_Alloy", [0.52, 0.53, 0.55, 1.0], 0.92, 0.28)
    m_lamp = g.material("Lamp_Lens", [0.070, 0.072, 0.085, 1.0], 0.0, 0.07)
    m_dark = g.material("Trim_Dark", [0.020, 0.020, 0.022, 1.0], 0.0, 0.80)
    m_int = g.material("Interior_Dark", [0.045, 0.045, 0.050, 1.0], 0.0, 0.90)
    m_plate = g.material("licenseplate", [0.92, 0.92, 0.90, 1.0], 0.0, 0.40)

    root = g.group(root_name or car.name)
    n_body = g.group("body", root)
    n_bump = g.group("bumpers", root)
    n_whl = g.group("wheels", root)

    gmask = glass_mask(car, us, REG)
    names = classify(car, us, REG, gmask)
    names[arch] = None                                     # arch holes
    uv_us = us if textured else None

    def sel(name):
        return np.array([[names[i, j] == name for j in range(names.shape[1])]
                         for i in range(names.shape[0])])

    def emit_both(mask):
        parts = [emit_grid(P, mask, +1, us=uv_us), emit_grid(P, mask, -1, us=uv_us)]
        Vs = [p[0] for p in parts if len(p[1])]
        if not Vs:
            return None
        V = np.concatenate(Vs)
        off, Fs, UVs = 0, [], []
        for p in parts:
            if len(p[1]):
                Fs.append(p[1] + off)
                off += len(p[0])
                if uv_us is not None:
                    UVs.append(p[2])
        UV = np.concatenate(UVs) if UVs else None
        return V, np.concatenate(Fs), UV

    # symmetric panels: one mesh spanning both sides
    for pn in ("hood", "roof", "trunk", "shell", "bumper_front", "bumper_rear"):
        got = emit_both(sel(pn))
        if not got:
            continue
        V, F, UV = got
        parent = n_bump if pn.startswith("bumper") else n_body
        g.mesh(pn, V, F, m_paint, parent=parent, uvs=UV)

    # doors: four separate panels, L/R from the grid side
    for pn, out_name_r, out_name_l in (("door_front", "door_FR", "door_FL"),
                                       ("door_rear", "door_RR", "door_RL")):
        m = sel(pn)
        # UK viewer convention in this repo: +z = right side of the car
        for side, nm in ((+1, out_name_r), (-1, out_name_l)):
            got = emit_grid(P, m, side, us=uv_us)
            V, F = got[0], got[1]
            UV = got[2] if uv_us is not None else None
            g.mesh(nm, V, F, m_paint, parent=n_body, uvs=UV)

    # caps join the bumpers. They share Material_0 (so resprays cover them),
    # so they need TEXCOORD_0 too — pinned to a blank white patch of the map.
    (cfV, cfF), (crV, crF) = caps(P)
    blank = lambda V: (np.full((len(V), 2), [0.5, 0.02])    # noqa: E731
                       if textured else None)
    g.mesh("bumper_front_cap", cfV, cfF, m_paint, parent=n_bump, uvs=blank(cfV))
    g.mesh("bumper_rear_cap", crV, crF, m_paint, parent=n_bump, uvs=blank(crV))

    # glass, one mesh both sides
    parts = [emit_grid(P, gmask & ~arch, +1), emit_grid(P, gmask & ~arch, -1)]
    V = np.concatenate([p[0] for p in parts])
    F = np.concatenate([parts[0][1], parts[1][1] + len(parts[0][0])])
    g.mesh("glass", V, F, m_glass, parent=root)

    aV, aF = arch_liners(car, us, axles, arch_r)
    g.mesh("arch_liners", aV, aF, m_dark, parent=n_body)

    iV, iF = interior_tub(car)
    g.mesh("interior", iV, iF, m_int, parent=root)

    # wheels: a group per corner; +z right, front = +x
    half = car.TR / 2
    corners = {"wheel_FR": (axles[0], half), "wheel_FL": (axles[0], -half),
               "wheel_RR": (axles[1], half), "wheel_RL": (axles[1], -half)}
    for cn, (x, z) in corners.items():
        node = g.group(cn, n_whl)
        (tv, tf), (rv, rf) = wheel(x, z, car.RW, car.TW)
        g.mesh(cn + "_tyre", tv, tf, m_tyre, parent=node)
        g.mesh(cn + "_rim", rv, rf, m_rim, parent=node)

    # lamps
    n_head = g.group("headlights", root)
    n_tail = g.group("taillights", root)
    # lamps and grille sit INSIDE the shell and emboss through the cap — the
    # first build hung them off the nose x and they protruded as stalks.
    nose = car.L * 0.5
    lampy = car.roofline(0.985) * 0.62
    for i, z in enumerate((car.W * 0.28, -car.W * 0.28)):
        v, f = disc(nose - 0.16, lampy, z, 0.15, 0.070, 0.04)
        g.mesh(f"headlight_{'R' if z > 0 else 'L'}", v, f, m_lamp, parent=n_head)
    for i, z in enumerate((car.W * 0.30, -car.W * 0.30)):
        v, f = disc(-nose + 0.15, car.roofline(0.02) * 0.72, z, 0.12, 0.065, 0.04)
        g.mesh(f"taillight_{'R' if z > 0 else 'L'}", v, f, m_lamp, parent=n_tail)
    v, f = disc(nose - 0.13, lampy * 0.60, 0.0, 0.28, 0.080, 0.05)
    g.mesh("grille", v, f, m_dark, parent=n_body)

    n_pl = g.group("number_plates", root)
    (pfV, pfF), (prV, prF) = plates(car)
    g.mesh("plate_front", pfV, pfF, m_plate, parent=n_pl)
    g.mesh("plate_rear", prV, prF, m_plate, parent=n_pl)

    size = g.save(out)
    return size, g


def print_tree(g):
    nodes = g.g["nodes"]
    roots = g.g["scenes"][0]["nodes"]

    def walk(idx, depth):
        n = nodes[idx]
        tag = "" if "mesh" in n else "/"
        print("  " * depth + "- " + n.get("name", "?") + tag)
        for c in n.get("children", []):
            walk(c, depth + 1)
    for r in roots:
        walk(r, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make")
    ap.add_argument("--model")
    ap.add_argument("--style")
    ap.add_argument("--name", help="root node name, e.g. 2026_VW_Touran")
    for k in ("length", "width", "height", "wheelbase", "track",
              "wheel_d", "tyre_w"):
        ap.add_argument(f"--{k.replace('_','-')}", type=float, dest=k)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    if a.make and a.model:
        key = (a.make.lower(), a.model.lower())
        if key not in SPECS:
            raise SystemExit(f"no spec for {key}; known {sorted(SPECS)}")
        spec = dict(SPECS[key])
    else:
        need = [k for k in ("length", "width", "height", "wheelbase") if not getattr(a, k)]
        if need:
            raise SystemExit(f"need --make/--model or {need}")
        spec = dict(length=a.length, width=a.width, height=a.height,
                    wheelbase=a.wheelbase, track=a.track or a.width * 0.86,
                    wheel_d=a.wheel_d or 640, tyre_w=a.tyre_w or 205,
                    style=a.style or "hatch")
    if a.style:
        spec["style"] = a.style
    name = a.name or (f"{a.make}-{a.model}" if a.make else
                      os.path.splitext(os.path.basename(a.out))[0])
    car = Car(name=name, **spec)
    size, g = build_structured(car, a.out, root_name=name)
    print(f"{a.out}: {size/1024:.0f} KB, {len(g.g['meshes'])} meshes, "
          f"{len(g.g['materials'])} materials")
    print_tree(g)


if __name__ == "__main__":
    main()
