#!/usr/bin/env python3
"""clay_geoclass.py — DOES NOT WORK AS WRITTEN. Kept as a measured negative.

STATUS 2026-08-13: the v1 heuristics below FAIL their control. Do not use this
to rebuild a car, and do not rebuild this approach the same way.

The idea is the owner's and it is sound: a material bound to four cylindrical
clusters at the corners IS a tyre whatever the exporter called it, so junk-named
clay cars (Astra L `1129_0`, Astra H `956_3`) could be recovered from geometry.
The implementation is what is wrong.

CONTROL RUN, on the Juke 2023 whose material NAMES are known correct:
    interior     -> "paint"      (wrong: interior is the LARGEST material, 31.6%)
    body         -> "interior"
    glass/d_glass/r_glass/o_glass -> "trim"/"interior"  (all wrong)
    tire_mat4    -> "trim"
Almost every verdict disagreed with a known-good name.

WHY, measured from the printed table: nearly every material spans 0.03-0.97 of
the car's length and 0.00-1.00 of its height, because A MATERIAL IS NOT ONE
PART. It is shared across many scattered pieces — four tyres at both ends, six
window panes, trim on every panel — so the per-material bounding box covers the
whole car and carries no positional signal at all. Every rule here reads that
bbox, so every rule is reading noise. The second error is independent: "biggest
area = body" is false, because a modelled interior has more surface than the
outer shell.

WHAT A WORKING VERSION NEEDS (not attempted here):
  * per-PIECE statistics, clustered — decide "four low cylinders at the corners"
    from the pieces, then vote the material, never from the union bbox;
  * an outside-visibility test to separate shell from cabin (ray-cast from
    outside, as hybrid_transfer.refine already does for interior bleed);
  * validation against BOTH controls before any use: a known-good-name car must
    reproduce its own names, and a junk-name car must produce a sane table.
The rest of the file is left intact as the starting point for that work.

Original design notes follow.

"""
_UNUSED_DOC = """clay_geoclass v1 design notes.

Owner's idea 2026-08-13: "junk name we could rename to correct cars".

clay_rebuild classifies a converter-clay car by material NAME, which fails
completely when the exporter wrote numbers: the Astra L ships `1129_0 ...
1129_9`, the Astra H `956_0 ...`, and those cars are unrecoverable by name
even though their geometry is fine and their bindings are intact. Tonight
that blocked more clay cars than it recovered.

But a material bound to four cylindrical clusters at the corners of the car
IS a tyre, whatever it is called. This module measures each material's
geometry in a normalised car frame and names it from physics:

    tyre      low, at 2+ wheel corners, ring-shaped (outer radius band)
    rim       low, at wheel corners, inside the tyre radius
    glass     greenhouse band, sloped/vertical, modest area
    paint     largest area, spans most of the car's length and width
    lamp      at a length end, mid height, small area
    plate     tiny, flat, at a length end, near the centreline
    interior  inset from BOTH width extremes (hidden inside the shell)
    trim      everything else — dark, which is the safe default

Deliberately conservative: anything it cannot place with confidence stays
"trim" rather than being guessed onto the paint, because a wrong paint call
repaints the whole car. It reports a table so the operator sees what it did
before a render is paid for — same contract as clay_rebuild's mapping table.

Usage:
    clay_geoclass.py --in clay.glb [--json out.json]
    clay_geoclass.py --in clay.glb --out rebuilt.glb     # classify AND write
"""
import argparse
import collections
import json
import os
import sys

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from clay_rebuild import PBR, classify as name_classify, rebuild_from_map  # noqa: E402


def _frame(scene):
    """Normalised car frame: X length, Y up (glTF), Z width, 0..1 on each."""
    v = np.concatenate([g.vertices for g in scene.geometry.values()])
    lo = np.percentile(v, 1, axis=0)
    hi = np.percentile(v, 99, axis=0)
    ext = np.maximum(hi - lo, 1e-9)
    # glTF is Y-up; length is the longer of X/Z
    LEN, WID = (0, 2) if ext[0] >= ext[2] else (2, 0)
    return [LEN, 1, WID], lo, ext


