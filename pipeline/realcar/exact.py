#!/usr/bin/env python3
"""exact.py: a car's own parts, exact, in place of the page's stand-in shapes.

A brake disc is built on the page from its published sizes (diameter, thickness, height, bolt circle, centre
bore). A caliper is a 3D model made from the real part's photo (an image-to-3D model of the catalogue
picture); its size and place come from the disc it fits: the piston's axis on the middle of the disc's
friction ring and the bridge just clear of the disc's rim. Nothing is made up: a part with no photo and no
published sizes keeps the page's own shape.

    python3 pipeline/realcar/exact.py disc OEM --make M --model M --years 1998-2006 --dia 280 --thick 22 \\
        --height 37 --pcd 100 --bolts 5 --bore 65 --hole 15.7 --wheel-offset 38 --source "…"
    python3 pipeline/realcar/exact.py caliper OEM GLB --side right --disc OEM --make M --model M --years 1998-2006 \\
        --photo URL --source "…"
    python3 pipeline/realcar/exact.py look MAKE MODEL YEAR

The parts live in $GLBMACHINE_HOME/parts (parts.json and each model's GLB), not in git: the photos and part
numbers are the owner's catalogue.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engines  # noqa: E402

DIR = os.path.join(engines.HOME, "parts")
INDEX = os.path.join(DIR, "parts.json")


def _load():
    try:
        return json.load(open(INDEX))
    except (OSError, ValueError):
        return {"parts": []}


def _save(idx):
    os.makedirs(DIR, exist_ok=True)
    tmp = INDEX + ".tmp"
    json.dump(idx, open(tmp, "w"), indent=1)
    os.replace(tmp, INDEX)


def _key(oem):
    return re.sub(r"[^0-9A-Z]", "", str(oem).upper())


def _years(s):
    a, _, b = str(s).partition("-")
    return [int(a), int(b or a)]


def _wheel(size, et, height, thick):
    """The room inside a WxD-inch wheel (6x15): the barrel's inner radius (the bead seat's, less 5 mm of steel
    and clearance) and how far the barrel runs in from the disc's middle (half the rim's width, plus the
    offset, less the disc's hat), in metres."""
    w, _, d = str(size).lower().partition("x")
    return {"size": size, "r_in": round(float(d) * 0.0254 / 2 - 0.005, 4),
            "inboard": round((float(w) * 25.4 / 2 + et - (height - thick / 2)) / 1000, 4)}


def _put(idx, entry):
    idx["parts"] = [p for p in idx["parts"] if _key(p["oem"]) != _key(entry["oem"])] + [entry]


def look(make, model, year=None, text="", engine=""):
    """The exact parts listed for this car: {kind: entry}. A part fits when its make matches, its model is a
    word of the car's model, and the car's year is in its years; a request with no year must name the
    generation instead ("mark 4", "Mk4", "IV"), or a Golf of any age would get a Mk4's brakes. A part listed
    for some engines only (a 1.8T has bigger brakes than a 1.9 TDI) needs one of them in the request or in
    the car's ENGINE."""
    out = {}
    words = set(re.findall(r"[a-z0-9]+", f"{model or ''} {text or ''}".lower()))
    said = " " + re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()) + " "
    for p in _load()["parts"]:
        f = p.get("fits") or {}
        if str(f.get("make", "")).lower() != str(make or "").lower():
            continue
        if not set(re.findall(r"[a-z0-9]+", str(f.get("model", "")).lower())) <= words:
            continue
        y0, y1 = f.get("years") or [0, 9999]
        if year:
            if not y0 <= int(year) <= y1:
                continue
        elif not any(f" {g} " in said for g in f.get("generation") or []):
            continue
        if f.get("engines") and not any(e.lower() in f"{text} {engine}".lower() for e in f["engines"]):
            continue
        if p.get("file") and not os.path.exists(os.path.join(DIR, p["file"])):
            continue
        out.setdefault(p["kind"], p)
    return out


# ── a caliper model fitted to its disc ──────────────────────────────────────────────────────────────────────

