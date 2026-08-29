#!/usr/bin/env python3
"""carspec.py — take every measurement off a known-good car ONCE, then hold
every other car to it.

WHY THIS EXISTS. Owner, after a day of me setting thresholds one at a time
off generated cars: "clone the model, take all the measurements out, make a
tool, so each car comes and the tool can adjust for the repairs." Correct,
and it is what this repo's own standing rule already demanded — *a
threshold with no positive control behind it is a guess* — while I was
measuring the patient with the patient.

Before this, every number in the chain came from somewhere different: the
glass band from ten mixed catalogue cars, the pillar width from one dark
Golf, the interior tones from a render, the level tolerance from nothing at
all. Each was calibrated in isolation and several were wrong in ways only
the owner's eye caught. A car has ONE set of proportions and they are all
related; measure them together, from one asset that is known to be right.

  extract  read a reference GLB, write a complete profile as JSON
  check    measure any car the same way, print the deviation table, and
           exit non-zero when something is outside tolerance

AXIS CONVENTION IS DETECTED, NOT ASSUMED. Catalogue cars are length-on-Z
with the nose at -Z; the machine authors length-on-X. This project has
burned renders on that difference more than once, so the longest horizontal
extent decides, and the profile records which axis it found.

WHAT IT MEASURES, and every one of these has already gone wrong once:

    proportions   W/L and H/L, wheelbase and overhangs as fractions of
                  length — so they survive any scaling
    stance        the four tyre contact patches: pitch, roll, and their
                  height above the model floor. The reference GTI sits at
                  0.0 mm; a car shipped today at 150 mm nose-up.
    glazing       glass as a share of total surface area. The reference is
                  5.33%; our generated cars run 6.49-9.25%, so the
                  1.0-13.0% band in use is wide enough to pass a car with
                  a fifth too much glass.
    greenhouse    beltline and roof height as fractions of car height, and
                  the DLO band. The interior kit needs the beltline and
                  had to measure it itself; now it is in the profile.
    budget        face count and per-material area shares. The reference
                  is 97k faces against our 1.5M.

WHAT IT DELIBERATELY DOES NOT DO. It does not move geometry. Scaling is
canon.py's job and levelling is level_car.py's; a tool that both measures
and corrects can always report success. This one only ever measures, so its
verdict cannot be contaminated by its own repair.

Run: python3 carspec.py extract <ref.glb> <profile.json> [--name NAME]
     python3 carspec.py check   <car.glb> <profile.json> [--tol 0.15]
"""
import argparse
import json
import re
import sys

import numpy as np
import trimesh

GLASSY = ("glass", "window", "windscreen", "screen", "glazing")
TYREY = ("tyre", "tire", "rubber", "pneu")
PAINTY = ("paint", "carpaint", "coloured", "body")


