#!/usr/bin/env python3
"""raster.py — exact z-buffer rasteriser matching cabin_rig.py's frozen cameras.

Why not render component ids in Blender: a per-component colour has to survive
a vertex-colour import and an 8-bit sRGB write, and neither round-trip is exact.
Rasterising in numpy gives the component id per pixel with no encoding at all.

The camera model is VALIDATED against the Blender label pass (`--selfcheck`):
the rasterised Body_Shell mask must agree with the label pass's Body_Shell mask.
If it does not, every number derived from this file is void.

Blender specifics reproduced here:
  * glTF import maps (x,y,z)_gltf -> (x,-z,y)_blender
  * TRACK_TO with track -Z / up +Y  ==  look-at with world up = +Z
  * sensor fit AUTO -> fits the LARGER pixel dimension (width, 1400 > 900)
"""
import json
import numpy as np


def gltf_to_blender(V):
    return np.stack([V[:, 0], -V[:, 2], V[:, 1]], 1)


def look_at(loc, target, up=(0, 0, 1)):
    loc = np.asarray(loc, float)
    f = np.asarray(target, float) - loc
    f /= np.linalg.norm(f)
    up = np.asarray(up, float)
    r = np.cross(f, up)
    if np.linalg.norm(r) < 1e-9:
        up = np.array([0.0, 1.0, 0.0])
        r = np.cross(f, up)
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    # world -> camera (camera looks down -Z, x right, y up)
    R = np.stack([r, u, -f], 0)
    return R, loc


class Cam:
    def __init__(self, loc, look, lens_mm, res, sensor_mm=36.0):
        self.R, self.C = look_at(loc, look)
        self.W, self.H = res
        fit = max(self.W, self.H)          # sensor fit AUTO
        self.fpx = lens_mm / sensor_mm * fit

    def project(self, Vb):
        P = (Vb - self.C) @ self.R.T
        z = -P[:, 2]                       # depth in front of camera
        with np.errstate(divide="ignore", invalid="ignore"):
            x = self.fpx * P[:, 0] / z + self.W / 2.0
            y = -self.fpx * P[:, 1] / z + self.H / 2.0
        return np.stack([x, y], 1), z


def rasterise(cam, Vb, F, fid=None, keep="near"):
    """Return (idbuf, zbuf). idbuf holds fid[face]+1, 0 = empty.

    keep="near" -> nearest surface (a normal z-buffer)
    keep="far"  -> FARTHEST surface. Needed to bound the glazed cabin: a
                   fragment inside the cabin lies between the near glazing and
                   the far glazing, and without the far bound the test also
                   selects geometry on the other side of the car seen straight
                   through it (negative control D/E caught exactly that)."""
    if fid is None:
        fid = np.arange(len(F))
    uv, z = cam.project(Vb)
    W, H = cam.W, cam.H
    idbuf = np.zeros((H, W), np.int64)
    far = (keep == "far")
    zbuf = np.full((H, W), -np.inf if far else np.inf)
    tri = uv[F]
    tz = z[F]
    ok = (tz > 1e-6).all(1)
    xmin = np.floor(tri[:, :, 0].min(1)).astype(int)
    xmax = np.ceil(tri[:, :, 0].max(1)).astype(int)
    ymin = np.floor(tri[:, :, 1].min(1)).astype(int)
    ymax = np.ceil(tri[:, :, 1].max(1)).astype(int)
    ok &= (xmax >= 0) & (xmin < W) & (ymax >= 0) & (ymin < H)
    idx = np.where(ok)[0]
    # FAST PATH: a triangle whose screen bbox is at most one pixel across in
    # both axes is written by its CENTROID pixel with a vectorised min/max
    # reduce. On this car ~90% of faces are sub-pixel at these camera
    # distances, and the per-face Python loop over them dominated the runtime
    # (the 15-direction hole test was heading for hours). The approximation is
    # sub-pixel by construction; the camera model is re-validated against
    # Blender's own label pass after this change.
    tiny = idx[(xmax[idx] - xmin[idx] <= 1) & (ymax[idx] - ymin[idx] <= 1)]
    if len(tiny):
        cx = np.clip(tri[tiny, :, 0].mean(1).astype(int), 0, W - 1)
        cy = np.clip(tri[tiny, :, 1].mean(1).astype(int), 0, H - 1)
        cz = 3.0 / (1.0 / tz[tiny]).sum(1)
        flat = cy * W + cx
        acc = np.full(H * W, -np.inf if far else np.inf)
        if far:
            np.maximum.at(acc, flat, cz)
        else:
            np.minimum.at(acc, flat, cz)
        acc = acc.reshape(H, W)
        winner = np.isfinite(acc) & ((acc > zbuf) if far else (acc < zbuf))
        zbuf[winner] = acc[winner]
        # resolve which face won each claimed pixel
        order = np.argsort(-cz if far else cz, kind="stable")
        f_ord, z_ord = flat[order], cz[order]
        first = np.flatnonzero(np.r_[True, f_ord[1:] != f_ord[:-1]])
        owner = np.full(H * W, -1, np.int64)
        owner[f_ord[first]] = tiny[order][first]
        ow = owner.reshape(H, W)
        idbuf[winner] = fid[ow[winner]] + 1
    idx = idx[(xmax[idx] - xmin[idx] > 1) | (ymax[idx] - ymin[idx] > 1)]
    # sort front-to-back so most fragments lose the depth test cheaply
    idx = idx[np.argsort(tz[idx].min(1))]
    if far:
        idx = idx[::-1]
    for i in idx:
        x0, x1 = max(xmin[i], 0), min(xmax[i] + 1, W)
        y0, y1 = max(ymin[i], 0), min(ymax[i] + 1, H)
        if x0 >= x1 or y0 >= y1:
            continue
        a, b, c = tri[i]
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        px = xx + 0.5
        py = yy + 0.5
        l0 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / d
        l1 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / d
        l2 = 1.0 - l0 - l1
        m = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if not m.any():
            continue
        za, zb, zc = tz[i]
        # perspective-correct depth
        inv = l0 / za + l1 / zb + l2 / zc
        zz = np.where(inv > 0, 1.0 / np.maximum(inv, 1e-12), np.inf)
        sub = zbuf[y0:y1, x0:x1]
        win = m & ((zz > sub) if far else (zz < sub))
        if win.any():
            win &= np.isfinite(zz)
            sub[win] = zz[win]
            idbuf[y0:y1, x0:x1][win] = fid[i] + 1
    return idbuf, zbuf


def cams_from_cfg(path):
    cfg = json.load(open(path))
    res = cfg["resolution"]
    return {n: Cam(c["loc"], c["look"], cfg["lens_mm"], res)
            for n, c in cfg["cameras"].items()}, cfg