def measure(path):
    """Per-material geometry stats in the normalised frame."""
    scene = trimesh.load(path, process=False)
    if not isinstance(scene, trimesh.Scene):
        scene = trimesh.Scene(scene)
    axes, lo, ext = _frame(scene)
    lo_a, ext_a = lo[axes], ext[axes]

    stats = collections.defaultdict(lambda: {
        "area": 0.0, "lo": [9e9] * 3, "hi": [-9e9] * 3,
        "n_up": 0.0, "pieces": 0, "corners": set()})
    total = 0.0
    for g in scene.geometry.values():
        mat = getattr(getattr(g.visual, "material", None), "name", None) or "(unnamed)"
        p = (g.vertices[:, axes] - lo_a) / ext_a
        s = stats[mat]
        a = float(g.area)
        s["area"] += a
        total += a
        s["pieces"] += 1
        s["lo"] = [min(s["lo"][i], float(p[:, i].min())) for i in range(3)]
        s["hi"] = [max(s["hi"][i], float(p[:, i].max())) for i in range(3)]
        if len(g.faces):
            s["n_up"] += float(np.abs(g.face_normals[:, 1]).mean()) * a
        # which quarter of the car does this piece sit in
        c = p.mean(axis=0)
        s["corners"].add((c[0] > 0.5, c[2] > 0.5))
    for s in stats.values():
        s["frac"] = s["area"] / max(total, 1e-9)
        s["n_up"] = s["n_up"] / max(s["area"], 1e-9)
        s["corners"] = len(s["corners"])
    return dict(stats)


def geo_classify(stats):
    """Name each material from where its geometry sits. Physics, not strings."""
    out = {}
    # the body is the biggest thing that spans the car
    spans = {m: (s["hi"][0] - s["lo"][0]) * (s["hi"][2] - s["lo"][2])
             for m, s in stats.items()}
    body = max(stats, key=lambda m: stats[m]["frac"] * (0.4 + spans[m]))
    for m, s in stats.items():
        lo_l, lo_u, lo_w = s["lo"]
        hi_l, hi_u, hi_w = s["hi"]
        span_l, span_u, span_w = hi_l - lo_l, hi_u - lo_u, hi_w - lo_w
        low = hi_u < 0.45                       # entirely below the beltline
        ends = lo_l > 0.80 or hi_l < 0.20       # nose or tail only
        if m == body:
            out[m] = "paint"
        elif low and s["corners"] >= 2 and span_l > 0.35 and s["frac"] > 0.01:
            # spread across both ends AND low = the four wheels, one material
            out[m] = "tyre" if s["frac"] > 0.03 else "rim"
        elif low and s["corners"] >= 2:
            out[m] = "rim"
        elif lo_u > 0.45 and s["n_up"] < 0.75 and 0.005 < s["frac"] < 0.30:
            out[m] = "glass"                    # greenhouse, not roof-flat
        elif ends and s["frac"] < 0.05 and 0.25 < (lo_u + hi_u) / 2 < 0.75:
            out[m] = "lamp"
        elif s["frac"] < 0.004 and span_u < 0.12 and ends:
            out[m] = "plate"
        elif lo_w > 0.12 and hi_w < 0.88:
            out[m] = "interior"                 # inset from both flanks
        else:
            out[m] = "trim_matt"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", help="write a rebuilt GLB using these classes")
    ap.add_argument("--json", help="write the classification table")
    a = ap.parse_args()

    stats = measure(a.src)
    cls = geo_classify(stats)
    print(f"{'material':26s} {'class':10s} {'area%':>6} {'len':>11} {'up':>11} corners")
    for m, s in sorted(stats.items(), key=lambda kv: -kv[1]["frac"]):
        print(f"  {m[:24]:24s} {cls[m]:10s} {100*s['frac']:5.1f}% "
              f"{s['lo'][0]:.2f}-{s['hi'][0]:.2f} {s['lo'][1]:.2f}-{s['hi'][1]:.2f} "
              f"{s['corners']}")
    print("classes:", dict(collections.Counter(cls.values())))
    if a.json:
        json.dump({m: {"class": cls[m], **{k: v for k, v in s.items()}}
                   for m, s in stats.items()}, open(a.json, "w"), indent=1)
    if a.out:
        rebuild_from_map(a.src, a.out, cls)
        print("WROTE", a.out)


if __name__ == "__main__":
    main()