class CarSpec:
    """Per-car specification file — the OTHER half of this module.

    RESTORED 2026-08-29. The reference-profile tool below was written into
    this file and SILENTLY REPLACED this class, which ten stages import
    (canon, canon_dims, fit_spec, wheel_stage, glass_stage, glass_presplit,
    aperture_clean, surface_stage, semantic_rebind, body_align). Every one
    of them died at `ImportError: cannot import name 'CarSpec'` the next
    time a car went through the chain from stage one — found by running it,
    not by reading it, which is this repo's whole point.

    The two live together deliberately: the class is the LIBRARY (published
    dimensions, tyre fitment, label conventions, read by stage code) and the
    `extract`/`check` CLI below is the TOOL (measures a real asset). They
    describe the same car from opposite directions and neither is a
    replacement for the other.

    The machine is CAR-AGNOSTIC SOFTWARE. Everything that describes a
    particular vehicle lives in a JSON spec file, never in stage code.
    Stage code reads the spec; anything the spec does not provide is
    MEASURED from the geometry and tagged "approximate" in the stage's QC
    output (rule: approximate data is never presented as verified OEM data).

    Spec format — every dimension is {"value": <num>, "source": <str>} so
    the number carries its provenance; omit a key entirely when unknown.

        {"identity":   {"make": ..., "model": ..., "note": ...},
         "dimensions": {"length_m": {...}, "width_m": {...},
                        "height_m": {...}, "wheelbase_m": {...},
                        "track_front_m": {...}, "track_rear_m": {...}},
         "tyre":       {"spec": "175/65R15", "source": ...},
         "labels":     {"body": "carpaint", "wheel_strip_prefixes": [...]},
         "expect":     {"axle_x": {...}, "tolerance_m": 0.06}}

    Use: spec = CarSpec.load("specs/toyota_yaris_xp130.json")
         spec.dim("track_front_m")   -> (value, source) or (None, None)
         spec.tyre()                 -> dict of tyre dims + provenance
    """

    def __init__(self, data, path="<inline>"):
        self.data = data
        self.path = path

    @classmethod
    def load(cls, path):
        with open(path) as f:
            return cls(json.load(f), path)

    @classmethod
    def empty(cls, note="no spec supplied — all values measured"):
        return cls({"identity": {"note": note}}, "<none>")

    def identity(self):
        return self.data.get("identity", {})

    def dim(self, key):
        d = self.data.get("dimensions", {}).get(key)
        if d is None:
            return None, None
        return float(d["value"]), d.get("source", "spec file (source untagged)")

    def label(self, key, default):
        return self.data.get("labels", {}).get(key, default)

    def expect(self):
        return self.data.get("expect", {})

    def tyre(self):
        """Parse a tyre spec string like '175/65R15' into metric dims."""
        t = self.data.get("tyre", {})
        s = t.get("spec")
        if not s:
            return None
        m = re.match(r"^\s*(\d{3})\s*/\s*(\d{2})\s*R?\s*(\d{2})\s*$", s)
        if not m:
            raise ValueError(f"unparseable tyre spec {s!r} in {self.path}")
        w = int(m.group(1)) / 1000.0
        aspect = int(m.group(2)) / 100.0
        rim_d = int(m.group(3)) * 0.0254
        return {"spec": s, "source": t.get("source", "spec file"),
                "width_m": w, "aspect": aspect, "rim_d_m": rim_d,
                "radius_m": rim_d / 2 + w * aspect,
                "rim_r_m": rim_d / 2}


def world_parts(path):
    sc = trimesh.load(path, force="scene")
    out = []
    for node in sc.graph.nodes_geometry:
        T, g = sc.graph[node]
        m = sc.geometry[g].copy()
        m.apply_transform(T)
        mat = getattr(getattr(m.visual, "material", None), "name", "") or ""
        out.append((g, mat, m))
    return out


def pick(parts, words, exclude=()):
    hit = []
    for g, mat, m in parts:
        s = f"{g} {mat}".lower()
        if any(w in s for w in words) and not any(x in s for x in exclude):
            hit.append(m)
    return trimesh.util.concatenate(hit) if hit else None


