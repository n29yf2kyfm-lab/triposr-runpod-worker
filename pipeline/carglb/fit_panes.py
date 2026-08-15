#!/usr/bin/env python3
"""fit_panes.py — build glazing PANES across a Hi3DGen mesh's window apertures,
and assemble the final structured, materialed GLB directly.

THE MEASURED TOPOLOGY (Golf run, 2026-08-15, see also glaze_openings.py):
Hi3DGen windows are neither surfaces nor boundary-loop holes. The outer skin
wraps THROUGH each aperture into a modelled cabin, so the mesh is watertight,
yet the side-view projection shows literally zero outward-facing faces where
the glass should be. Nothing exists to label — recess detection (21.7% then
15.4% false positives) was chasing surface that is not there. The correct move
is construction: rasterise each side of the car, find the in-silhouette pixel
regions with NO outward surface in the cabin band (those ARE the window
apertures), and span a pane across each at the local pillar level.

Assembly skips the PartCrafter/hybrid path entirely for this mesh class:
  body   = the 96%-shell               -> Material_0
  panes  = built here                  -> Glass_Tint (BLEND 0.26)
  wheels = the 4 separate wheel bodies -> Tyre_Rubber
  small bodies (mirrors, trims)        -> Material_0 with the body
which satisfies the same gates build_car enforces: glass clear/proven by
construction, glazing share printed against the 2.5-9.5% band, tyres
unreachable by paint, respray touches Material_0 only.

Usage:
    python3 pipeline/carglb/fit_panes.py shape.glb out.glb

STATUS v2 2026-08-15, measured on the Golf run: COMPLETE CAR, GATES PASS.
  glass_probe clear/proven · glass 7.06% of faces (band 2.5-9.5%) ·
  crease_density 183 (2/3 catalogue) · windscreen+backlight paned via the
  oblique rake projections (dominant region only — the oblique view also sees
  underbody gaps that fake dozens of small apertures) · side windows paned ·
  interior reads through tint in the production render. Remaining polish for
  v3: pane speckle at edges (per-pixel grid; fit a smooth plane instead) and
  roofline noise. Earlier v1 status kept below for the record.

STATUS v1 (superseded): WORKING BUT RAGGED.
  * side apertures: found (2 per side, the door windows) and paned; the
    rear-quarter pane bleeds around the C-pillar and pane edges leak above
    the roofline (the dilate step ignores the silhouette boundary).
  * windscreen/backlight: the top-map region detector fragments below the
    size threshold — the raked screen needs its own projection (view along
    the screen normal, not straight down).
  * assembly, materials, gates: sound. GLB valid (after the corner -inf
    fix), renders through the production rig, glass_probe-satisfiable by
    construction.
Next iteration: clamp dilation to the silhouette, per-screen oblique
projection, then wire into carglb.run_local as the Hi3DGen path.
"""
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "authoring"))
from glb import GLB                                            # noqa: E402


def axes_of(V):
    ext = V.max(0) - V.min(0)
    L = int(np.argmax(ext))
    rest = [i for i in range(3) if i != L]
    H = rest[int(np.argmin(ext[rest]))]
    W = [i for i in rest if i != H][0]
    return L, H, W


def sliding_row_max(img, win):
    out = img.copy()
    for shift in range(1, win + 1):
        out[:, shift:] = np.maximum(out[:, shift:], img[:, :-shift])
        out[:, :-shift] = np.maximum(out[:, :-shift], img[:, shift:])
    return out


def dilate(mask, n=2):
    out = mask.copy()
    for _ in range(n):
        d = out.copy()
        d[1:, :] |= out[:-1, :]; d[:-1, :] |= out[1:, :]
        d[:, 1:] |= out[:, :-1]; d[:, :-1] |= out[:, 1:]
        out = d
    return out


def erode(mask, n=1):
    out = mask.copy()
    for _ in range(n):
        d = out.copy()
        d[1:, :] &= out[:-1, :]; d[:-1, :] &= out[1:, :]
        d[:, 1:] &= out[:, :-1]; d[:, :-1] &= out[:, 1:]
        out = d
    return out


