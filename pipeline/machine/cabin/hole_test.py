#!/usr/bin/env python3
"""hole_test.py — prove the deletions opened NO hole in the car.

15 directions (az 0/+-22/+-40 x el 0/+-18), rasterised with the validated
camera model. Two measurements per direction, over the OPAQUE set (everything
except the four glazing nodes):

  LOST SILHOUETTE : a pixel the BEFORE car covered and the AFTER car does not.
                    Outside the glazing apertures this must be ZERO — that is
                    the actual claim "no hole was opened".
  DEEPER          : a pixel where the AFTER car's nearest opaque surface is
                    more than THRESH behind the BEFORE car's. Inside the
                    apertures this is the INTENDED effect (the blocking skin is
                    gone). Outside them it would be a hole.

NEGATIVE CONTROL (--controls): a copy of the AFTER car with 4,000 extra faces
deleted from the MIDDLE of the main body shell must make both numbers fire.
A test that cannot fail is not a test.

Run: python3 hole_test.py <before.glb> <after.glb> [--controls]
"""
import json
import sys
import numpy as np
import trimesh
import raster

BEF, AFT = sys.argv[1], sys.argv[2]
CONTROLS = "--controls" in sys.argv
GLAZE = {"Glass_Rear", "Glass_Windscreen", "Glass_Side_L", "Glass_Side_R"}
THRESH = 0.05          # m
DIRS = [(az, el) for el in (-18, 0, 18) for az in (0, -22, 22, -40, 40)]


def opaque(path, drop_middle=0):
    sc = trimesh.load(path, force="scene", process=False)
    V, F = [], []
    for node in sc.graph.nodes_geometry:
        T, gn = sc.graph[node]
        if node in GLAZE:
            continue
        g = sc.geometry[gn]
        f = np.asarray(g.faces)
        if drop_middle and node == "Body_Shell":
            v = trimesh.transform_points(g.vertices, T)
            fc = v[f].mean(1)
            # a compact patch on the flank, well away from any aperture
            d = (fc[:, 0] - 0.55) ** 2 + (fc[:, 1] - 0.62) ** 2 + \
                (fc[:, 2] + 0.79) ** 2
            kill = np.argsort(d)[:drop_middle]
            m = np.ones(len(f), bool)
            m[kill] = False
            f = f[m]
        F.append(f + sum(len(x) for x in V))
        V.append(trimesh.transform_points(g.vertices, T))
    return raster.gltf_to_blender(np.vstack(V)), np.vstack(F)


def glaze(path):
    sc = trimesh.load(path, force="scene", process=False)
    V, F = [], []
    for node in sc.graph.nodes_geometry:
        if node not in GLAZE:
            continue
        T, gn = sc.graph[node]
        g = sc.geometry[gn]
        F.append(np.asarray(g.faces) + sum(len(x) for x in V))
        V.append(trimesh.transform_points(g.vertices, T))
    return raster.gltf_to_blender(np.vstack(V)), np.vstack(F)


def cams(Vb):
    lo, hi = Vb.min(0), Vb.max(0)
    ctr = (lo + hi) / 2
    diag = float(np.linalg.norm(hi - lo))
    out = {}
    for az, el in DIRS:
        a, e = np.radians(az), np.radians(el)
        r = diag * 2.2
        loc = [ctr[0] + r * np.cos(a) * np.cos(e),
               ctr[1] + r * np.sin(a) * np.cos(e), ctr[2] + r * np.sin(e)]
        out[f"az{az:+04d}_el{el:+03d}"] = raster.Cam(loc, ctr, 62.0, (1100, 720))
    return out