def measure(path):
    parts = world_parts(path)
    if not parts:
        raise SystemExit(f"REFUSED: no geometry in {path}")
    allm = trimesh.util.concatenate([m for _, _, m in parts])
    b = allm.bounds
    ext = b[1] - b[0]

    # LENGTH AXIS IS DETECTED. Catalogue cars are length-on-Z, the machine
    # authors length-on-X, and this project has burned renders on the
    # difference. Longest horizontal extent wins; Y is always up.
    horiz = [0, 2]
    LA = horiz[int(np.argmax([ext[0], ext[2]]))]
    WA = 2 if LA == 0 else 0
    L, W, H = float(ext[LA]), float(ext[WA]), float(ext[1])

    d = {"length_axis": "xyz"[LA], "L": L, "W": W, "H": H,
         "W_over_L": W / L, "H_over_L": H / L,
         "faces": int(sum(len(m.faces) for _, _, m in parts))}

    tot = float(allm.area)
    glass = pick(parts, GLASSY, exclude=("mirror", "surround"))
    tyre = pick(parts, TYREY)
    paint = pick(parts, PAINTY, exclude=("glass",))
    # OUTER SKIN ONLY, for comparability. The reference GTI is
    # DOUBLE-SKINNED (Glass_* outside, GlassInside_* within) and counting
    # both gives 9.32% against 5.33% for the outer alone. Our chain builds a
    # single skin, so the outer figure is the like-for-like one; the total
    # is kept beside it because the double skin is itself worth copying.
    outer = pick(parts, GLASSY, exclude=("mirror", "surround", "inside",
                                         "interior"))
    # GLASS / L^2 IS THE PRIMARY MEASURE, and "% of total area" is kept only
    # as a secondary because it is DENOMINATOR-DEPENDENT and it lied badly.
    # Against the GTI reference it reported the generated Golf as having 65%
    # too much glazing, and I nearly eroded the glass label on that. The
    # rival test - compare ABSOLUTE areas - says otherwise:
    #
    #                       GTI        generated
    #   total surface     68.898 m2   44.363 m2
    #   interior          37.1%       13.2%      <- the entire difference
    #   glass absolute     3.669 m2    3.911 m2   x1.066
    #   glass / L^2        0.1812      0.2157     x1.190
    #   glass / total      5.33%       8.82%      x1.655   <- the bad metric
    #
    # The reference has a fully modelled interior and ours does not, so its
    # total surface area is 1.55x larger and every "% of total" figure is
    # scaled by that. The true excess is ~19% on a scale-free measure, not
    # 65%. Acting on the percentage would have cut 40% of the glazing off a
    # car whose glass area is within 7% of a real one.
    d["glass_over_L2"] = float(outer.area) / (L * L) if outer is not None else None
    d["glass_area_m2"] = float(outer.area) if outer is not None else None
    d["total_area_m2"] = tot
    d["glass_area_pct"] = 100 * float(outer.area) / tot if outer is not None else None
    d["glass_area_pct_all_skins"] = (100 * float(glass.area) / tot
                                     if glass is not None else None)
    d["paint_area_pct"] = 100 * float(paint.area) / tot if paint is not None else None

    # STANCE, from the contact patches. Never the lowest vertex — on the car
    # that shipped nose-up the lowest vertex was the interior shell.
    if tyre is not None:
        v = tyre.vertices
        ctr = 0.5 * (b[0] + b[1])
        cps = {}
        for nm, kl, kw in (("FR", 1, 1), ("FL", 1, -1),
                           ("RR", -1, 1), ("RL", -1, -1)):
            k = (np.sign(v[:, LA] - ctr[LA]) == kl) & \
                (np.sign(v[:, WA] - ctr[WA]) == kw)
            if k.sum() < 20:
                cps = {}
                break
            c = v[k]
            cps[nm] = float(c[c[:, 1] <= np.percentile(c[:, 1], 3)][:, 1].mean())
        if cps:
            wb = abs(0.5 * (v[np.sign(v[:, LA] - ctr[LA]) == 1][:, LA].mean()) -
                     0.5 * (v[np.sign(v[:, LA] - ctr[LA]) == -1][:, LA].mean())) * 2
            lo = min(cps.values())
            d["stance"] = {
                "patch_spread_mm": 1000 * (max(cps.values()) - lo),
                "above_floor_mm": 1000 * (lo - float(b[0][1])),
                "pitch_mm": 1000 * (0.5 * (cps["FR"] + cps["FL"])
                                    - 0.5 * (cps["RR"] + cps["RL"])),
                "roll_mm": 1000 * (0.5 * (cps["FR"] + cps["RR"])
                                   - 0.5 * (cps["FL"] + cps["RL"])),
                "wheelbase_over_L": float(wb) / L}

    # GREENHOUSE, as fractions of height so they survive scaling
    if glass is not None:
        c = glass.triangles_center
        n = glass.face_normals
        # UPPER HALF ONLY. Without it the reference returned a beltline at
        # 0.192 H and a 995 mm DLO — impossible for a hatchback, and it was
        # reading the inner glazing skin and the lamp lenses. A beltline is
        # by definition in the top half of the car.
        side = (np.abs(n[:, WA]) > 0.55) & \
               (np.abs(c[:, WA] - 0.5 * (b[0][WA] + b[1][WA])) > 0.25 * W) & \
               (c[:, 1] > b[0][1] + 0.45 * H)
        if side.sum() > 100:
            y = c[side][:, 1]
            belt, rail = float(np.percentile(y, 2)), float(np.percentile(y, 98))
            d["greenhouse"] = {
                "belt_frac_H": (belt - float(b[0][1])) / H,
                "rail_frac_H": (rail - float(b[0][1])) / H,
                "dlo_band_mm": 1000 * (rail - belt)}
    return d


