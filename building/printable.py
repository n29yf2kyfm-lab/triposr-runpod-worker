"""A physical scale model of the measured building — binary STL.

The same geometry that priced the job, shrunk to something a builder can
hand a client across a table. Pure stdlib: STL is a dumb format and this
writes it directly, the way write_glb and write_ifc do.

WHAT MAKES THIS DIFFERENT FROM AN EXPORT. Shrinking a building is where
architectural prints fail: detail that is comfortable at full size goes
below the printer's minimum feature and simply does not appear. Run our
own walls through it (docs/IMAGE_TO_3D.md):

    at 1:100  a 300mm external wall prints 3.0mm  — comfortable
              a 100mm partition    prints 1.0mm  — UNDER the 1.5mm floor
    at 1:50   that same partition  prints 2.0mm  — fine

So this module enforces a minimum printed thickness, thickens whatever
would fall under it, and REPORTS every element it changed. A model that
silently dropped its internal walls would still look like the house from
the outside, which is exactly the sort of quiet wrongness this codebase
refuses.

Watertightness, honestly stated: each element (wall segment, slab, roof,
base) is written as its own closed manifold solid, and they overlap where
they meet. Every slicer unions overlapping closed solids at slice time —
Cura, PrusaSlicer, Bambu and Orca all do. This is NOT a boolean union of
the building into one shell; doing that properly needs a CSG kernel, and
claiming it without one would be a lie about precision.
"""
import struct

import model3d as M

# FDM minimums (docs/IMAGE_TO_3D.md, sourced from Raise3D/Formlabs/BigRep).
# 1.5mm is the reliable floor for PLA; a 0.4mm nozzle likes multiples of
# its own width, so 1.6mm is the honest target once anything is thickened.
MIN_WALL_MM = 1.5
NOZZLE_MM = 0.4
MIN_FEATURE_MM = 0.8            # supported detail: cills, ridge capping

DEFAULT_SCALE = 50              # 1:50 — the scale a 100mm partition survives
BASE_PLATE_MM = 2.0             # presentation base under the model
BASE_MARGIN_MM = 5.0


def _nozzle_round(mm):
    """Round a thickened feature UP to a whole number of nozzle widths."""
    n = max(1, int(mm / NOZZLE_MM + 0.999))
    return round(n * NOZZLE_MM, 3)


class _Mesh:
    """Triangles in printed millimetres, built from metres."""

    def __init__(self, scale_denom):
        self.tris = []
        self.k = 1000.0 / float(scale_denom)     # metres -> printed mm

    def v(self, x, y, z):
        # plan (x, y, z) -> print (x, y, z) with Y-up handled by the
        # slicer's Z: keep plan Y as the bed's Y and height as Z, which is
        # how a building sits on a print bed.
        return (x * self.k, y * self.k, z * self.k)

    def tri(self, a, b, c):
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = (uy * vz - uz * vy, uz * vx - ux * vz,
                      ux * vy - uy * vx)
        ln = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
        self.tris.append(((nx / ln, ny / ln, nz / ln), a, b, c))

    def quad(self, a, b, c, d):
        self.tri(a, b, c)
        self.tri(a, c, d)

    def box(self, x0, y0, z0, x1, y1, z1):
        """A closed rectangular solid, outward normals."""
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        if z1 < z0:
            z0, z1 = z1, z0
        V = self.v
        a, b = V(x0, y0, z0), V(x1, y0, z0)
        c, d = V(x1, y1, z0), V(x0, y1, z0)
        e, f = V(x0, y0, z1), V(x1, y0, z1)
        g, h = V(x1, y1, z1), V(x0, y1, z1)
        self.quad(a, d, c, b)          # bottom (normal -z)
        self.quad(e, f, g, h)          # top
        self.quad(a, b, f, e)          # y0
        self.quad(b, c, g, f)          # x1
        self.quad(c, d, h, g)          # y1
        self.quad(d, a, e, h)          # x0

    def bbox_mm(self):
        xs = [p[0] for t in self.tris for p in t[1:]]
        ys = [p[1] for t in self.tris for p in t[1:]]
        zs = [p[2] for t in self.tris for p in t[1:]]
        if not xs:
            return (0.0, 0.0, 0.0)
        return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))

    def write(self, path, title):
        with open(path, "wb") as fh:
            fh.write(title.encode("ascii", "replace")[:79].ljust(80, b"\0"))
            fh.write(struct.pack("<I", len(self.tris)))
            for n, a, b, c in self.tris:
                fh.write(struct.pack("<12fH", *n, *a, *b, *c, 0))
        return path


def _roof_solid(mesh, roof):
    """The roof as a closed prism per range — slopes, ends and a soffit.

    write_obj draws the roof as open planes, which is right for viewing and
    unprintable: a surface has no thickness and a slicer has nothing to
    fill. Closing the underside turns each range into a solid the printer
    can actually make.
    """
    ez = roof.get("eaves_tip_z_m", roof["eaves_z_m"])
    rz = roof["ridge_z_m"]
    along_x = roof["along_x"]
    V = mesh.v
    for band in roof.get("range_list") or [
            {"band_m": roof["footprint_m"], "ridge": roof["ridge"]}]:
        bx0, bx1 = band["band_m"]["x"]
        by0, by1 = band["band_m"]["y"]
        (r0x, r0y), (r1x, r1y) = band["ridge"]
        a, b = V(bx0, by0, ez), V(bx1, by0, ez)
        c, d = V(bx1, by1, ez), V(bx0, by1, ez)
        r0, r1 = V(r0x, r0y, rz), V(r1x, r1y, rz)
        mesh.quad(a, d, c, b)                       # soffit, closes it
        if along_x:
            mesh.quad(a, b, r1, r0)                 # front slope
            mesh.quad(c, d, r0, r1)                 # back slope
            mesh.tri(d, a, r0)
            mesh.tri(b, c, r1)
        else:
            mesh.quad(b, c, r1, r0)
            mesh.quad(d, a, r0, r1)
            mesh.tri(a, b, r0)
            mesh.tri(c, d, r1)