def run(Vb, Fb, Va, Fa, Vg, Fg, tag):
    C = cams(Vb)
    tot = {"lost_out": 0, "lost_in": 0, "deeper_out": 0, "deeper_in": 0,
           "gained_out": 0, "shallower_out": 0, "before_px": 0}
    worst = []
    for name, cam in C.items():
        ib, zb = raster.rasterise(cam, Vb, Fb)
        ia, za = raster.rasterise(cam, Va, Fa)
        _, zg = raster.rasterise(cam, Vg, Fg)
        AP = np.isfinite(zg)                     # a glazing pane covers it
        hb, ha = ib > 0, ia > 0
        lost = hb & ~ha
        gained = ha & ~hb                       # a part sticking out BEYOND the body
        shallower = hb & ha & (zb > za + THRESH)  # a part in FRONT of solid skin
        deeper = hb & ha & (za > zb + THRESH)
        tot["before_px"] += int(hb.sum())
        tot["lost_out"] += int((lost & ~AP).sum())
        tot["lost_in"] += int((lost & AP).sum())
        tot["deeper_out"] += int((deeper & ~AP).sum())
        tot["deeper_in"] += int((deeper & AP).sum())
        tot["gained_out"] = tot.get("gained_out", 0) + int((gained & ~AP).sum())
        tot["shallower_out"] = tot.get("shallower_out", 0) + int((shallower & ~AP).sum())
        worst.append((name, int((lost & ~AP).sum()), int((deeper & ~AP).sum())))
        print(f"  {name}: car={int(hb.sum()):7d}  lost out/in="
              f"{int((lost&~AP).sum()):5d}/{int((lost&AP).sum()):5d}  "
              f"deeper out/in={int((deeper&~AP).sum()):5d}/"
              f"{int((deeper&AP).sum()):5d}")
    print(f"[{tag}] TOTALS over {len(C)} directions, {tot['before_px']} car px")
    print(f"[{tag}]   LOST SILHOUETTE outside apertures : {tot['lost_out']} "
          f"({100*tot['lost_out']/tot['before_px']:.5f}%)")
    print(f"[{tag}]   DEEPER outside apertures          : {tot['deeper_out']} "
          f"({100*tot['deeper_out']/tot['before_px']:.5f}%)")
    print(f"[{tag}]   GAINED silhouette outside apert.  : {tot['gained_out']} "
          f"({100*tot['gained_out']/tot['before_px']:.5f}%)   <- a cabin part beyond the body")
    print(f"[{tag}]   SHALLOWER outside apertures       : {tot['shallower_out']} "
          f"({100*tot['shallower_out']/tot['before_px']:.5f}%)   <- a cabin part through the skin")
    print(f"[{tag}]   (inside apertures, intended)      : lost {tot['lost_in']}"
          f"  deeper {tot['deeper_in']}")
    return tot


Vb, Fb = opaque(BEF)
Va, Fa = opaque(AFT)
Vg, Fg = glaze(AFT)
print(f"before opaque {len(Fb)} faces, after {len(Fa)} faces "
      f"({len(Fb)-len(Fa)} deleted)")
real = run(Vb, Fb, Va, Fa, Vg, Fg, "REAL")

if CONTROLS:
    print("\nNEGATIVE CONTROL: after-car with 4000 extra body faces deleted")
    Vc, Fc = opaque(AFT, drop_middle=4000)
    ctl = run(Vb, Fb, Vc, Fc, Vg, Fg, "CTRL")
    fired = ctl["deeper_out"] > 100 * max(real["deeper_out"], 1) or \
        ctl["lost_out"] > 100 * max(real["lost_out"], 1) or \
        (ctl["deeper_out"] + ctl["lost_out"]) > 500
    print(f"\nCONTROL {'FIRES' if fired else '*** DID NOT FIRE — TEST IS VOID ***'}")
    json.dump({"real": real, "control": ctl, "control_fired": bool(fired),
               "directions": len(DIRS), "thresh_m": THRESH},
              open("hole_test.json", "w"), indent=1)
else:
    json.dump({"real": real, "directions": len(DIRS), "thresh_m": THRESH},
              open("hole_test.json", "w"), indent=1)
print("wrote hole_test.json")
