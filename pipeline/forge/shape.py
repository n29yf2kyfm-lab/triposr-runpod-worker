#!/usr/bin/env python3
"""shape.py — a Car whose curves come from photographs.

`PhotoCar` is `parametric_car.Car` with every identity-carrying curve replaced
by what `trace.py` measured: the roofline and sill along the car, the wheel
centres, the beltline, the side-glass outline, the door shut lines, and the
cross-section shape taken from the front and rear views. Anything the photos
did not give falls back to the style default, and the report says which.

The loft, the panel classification and the GLB writer are unchanged: this
class only answers the same questions (`roofline(u)`, `sill(u)`, `section(u)`,
`shut_positions()`) with measured numbers instead of style constants.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "authoring"))
from parametric_car import Car, STYLES, NV  # noqa: E402


class PhotoCar(Car):
    def __init__(self, dims, side=None, front=None, rear=None, name="car"):
        style = dims.get("style", "hatch")
        super().__init__(dims["length"], dims["width"], dims["height"], dims["wheelbase"],
                         dims.get("track", dims["width"] * 0.86), dims.get("wheel_d", 640),
                         dims.get("tyre_w", 205), style=style, name=name)
        self.side, self.front, self.rear = side, front, rear
        self.used = {}
        self.s = dict(self.s)
        if side:
            # the photo says where the wheels are; the dims say how far apart
            # they must be. Keep the photo's overhang split, the dims' wheelbase.
            wb_u = self.WB / self.L
            mid = 0.5 * (side["u_front"] + side["u_rear"])
            self.u_front, self.u_rear = mid + wb_u / 2, mid - wb_u / 2
            self.used["wheels"] = "side photo (overhang split), dims (wheelbase)"
            # landmarks the classifier still reads from `s`
            u, roof = side["u"], side["roof"]
            roof_h = np.percentile(roof, 92)
            hi = np.where(roof >= 0.985 * roof_h)[0]
            self.s["roof_f"] = float(u[hi].max())
            self.s["roof_r"] = float(u[hi].min())
            bon = np.median(roof[(u > 0.78) & (u < 0.9)]) / self.H
            self.s["bonnet_h"] = float(bon)
            # the cowl is the FIRST station back from the nose where the
            # profile climbs clear of the bonnet line: the base of the screen.
            # Taking the last one (as photos_to_glb did) returned the roof's
            # front end instead, and the "bonnet" then ran up the windscreen.
            cowl = None
            for k in range(len(u) - 1, -1, -1):
                if u[k] < self.s["roof_f"]:
                    break
                if roof[k] / self.H > bon + 0.06:
                    cowl = u[k]
                    break
            if cowl:
                self.s["cowl"] = float(cowl)
            self.used["roofline"] = "side photo"
            self.used["sill"] = "side photo" if side.get("sill_from_photo") else "typical rocker height (the cut-out kept the ground shadow)"
            if np.isfinite(side["belt"]).sum() > 20:
                self.used["beltline"] = "side photo"
                self.used["side_glass"] = f"side photo ({len(side.get('windows', []))} windows a side)"
            if side["shut_u"]:
                self.used["shut_lines"] = f"side photo ({len(side['shut_u'])} found)"
        views = [v for v in (front, rear) if v]
        if views:
            # the end views give the section's two identity ratios; the
            # section itself stays the loft's landmark polyline, which is what
            # keeps the creases placed and the regions labelled
            self.s["tumble"] = float(np.mean([v["tumble"] for v in views]))
            self.s["roof_w"] = float(np.mean([v["roof_w"] for v in views]))
            self.used["section"] = "front/rear photo (tumblehome %.2f, roof width %.2f)" % (
                self.s["tumble"], self.s["roof_w"])

    # ── curves along the car ─────────────────────────────────────────────
    def roofline(self, u):
        if not self.side:
            return super().roofline(u)
        return float(np.interp(u, self.side["u"], self.side["roof"]))

    def sill(self, u):
        if not self.side:
            return super().sill(u)
        return float(np.interp(u, self.side["u"], self.side["sill"]))

    def belt_y(self, u):
        if self.side and np.isfinite(self.side["belt"]).sum() > 20:
            b, uu = self.side["belt"], self.side["u"]
            ok = np.isfinite(b)
            # only trust the belt where glass was seen; elsewhere use the ratio
            # the seen part implies
            if uu[ok].min() - 0.03 <= u <= uu[ok].max() + 0.03:
                return float(np.interp(u, uu[ok], b[ok]))
            frac = np.median((b[ok] - np.interp(uu[ok], uu, self.side["sill"])) /
                             (np.interp(uu[ok], uu, self.side["roof"]) - np.interp(uu[ok], uu, self.side["sill"])))
            return self.sill(u) + (self.roofline(u) - self.sill(u)) * float(np.clip(frac, 0.4, 0.75))
        return super().belt_y(u)

    # ── plan view ────────────────────────────────────────────────────────
    def halfwidth(self, u):
        """No photograph here shows the plan, so the nose and tail round off
        with a generic corner: full width to 5% from each end, then a smooth
        fall to half width at the very end, which is what a bumper's corners
        do. The loft's own 85% end was a brick."""
        e = 0.5 * self.W
        t = min(max(u, 0.0), 1.0)
        f = min(max(min(t, 1.0 - t) / 0.05, 0.0), 1.0)
        f = f * f * (3 - 2 * f)
        return e * (0.50 + 0.50 * f)

    # ── section: the glass starts AT the measured beltline ───────────────
    def section(self, u, nv=NV):
        """The loft's landmark polyline, with one change: the measured
        beltline is the bottom of the glass. The base puts region 4 (glass)
        from mid-glass upward, which left every photo-traced window as a thin
        strip under the roof."""
        w = self.halfwidth(u)
        y0, y1 = self.sill(u), self.roofline(u)
        yb = self.belt_y(u)
        s = self.s
        pts = [
            (y0 + 0.02 * (y1 - y0), 0.0),            # 0 floor centre
            (y0 + 0.01 * (y1 - y0), w * 0.55),       # 1 floor edge
            (y0, w * 0.90),                           # 2 sill
            (y0 + (yb - y0) * 0.45, w * 0.995),       # 3 shoulder (widest)
            (yb - 0.012, w * 0.968),                  # 4 just under the belt: body
            (yb, w * 0.962),                          # 5 beltline: glass begins
            (yb + (y1 - yb) * 0.55, w * s["tumble"]),  # 6 mid glass
            (y1 - (y1 - yb) * 0.10, w * s["roof_w"]),  # 7 roof rail
            (y1, w * s["roof_w"] * 0.55),             # 8 roof edge
            (y1, 0.0),                                # 9 roof centre
        ]
        regions = [0, 0, 1, 2, 3, 4, 4, 4, 5, 5]
        crease_landmarks = [2, 3, 5, 7]
        P = np.array(pts, dtype=np.float64)
        d = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
        d /= d[-1]
        t = np.linspace(0, 1, nv)
        out = np.empty((nv, 2))
        for k in range(2):
            out[:, k] = np.interp(t, d, P[:, k])
        reg = np.interp(t, d, regions).round().astype(int)
        crease = np.zeros(nv, dtype=bool)
        for li in crease_landmarks:
            crease[int(np.argmin(np.abs(t - d[li])))] = True
        sm = out.copy()
        sm[1:-1] = 0.25 * out[:-2] + 0.5 * out[1:-1] + 0.25 * out[2:]
        protect = crease.copy()
        protect[1:] |= crease[:-1]
        protect[:-1] |= crease[1:]
        sm[protect] = out[protect]
        return sm, reg, crease

    # ── seams ────────────────────────────────────────────────────────────
    def shut_positions(self):
        base = super().shut_positions()
        if not (self.side and self.side["shut_u"]):
            return base
        s = self.s
        su = self.side["shut_u"]
        arch_f = self.u_front - self.RW / self.L * 1.05     # behind the front arch
        arch_r = self.u_rear + self.RW / self.L * 1.05      # ahead of the rear arch
        doors = {"lead": arch_f, "mid": (arch_f + arch_r) / 2, "trail": arch_r}
        # snap each default door seam to the nearest line the photo showed,
        # within a door's width; a line that matches nothing is ignored
        for k, d in doors.items():
            near = min(su, key=lambda x: abs(x - d))
            if abs(near - d) < 0.08:
                doors[k] = near
        seams = [(s["cowl"] + 0.005, (0, 5)), (doors["lead"], (0, 5)),
                 (doors["mid"], (0, 4)), (doors["trail"], (0, 4)),
                 (s["roof_r"] - 0.01, (3, 5))]
        self.door_seams = doors
        return [(u, r) for u, r in seams if 0.05 < u < 0.97]

    # ── glass from the photo, per loft quad ──────────────────────────────
    def glass_quad(self, u, z, r):
        """True when the side photo shows glass at (u, z). Only asked for the
        side-glass region; the raked screens keep the loft's own rule."""
        if not self.side or not self.side["glass"].any():
            return None
        x0, x1, ground, pxm, facing, zscale = self.side["frame"]
        n = x1 - x0 + 1
        k = (1 - u) * (n - 1) if facing == "left" else u * (n - 1)
        x = int(round(x0 + k))
        y = int(round(ground - z / zscale * pxm))
        g = self.side["glass"]
        if not (0 <= y < g.shape[0] and 0 <= x < g.shape[1]):
            return False
        win = g[max(0, y - 3):y + 4, max(0, x - 3):x + 4]
        return bool(win.mean() > 0.5)