FIELDS = [("W_over_L", "width / length", 0.06),
          ("H_over_L", "height / length", 0.06),
          ("glass_over_L2", "glass / length^2", 0.20),
          ("glass_area_pct", "glass % of area *", 0.30),
          ("paint_area_pct", "paint % of area *", 0.40)]
NESTED = [("greenhouse", "belt_frac_H", "beltline / height", 0.10),
          ("greenhouse", "rail_frac_H", "roofline / height", 0.06),
          ("stance", "wheelbase_over_L", "wheelbase / length", 0.06)]
ABS = [("stance", "patch_spread_mm", "tyre patch spread", 8.0),
       ("stance", "above_floor_mm", "tyres above floor", 8.0),
       ("stance", "pitch_mm", "stance pitch", 12.0),
       ("stance", "roll_mm", "stance roll", 12.0)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("extract", "check"))
    ap.add_argument("glb")
    ap.add_argument("profile")
    ap.add_argument("--name", default=None)
    ap.add_argument("--tol", type=float, default=1.0,
                    help="multiplier on every per-field tolerance")
    a = ap.parse_args()

    m = measure(a.glb)
    if a.mode == "extract":
        m["_reference"] = a.name or a.glb
        json.dump(m, open(a.profile, "w"), indent=1)
        print(f"reference: {m['_reference']}  (length on {m['length_axis']})")
        print(f"  L {m['L']:.3f}  W {m['W']:.3f}  H {m['H']:.3f}   "
              f"W/L {m['W_over_L']:.4f}  H/L {m['H_over_L']:.4f}")
        if m.get("glass_area_pct") is not None:
            print(f"  glass {m['glass_area_pct']:.2f}% of area (outer skin; "
                  f"{m['glass_area_pct_all_skins']:.2f}% counting both), "
                  f"paint {m['paint_area_pct']:.2f}%")
        if "stance" in m:
            s = m["stance"]
            print(f"  stance: spread {s['patch_spread_mm']:.1f} mm, "
                  f"{s['above_floor_mm']:.1f} mm above the floor, "
                  f"pitch {s['pitch_mm']:+.1f} mm")
        if "greenhouse" in m:
            g = m["greenhouse"]
            print(f"  beltline {g['belt_frac_H']:.3f} H, "
                  f"roofline {g['rail_frac_H']:.3f} H, "
                  f"DLO {g['dlo_band_mm']:.0f} mm")
        print(f"  faces {m['faces']}")
        print(f"wrote {a.profile}")
        return

    ref = json.load(open(a.profile))
    print(f"reference: {ref.get('_reference','?')}")
    print(f"{'quantity':24s} {'reference':>11s} {'this car':>11s} "
          f"{'delta':>9s}  verdict")
    bad = 0
    def row(label, r, v, tol, rel, unit=""):
        nonlocal bad
        if r is None or v is None:
            print(f"  {label:22s} {'n/a':>11s} {'n/a':>11s} "
                  f"{'':>9s}  NOT MEASURED")
            return
        dv = v - r
        off = (abs(dv) / abs(r) > tol * a.tol) if rel else (abs(dv) > tol * a.tol)
        bad += int(off)
        pct = f"{100*dv/r:+.1f}%" if rel else f"{dv:+.1f}{unit}"
        print(f"  {label:22s} {r:11.4f} {v:11.4f} {pct:>9s}  "
              f"{'OUT' if off else 'ok'}")
    for key, label, tol in FIELDS:
        row(label, ref.get(key), m.get(key), tol, True)
    for grp, key, label, tol in NESTED:
        row(label, (ref.get(grp) or {}).get(key), (m.get(grp) or {}).get(key),
            tol, True)
    for grp, key, label, tol in ABS:
        row(label, (ref.get(grp) or {}).get(key), (m.get(grp) or {}).get(key),
            tol, False, " mm")
    print(f"\n  faces {ref.get('faces')} -> {m.get('faces')} "
          f"({m.get('faces',0)/max(ref.get('faces',1),1):.1f}x the reference)")
    print("\n  * denominator-dependent: a reference with a fully modelled "
          "interior has a much\n    larger total area, so these read high on "
          "a car without one. Judge glazing\n    on glass / length^2.")
    print(f"\n{bad} quantity(ies) outside tolerance")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