def fit_plane(px, lvl):
    """Least-squares plane level = a*x + b*y + c over the region's FINITE
    sliding-max samples. A per-pixel level made the panes speckle (each pixel
    at its own stepped max); glass is flat — one plane per pane is both truer
    and visually clean."""
    ys, xs, zs = [], [], []
    for (py, pxx) in px:
        v = lvl[min(py, lvl.shape[0] - 1), min(pxx, lvl.shape[1] - 1)]
        if np.isfinite(v):
            ys.append(py); xs.append(pxx); zs.append(v)
    if len(zs) < 3:
        return None
    A = np.c_[xs, ys, np.ones(len(zs))]
    coef, *_ = np.linalg.lstsq(A, np.array(zs), rcond=None)
    return coef        # a, b, c


def regions(mask, min_px):
    """4-connected components of a boolean image, dependency-free BFS."""
    lab = np.zeros(mask.shape, dtype=int)
    cur = 0
    out = []
    for y, x in zip(*np.where(mask)):
        if lab[y, x]:
            continue
        cur += 1
        stack = [(y, x)]
        lab[y, x] = cur
        px = []
        while stack:
            cy, cx = stack.pop()
            px.append((cy, cx))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = cy + dy, cx + dx
                if (0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1]
                        and mask[ny, nx] and not lab[ny, nx]):
                    lab[ny, nx] = cur
                    stack.append((ny, nx))
        if len(px) >= min_px:
            out.append(np.array(px))
    return out


def pane_from_region(px, u_lo, u_scale, v_lo, v_scale, level_img, axisL,
                     axisH, axisW, sign, inset):
    """A pane mesh over the region's pixels on a PLANE-FIT level (v3).

    v2 set each vertex at its own sliding-max level, which stepped pixel to
    pixel — the render showed speckle across every pane. Glass is flat: fit
    one least-squares plane per pane and put every vertex on it.
    """
    plane = fit_plane(px, level_img)
    if plane is None:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.uint32)
    a_, b_, c_ = plane
    Vs, Fs, index = [], [], {}
    have = set(map(tuple, px))
    for (py, pxx) in have:
        for dy, dx in ((0, 0), (1, 0), (0, 1), (1, 1)):
            key = (py + dy, pxx + dx)
            if key not in index:
                yy, xx = key
                p = np.zeros(3)
                p[axisL] = u_lo + xx * u_scale
                p[axisH] = v_lo + yy * v_scale
                p[axisW] = (a_ * xx + b_ * yy + c_ - inset) * sign
                index[key] = len(Vs)
                Vs.append(p)
        a = index[(py, pxx)]
        b = index[(py + 1, pxx)]
        c = index[(py + 1, pxx + 1)]
        d = index[(py, pxx + 1)]
        Fs += [[a, b, c], [a, c, d]]
    return np.array(Vs), np.array(Fs, dtype=np.uint32)