def fit_caliper(glb, disc, wheel=None, samples=400000):
    """Where the disc sits in a caliper model, and the model's scale, from the model's own shape.

    The disc's slot is the run along one axis where the model is thin (only the bridge crosses it); the side
    of the slot the model reaches further is the piston's (a floating caliper's fingers are short). The
    piston's axis is the round hole in the housing's face. The bridge is on the far side of the slot's
    material from the disc's centre. Two facts then fix the rest: the piston presses on the middle of the
    friction ring, and nothing in the slot may come within the disc's radius (3 mm clear). WHEEL ({r_in, inboard}:
    the barrel's inner radius and how far in from the disc's middle its inner edge is) keeps it inside the rim."""
    import numpy as np
    import trimesh
    m = trimesh.load(glb).to_geometry()
    p, _ = trimesh.sample.sample_surface(m, samples, seed=2)
    v = np.vstack([p, m.vertices])
    lo, hi = v.min(0), v.max(0)
    R, T, rin = disc["R"], disc["T"], disc["rIn"]
    rmid = (rin + R) / 2

    def profile(ax, bins=40):
        o = [i for i in range(3) if i != ax]
        zs = np.linspace(lo[ax], hi[ax], bins + 1)
        occ = []
        for a, b in zip(zs[:-1], zs[1:]):
            q = v[(v[:, ax] >= a) & (v[:, ax] < b)][:, o]
            g = np.zeros((24, 48), bool)
            if len(q):
                ij = ((q - lo[o]) / (hi[o] - lo[o]) * [23.999, 47.999]).astype(int)
                g[ij[:, 0], ij[:, 1]] = True
            occ.append(g.sum())
        return zs, np.array(occ, float)

    best = None
    for ax in range(3):
        zs, occ = profile(ax)
        full = np.percentile(occ, 85)
        low = occ < 0.5 * full
        # the longest run of thin slices that does not touch either end
        run, i = None, 1
        while i < len(low) - 1:
            if low[i]:
                j = i
                while j + 1 < len(low) - 1 and low[j + 1]:
                    j += 1
                if not run or j - i > run[1] - run[0]:
                    run = (i, j)
                i = j + 1
            else:
                i += 1
        if run and (best is None or run[1] - run[0] > best[1][1] - best[1][0]):
            best = (ax, run, zs)
    if not best:
        raise ValueError("no disc slot found in the caliper model")
    ax, (i, j), zs = best
    z0, z1 = zs[i], zs[j + 1]
    zc = (z0 + z1) / 2
    out_sign = 1 if (hi[ax] - z1) < (z0 - lo[ax]) else -1          # the fingers' side: the shorter one
    others = [k for k in range(3) if k != ax]
    ext = hi - lo
    tan = max(others, key=lambda k: ext[k])                          # the pins run along the disc's edge
    rad = min(others, key=lambda k: ext[k])

    # the piston's axis: the round hole in the housing, just behind its face
    from shapely.geometry import Polygon
    zf = z0 - 0.06 * ext[ax] if out_sign > 0 else z1 + 0.06 * ext[ax]
    bore = None
    for zz in (zf, zf - out_sign * 0.04 * ext[ax], zf - out_sign * 0.1 * ext[ax]):
        sec = m.section(plane_origin=[zz if k == ax else 0 for k in range(3)],
                        plane_normal=[1 if k == ax else 0 for k in range(3)])
        if sec is None:
            continue
        loops = [np.asarray(d)[:, [rad, tan]] for d in sec.discrete]
        polys = [Polygon(L) for L in loops if len(L) > 3]
        polys = [q for q in polys if q.is_valid and q.area > 0]
        big = max(polys, key=lambda q: q.area, default=None)
        holes = [q for q in polys if q is not big and big is not None and big.contains(q.representative_point())
                 and 4 * np.pi * q.area / q.length ** 2 > 0.7]         # round
        if holes:
            h = max(holes, key=lambda q: q.area)
            bore = (h.centroid.x, h.centroid.y)
            break
    if bore is None:
        raise ValueError("no piston bore found in the caliper model")
    xb, yb = bore

    # the slot's material is the bridge, on the outside of the disc: the disc's centre lies the other way
    def slab(k):
        return v[np.abs(v[:, ax] - zc) <= (T / 2 + 0.002) / k]
    q = slab(0.2)
    to_c = -1 if np.median(q[:, rad]) > xb else 1
    def tight(k_):
        """The disc's centre for scale K_: as close as the slot's material lets it, 3 mm clear of the rim."""
        q = slab(k_)

        def clear(d):
            return np.hypot(q[:, rad] - d, q[:, tan] - yb).min() * k_
        a_, b_ = 1e-4 * ext.max(), 4.0 * ext.max()
        for _ in range(40):
            mid = (a_ + b_) / 2
            a_, b_ = (a_, mid) if clear(xb + to_c * mid) >= R + 0.003 else (mid, b_)
        return xb + to_c * b_

    def reach(d, k_):
        """How far from the axle the part reaches inside the wheel's barrel (axially, from the disc's middle
        to the rim's inner edge)."""
        inb = v[(v[:, ax] - zc) * out_sign >= -(wheel or {}).get("inboard", 9) / k_]
        return np.hypot(inb[:, rad] - d, inb[:, tan] - yb).max() * k_

    # the scale: the piston on the middle of the friction ring (the piston's axis is the hole in the
    # housing) ...
    a_, b_ = 0.02, 2.0                                              # the piston's radius falls as K grows
    for _ in range(40):
        mid = (a_ + b_) / 2
        a_, b_ = (mid, b_) if abs(tight(mid) - xb) * mid >= rmid else (a_, mid)
    k = a_
    fitted_by = "piston on the middle of the friction ring, bridge 3 mm clear of the disc's rim"
    # ... unless that is too big for the wheel: a model from one photo guesses its depth, and the real part
    # goes inside its wheel. Then the largest that clears the disc and goes in the wheel
    if wheel and reach(tight(k), k) > wheel["r_in"]:
        a_, b_ = 0.02, k
        for _ in range(30):
            mid = (a_ + b_) / 2
            a_, b_ = (mid, b_) if reach(tight(mid), mid) <= wheel["r_in"] else (a_, mid)
        k = a_
        fitted_by = "the largest that clears the disc's rim by 3 mm and goes inside the wheel"
    xc = tight(k)
    centre = [0.0, 0.0, 0.0]
    centre[ax], centre[rad], centre[tan] = float(zc), float(xc), float(yb)
    size = (ext * k * 1000).round(1).tolist()
    return {"scale": round(float(k), 5), "centre": [round(c, 5) for c in centre],
            "axial": ax, "axial_out": out_sign, "radial": rad, "to_centre": to_c, "tangential": tan,
            "fitted_by": fitted_by,
            **({"wheel_r_in_mm": round(wheel["r_in"] * 1000, 1),
                "fits_wheel": bool(reach(xc, k) <= wheel["r_in"])} if wheel else {}),
            "check_mm": {"size": size, "slot": round((z1 - z0) * k * 1000, 1),
                         "piston_radius": round(abs(xc - xb) * k * 1000, 1),
                         "reach_in_wheel": round(reach(xc, k) * 1000, 1)}}