def build(model, scale_denom=DEFAULT_SCALE, base_plate=True,
          min_wall_mm=MIN_WALL_MM):
    """Solid geometry for printing, plus the report of what changed."""
    mesh = _Mesh(scale_denom)
    k = mesh.k
    storeys = int(model.get("storeys") or 1)
    per = float(model.get("storey_height_m") or M.DEFAULT_CEILING_HEIGHT_M)
    x0, x1 = model["extent_m"]["x"]
    y0, y1 = model["extent_m"]["y"]

    thickened, min_seen = [], None
    for level in range(storeys):
        z = level * per
        mesh.box(x0, y0, z - M.DEFAULT_SLAB_M, x1, y1, z)
        for i, w in enumerate(model["walls"]):
            if not M._wall_on_level(w, level):
                continue
            t_m = float(w["thickness_m"])
            printed = t_m * 1000.0 / scale_denom
            min_seen = printed if min_seen is None else min(min_seen, printed)
            if printed < min_wall_mm:
                want = _nozzle_round(min_wall_mm)
                t_m = want * scale_denom / 1000.0
                if level == 0:
                    thickened.append({
                        "wall": i, "kind": "external" if w.get("external")
                        else "partition",
                        "as_designed_mm": round(printed, 2),
                        "printed_mm": want,
                        "as_designed_m": round(float(w["thickness_m"]), 3),
                        "printed_as_m": round(t_m, 3)})
            t = t_m / 2.0
            (ax, ay), (bx, by) = w["start"], w["end"]
            if abs(bx - ax) >= abs(by - ay):
                lo, hi = sorted((ax, bx))
                for s, e, zlo, zhi in M._split_for_openings(lo, hi, w, level):
                    mesh.box(s, ay - t, z + zlo, e, ay + t, z + zhi)
            else:
                lo, hi = sorted((ay, by))
                for s, e, zlo, zhi in M._split_for_openings(lo, hi, w, level):
                    mesh.box(ax - t, s, z + zlo, ax + t, e, z + zhi)

    for cap in model.get("caps") or []:
        cx, cy, cz = cap["x"], cap["y"], cap["z_m"]
        mesh.box(cx[0], cy[0], cz - M.DEFAULT_SLAB_M, cx[1], cy[1], cz)

    if model.get("roof"):
        _roof_solid(mesh, model["roof"])

    if base_plate:
        m = BASE_MARGIN_MM / k                      # printed mm -> metres
        d = BASE_PLATE_MM / k
        mesh.box(x0 - m, y0 - m, -M.DEFAULT_SLAB_M - d,
                 x1 + m, y1 + m, -M.DEFAULT_SLAB_M)

    w_mm, d_mm, h_mm = mesh.bbox_mm()
    report = {
        "scale": f"1:{scale_denom}",
        "triangles": len(mesh.tris),
        "size_mm": {"x": round(w_mm, 1), "y": round(d_mm, 1),
                    "z": round(h_mm, 1)},
        "min_wall_mm": round(min_seen, 2) if min_seen is not None else None,
        "min_wall_rule_mm": min_wall_mm,
        "thickened": thickened,
        "base_plate": bool(base_plate),
        "notes": [
            "Millimetres, as every slicer expects.",
            "Elements are separate closed solids that overlap where they "
            "meet; slicers union them at slice time. This is not a boolean "
            "union of the building into one shell.",
            "Openings are cut as real voids — the walls are split around "
            "them, not textured.",
        ],
    }
    if thickened:
        report["notes"].append(
            f"{len(thickened)} wall type(s) fell below the {min_wall_mm}mm "
            f"printable minimum at 1:{scale_denom} and were thickened; "
            "the printed model is therefore not dimensionally true for "
            "those elements. Print at a larger scale for a true model.")
    if max(w_mm, d_mm) > 250.0:
        report["notes"].append(
            f"{max(w_mm, d_mm):.0f}mm across — larger than a common 220-256mm "
            "bed. Print in parts or reduce the scale.")
    return mesh, report


def write_stl(model, path, scale_denom=DEFAULT_SCALE, base_plate=True):
    """Write the printable model; returns (path, report)."""
    mesh, report = build(model, scale_denom=scale_denom,
                         base_plate=base_plate)
    title = (f"{model['totals']['rooms']} rooms "
             f"{model['totals']['floor_area_m2']}m2 at 1:{scale_denom}")
    mesh.write(path, title)
    report["path"] = path
    return path, report


def describe(report):
    lines = [f"Scale model {report['scale']} — "
             f"{report['size_mm']['x']:.0f} x {report['size_mm']['y']:.0f} x "
             f"{report['size_mm']['z']:.0f} mm, "
             f"{report['triangles']:,} triangles"]
    for t in report["thickened"]:
        lines.append(
            f"  thickened {t['kind']}: {t['as_designed_m']*1000:.0f}mm wall "
            f"would print {t['as_designed_mm']}mm -> {t['printed_mm']}mm")
    lines += ["  " + n for n in report["notes"]]
    return "\n".join(lines)