def fit(src, out_glb, res=256, inset_frac=0.004, min_frac=0.0015):
    m = trimesh.load(src, force="mesh")
    V = np.asarray(m.vertices)
    N = m.face_normals
    F = np.asarray(m.faces)
    C = V[F].mean(axis=1)
    lo, hi = V.min(0), V.max(0)
    ext = hi - lo
    L, H, W = axes_of(V)
    inset = inset_frac * ext[L]
    win = max(2, int(0.10 * res))
    min_px = int(min_frac * res * res)

    def norm(a, ax):
        return (a - lo[ax]) / ext[ax]

    panes = []
    # ---------------- side apertures --------------------------------------
    for sign in (+1, -1):
        sel = (N[:, W] * sign > 0.25)
        u = (norm(C[sel, L], L) * (res - 1)).astype(int)
        v = (norm(C[sel, H], H) * (res - 1)).astype(int)
        w = np.abs(C[sel, W])
        img = np.full((res, res), -np.inf)
        np.maximum.at(img, (v, u), w)
        covered = np.isfinite(img)
        # silhouette: columns/rows the car occupies at all (any geometry)
        au = (norm(C[:, L], L) * (res - 1)).astype(int)
        av = (norm(C[:, H], H) * (res - 1)).astype(int)
        sil = np.zeros((res, res), dtype=bool)
        sil[av, au] = True
        # densify: fill each column between the car's top and bottom rows —
        # sparse centroid hits leave speckle holes that fake apertures
        for col in range(res):
            rows = np.where(sil[:, col])[0]
            if len(rows) > 1:
                sil[rows.min():rows.max() + 1, col] = True
        # aperture = inside silhouette, cabin band, NO outward surface
        band = np.zeros((res, res), dtype=bool)
        band[int(res * 0.45):int(res * 0.97), int(res * 0.06):int(res * 0.94)] = True
        aperture = dilate(band & sil & ~covered) & ~covered & sil
        lvl = sliding_row_max(np.where(covered, img, -np.inf), win)
        aperture = erode(aperture, 1)
        regs = regions(aperture, min_px)
        print(f"side {'+' if sign > 0 else '-'}: aperture px "
              f"{aperture.sum()} -> {len(regs)} regions "
              f"{[len(r) for r in regs]}")
        for r in regs:
            pv, pf = pane_from_region(
                r, lo[L], ext[L] / (res - 1), lo[H], ext[H] / (res - 1),
                lvl, L, H, W, sign, inset)
            panes.append((pv, pf))

    # ---------------- windscreen / backlight ------------------------------
    sel = N[:, H] > 0.20
    u = (norm(C[sel, L], L) * (res - 1)).astype(int)
    v = (norm(C[sel, W], W) * (res - 1)).astype(int)
    h = C[sel, H]
    img = np.full((res, res), -np.inf)
    np.maximum.at(img, (v, u), h)
    covered = np.isfinite(img)
    au = (norm(C[:, L], L) * (res - 1)).astype(int)
    av = (norm(C[:, W], W) * (res - 1)).astype(int)
    sil = np.zeros((res, res), dtype=bool)
    sil[av, au] = True
    for col in range(res):
        rows = np.where(sil[:, col])[0]
        if len(rows) > 1:
            sil[rows.min():rows.max() + 1, col] = True
    band = np.zeros((res, res), dtype=bool)
    band[int(res * 0.12):int(res * 0.88), int(res * 0.05):int(res * 0.95)] = True
    aperture = dilate(band & sil & ~covered, 3) & ~covered & sil
    lvl = sliding_row_max(np.where(covered, img, -np.inf), win)
    regs = regions(aperture, max(20, min_px // 3))
    print(f"top      : aperture px {aperture.sum()} -> {len(regs)} regions "
          f"{[len(r) for r in regs]}")
    for r in regs:
        pv, pf = pane_from_region(
            r, lo[L], ext[L] / (res - 1), lo[W], ext[W] / (res - 1),
            lvl, L, W, H, +1, inset)
        panes.append((pv, pf))

    # ---------------- raked screens: oblique projections -------------------
    # straight-down fragments a raked windscreen (measured: 51/37-px crumbs).
    # Project along the rake instead: axis = cos(a)*L_hat (+/- nose) +
    # sin(a)*H_hat, with the screen band selected by position.
    for nose_sign, l_lo, l_hi in ((+1, 0.55, 0.95), (-1, 0.05, 0.45)):
        a = np.radians(35)
        d_ax = np.zeros(3)
        d_ax[L] = nose_sign * np.cos(a)
        d_ax[H] = np.sin(a)
        # oblique coords: p1 along the rake-projected length, p2 = width
        t_ax = np.zeros(3)
        t_ax[L] = -nose_sign * np.sin(a)
        t_ax[H] = np.cos(a)
        depth_v = C @ d_ax                     # distance along view axis
        p1 = C @ t_ax
        p2 = C[:, W]
        nsel = (N @ d_ax) > 0.25
        lf = norm(C[:, L], L)
        band_sel = (lf > l_lo) & (lf < l_hi) & (norm(C[:, H], H) > 0.45)
        sel = nsel & band_sel
        if sel.sum() < 100:
            continue
        p1n = (p1[sel] - p1[sel].min()) / max(np.ptp(p1[sel]), 1e-9)
        p2n = (p2[sel] - lo[W]) / ext[W]
        u = (p1n * (res - 1)).astype(int)
        v = np.clip((p2n * (res - 1)).astype(int), 0, res - 1)
        img = np.full((res, res), -np.inf)
        np.maximum.at(img, (v, u), depth_v[sel])
        covered = np.isfinite(img)
        allsel = band_sel
        ap1 = (p1[allsel] - p1[sel].min()) / max(np.ptp(p1[sel]), 1e-9)
        ap2 = (p2[allsel] - lo[W]) / ext[W]
        sau = np.clip((ap1 * (res - 1)).astype(int), 0, res - 1)
        sav = np.clip((ap2 * (res - 1)).astype(int), 0, res - 1)
        sil2 = np.zeros((res, res), dtype=bool)
        sil2[sav, sau] = True
        for col in range(res):
            rows = np.where(sil2[:, col])[0]
            if len(rows) > 1:
                sil2[rows.min():rows.max() + 1, col] = True
        aperture = erode(dilate(sil2 & ~covered) & ~covered & sil2, 1)
        lvl = sliding_row_max(np.where(covered, img, -np.inf), win)
        regs = regions(aperture, max(30, min_px // 2))
        # keep only the DOMINANT region: the screen. The oblique view also sees
        # underbody/interior gaps, which fake dozens of small apertures
        # (measured: 19 and 23 regions; the real screens were 12k and 7k px).
        regs = sorted(regs, key=len)[-1:] if regs else []
        print(f"rake {'front' if nose_sign>0 else 'rear'}: aperture px "
              f"{aperture.sum()} -> kept {[len(r) for r in regs]}")
        for r in regs:
            plane = fit_plane(r, lvl)
            if plane is None:
                continue
            pa, pb, pc = plane
            Vs, Fs, index = [], [], {}
            have = set(map(tuple, r))
            for (py, pxx) in have:
                for dy, dx in ((0, 0), (1, 0), (0, 1), (1, 1)):
                    key = (py + dy, pxx + dx)
                    if key not in index:
                        yy, xx = key
                        l2 = pa * xx + pb * yy + pc
                        t1 = p1[sel].min() + xx / (res - 1) * np.ptp(p1[sel])
                        t2 = lo[W] + yy / (res - 1) * ext[W]
                        pt = t_ax * t1 + d_ax * (l2 - inset)
                        pt[W] = t2
                        index[key] = len(Vs)
                        Vs.append(pt)
                a = index[(py, pxx)]; b = index[(py + 1, pxx)]
                c = index[(py + 1, pxx + 1)]; d = index[(py, pxx + 1)]
                Fs += [[a, b, c], [a, c, d]]
            if Vs:
                panes.append((np.array(Vs), np.array(Fs, dtype=np.uint32)))

    if not panes:
        raise SystemExit("no apertures found — this mesh is not the "
                         "open-aperture kind")

    # ---------------- assemble the structured GLB -------------------------
    bodies = m.split(only_watertight=False)
    bodies = sorted(bodies, key=lambda b: -len(b.faces))
    shell, rest = bodies[0], bodies[1:]
    # wheels: the four biggest non-shell bodies in the wheel height band
    wheels, trims = [], []
    for b in rest:
        cy = (b.centroid[H] - lo[H]) / ext[H]
        if cy < 0.45 and len(b.faces) > 500 and len(wheels) < 4:
            wheels.append(b)
        else:
            trims.append(b)
    print(f"assembly: shell {len(shell.faces)}f, wheels {len(wheels)}, "
          f"trims {len(trims)}")

    g = GLB(generator="carglb/fit_panes")
    m_paint = g.material("Material_0", [0.72, 0.73, 0.75, 1.0], 0.10, 0.28)
    m_glass = g.material("Glass_Tint", [0.03, 0.04, 0.05, 0.26], 0.0, 0.05,
                         blend=True)
    m_tyre = g.material("Tyre_Rubber", [0.026, 0.026, 0.030, 1.0], 0.0, 0.92)
    root = g.group("car")
    g.mesh("body", shell.vertices, shell.faces, m_paint, parent=root)
    for i, b in enumerate(trims):
        g.mesh(f"trim_{i}", b.vertices, b.faces, m_paint, parent=root)
    for i, b in enumerate(wheels):
        g.mesh(f"wheel_{i}", b.vertices, b.faces, m_tyre, parent=root)
    tot_pane_faces = 0
    for i, (pv, pf) in enumerate(panes):
        g.mesh(f"glass_{i}", pv, pf, m_glass, parent=root)
        tot_pane_faces += len(pf)
    size = g.save(out_glb)
    all_faces = len(shell.faces) + sum(len(b.faces) for b in rest) + tot_pane_faces
    share = tot_pane_faces / all_faces * 100
    print(f"wrote {out_glb} ({size/1e6:.1f}MB)  glass faces {tot_pane_faces} "
          f"= {share:.2f}% of car (gate band 2.5-9.5%)")
    return out_glb


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    fit(sys.argv[1], sys.argv[2])