def _node(script, *args):
    env = dict(os.environ)
    try:
        env.setdefault("NODE_PATH", subprocess.check_output(["npm", "root", "-g"], text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        pass
    subprocess.run(["node", os.path.join(HERE, script), *args], check=True, env=env, cwd=HERE)


def slim(src, dst, triangles=24000):
    """An image-to-3D part (two million triangles, three 4K maps) cut down for a phone: about TRIANGLES
    triangles, 512-pixel maps, meshopt-packed."""
    import trimesh
    n = sum(len(g.faces) for g in trimesh.load(src).geometry.values())
    tmp = dst + ".slim.glb"
    _node("slim.mjs", src, tmp, str(min(1.0, triangles / max(n, 1))))
    import ai_parts
    ai_parts.shrink_images(tmp, px=512, quality=85)
    return tmp


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("disc", "caliper"):
        s = sub.add_parser(name)
        s.add_argument("oem")
        if name == "caliper":
            s.add_argument("glb")
            s.add_argument("--side", choices=("left", "right"), required=True)
            s.add_argument("--disc", required=True, help="the disc's OEM number (add it first)")
            s.add_argument("--photo", required=True)
            s.add_argument("--maker", default="image-to-3D from the catalogue photo")
        else:
            for f in ("dia", "thick", "height", "pcd", "bore", "hole"):
                s.add_argument("--" + f, type=float, required=True)
            s.add_argument("--bolts", type=int, default=5)
            s.add_argument("--vented", action="store_true")
            s.add_argument("--wheel-offset", type=float, required=True, help="the wheel's ET, mm")
            s.add_argument("--wheel", required=True, help="the smallest wheel it is fitted with: '6x15' (inches)")
        s.add_argument("--label", default="")
        s.add_argument("--make", required=True)
        s.add_argument("--model", required=True)
        s.add_argument("--years", required=True)
        s.add_argument("--generation", default="", help="words that name it without a year: 'mark 4,mk4,iv'")
        s.add_argument("--engines", default="", help="only for these engines: '1.9,2.0'")
        s.add_argument("--source", required=True, help="where the sizes or the photo come from")
    s = sub.add_parser("look")
    s.add_argument("make")
    s.add_argument("model")
    s.add_argument("year", nargs="?")
    a = ap.parse_args(argv)
    if a.cmd == "look":
        print(json.dumps(look(a.make, a.model, a.year, " ".join([a.model] + ([a.year] if a.year else []))), indent=1))
        return
    idx = _load()
    fits = {"make": a.make, "model": a.model, "years": _years(a.years),
            "generation": [g.strip().lower() for g in a.generation.split(",") if g.strip()],
            "engines": [e.strip() for e in a.engines.split(",") if e.strip()]}
    if a.cmd == "disc":
        mm = lambda x: round(x / 1000, 5)                              # noqa: E731
        dims = {"R": mm(a.dia / 2), "T": mm(a.thick), "H": mm(a.height), "pcd": mm(a.pcd / 2),
                "bore": mm(a.bore / 2), "hole": mm(a.hole / 2), "bolts": a.bolts, "vented": a.vented,
                # what the published sizes leave open, in the usual proportions of a vented disc
                "rIn": mm(a.dia / 2 * 0.665), "hatR": mm(a.pcd / 2 + a.hole + 13),
                "cheek": mm(a.thick * (0.3 if a.vented else 0.5))}
        entry = {"kind": "disc", "oem": a.oem, "label": a.label or "Brake disc", "fits": fits, "dims": dims,
                 "wheel_offset": mm(a.wheel_offset), "wheel": _wheel(a.wheel, a.wheel_offset, a.height, a.thick),
                 "source": a.source}
    else:
        disc = next((p for p in idx["parts"] if p["kind"] == "disc" and _key(p["oem"]) == _key(a.disc)), None)
        if not disc:
            raise SystemExit(f"add the disc {a.disc} first")
        os.makedirs(DIR, exist_ok=True)
        f = _key(a.oem) + ".glb"
        tmp = slim(a.glb, os.path.join(DIR, f))
        fit = fit_caliper(tmp, disc["dims"], disc.get("wheel"))
        _node("encode.mjs", tmp, os.path.join(DIR, f))
        os.remove(tmp)
        entry = {"kind": "caliper", "oem": a.oem, "label": a.label or "Brake caliper", "side": a.side,
                 "disc": disc["oem"], "fits": fits, "file": f, "fit": fit,
                 "source": a.source, "photo": a.photo, "maker": a.maker}
    _put(idx, entry)
    _save(idx)
    print(json.dumps(entry, indent=1))


if __name__ == "__main__":
    main()
