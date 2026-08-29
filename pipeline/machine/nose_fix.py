#!/usr/bin/env python3
"""nose_fix.py — put the car's NOSE at +x, before anything depends on it.

THE GAP THIS FILLS. canon.py says outright that it does not resolve nose
direction — the OBB's axes carry a sign ambiguity — and until now nothing in
tripo_car.sh resolved it either. The overnight run of 2026-08-29 proved the
cost: same chain, two cars, and the Yaris landed nose-forward while the Golf
came out 180 degrees reversed, so its "front34_R" render showed the
tailgate. A coin flip, which is exactly how an unresolved sign behaves.

It has to be decided EARLY — right after deyaw, before the view set — because
lamp_boost picks its "nose views" by view index (view_00 = az 0) before any
label exists. Get the sign wrong and it boosts the tail lamps.

THREE CUES, measured on the two overnight cars where the answer is known
(Yaris nose=+x, Golf nose=-x):

    cue                             Yaris     Golf
    flat-up faces front:rear         3.36     0.08     <- 40x separation
    greenhouse centre (xf)           0.389    0.640
    roof-top mean y, +x minus -x    -0.032   +0.040

  1. BONNET. A bonnet is a large near-horizontal upward surface; a tailgate
     is short and steep. Count strongly up-facing faces in the bonnet height
     band at each end. Much the strongest cue.
  2. GREENHOUSE CENTRE. On a hatch the cabin sits rearward of mid-length, so
     the tall geometry's centre falls on the tail side.
  3. ROOF PEAK. The roof is higher over the cabin than over the nose.

TWO OF THREE MUST AGREE, and the tool REFUSES when they do not — the
canon_dims pattern, adopted after a single-cue rule flipped a correct car
earlier in the same session. A wrong flip is worse than a refusal: it puts
headlamps on the tailgate and every kit on the wrong end.

The flip is a root-node quaternion with the BIN chunk VERBATIM (the pose_fix
pattern), 180 degrees about Y — a proper rotation, determinant +1, so
winding and normals stay valid.

Run: python3 nose_fix.py <in.glb> <out.glb> [--report r.json]
"""
import argparse
import json
import os
import struct

import numpy as np
import trimesh


def read_glb(path):
    d = open(path, "rb").read()
    if d[:4] != b"glTF":
        raise SystemExit(f"REFUSED: {path} is not a binary glTF")
    n = struct.unpack("<I", d[12:16])[0]
    return json.loads(d[20:20 + n]), d[20 + n:]


def write_glb(path, j, rest):
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    with open(path, "wb") as fh:
        fh.write(b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + len(rest)))
        fh.write(struct.pack("<I", len(js)) + b"JSON" + js)
        fh.write(rest)


def cues(path):
    # WORLD SPACE, via the scene graph. Concatenating sc.geometry.values()
    # reads RAW vertices and is blind to a root-node transform — the recorded
    # trimesh trap ("Scene.apply_transform stores a ROOT NODE transform;
    # geometry.vertices still shows pre-transform coords"). It bit here
    # immediately: the 180 flip was applied correctly and this function
    # reported it had not landed, because it never saw the transform.
    sc = trimesh.load(path, force="scene")
    parts = []
    for node in sc.graph.nodes_geometry:
        T, gname = sc.graph[node]
        g = sc.geometry[gname].copy()
        g.apply_transform(T)
        parts.append(g)
    m = trimesh.util.concatenate(parts) if len(parts) > 1 else parts[0]
    v, c, n = m.vertices, m.triangles_center, m.face_normals
    x0, x1 = v[:, 0].min(), v[:, 0].max()
    y0, y1 = v[:, 1].min(), v[:, 1].max()
    L, H = x1 - x0, y1 - y0
    xf, yf = (c[:, 0] - x0) / L, (c[:, 1] - y0) / H

    up = n[:, 1] > 0.80
    band = (yf > 0.55) & (yf < 0.75)
    f_flat = int((up & band & (xf > 0.78)).sum())
    r_flat = int((up & band & (xf < 0.22)).sum())
    bonnet = "+x" if f_flat > r_flat else "-x"

    tall = yf > 0.80
    gh = float(np.percentile(xf[tall], [2, 98]).mean()) if tall.any() else 0.5
    greenhouse = "+x" if gh < 0.5 else "-x"

    topq = yf > 0.90
    fr = float(c[topq & (xf > 0.5)][:, 1].mean())
    re = float(c[topq & (xf < 0.5)][:, 1].mean())
    roof = "+x" if fr < re else "-x"

    return {"bonnet": bonnet, "bonnet_ratio": f_flat / max(r_flat, 1),
            "bonnet_front": f_flat, "bonnet_rear": r_flat,
            "greenhouse": greenhouse, "greenhouse_centre": gh,
            "roof": roof, "roof_front_y": fr, "roof_rear_y": re}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    q = cues(a.inp)
    votes = [q["bonnet"], q["greenhouse"], q["roof"]]
    plus = votes.count("+x")
    print(f"nose cues: bonnet {q['bonnet']} (front {q['bonnet_front']} : rear "
          f"{q['bonnet_rear']}, ratio {q['bonnet_ratio']:.2f})")
    print(f"           greenhouse {q['greenhouse']} (centre {q['greenhouse_centre']:.3f})")
    print(f"           roof {q['roof']} (+x {q['roof_front_y']:.3f} / "
          f"-x {q['roof_rear_y']:.3f})")

    if plus not in (0, 3) and max(plus, 3 - plus) < 2:
        raise SystemExit("REFUSED: nose cues disagree — a wrong flip puts the "
                         "headlamps on the tailgate; decide by eye and pin it")
    nose = "+x" if plus >= 2 else "-x"
    agree = max(plus, 3 - plus)
    print(f"verdict: nose at {nose} ({agree}/3 cues agree)")
    if agree < 3:
        print("  NOTE: one cue dissented — worth an eye check on the render")

    q.update({"verdict": nose, "agree": agree, "flipped": nose == "-x"})
    if a.report:
        json.dump(q, open(a.report, "w"), indent=1)

    j, rest = read_glb(a.inp)
    if nose == "+x":
        write_glb(a.out, j, rest)
        print(f"already nose-forward — copied to {a.out}")
        return

    # 180 about Y as a root-node quaternion: (x,y,z,w) = (0,1,0,0)
    scene = j.get("scenes", [{}])[j.get("scene", 0)]
    roots = list(scene.get("nodes", []))
    j.setdefault("nodes", []).append(
        {"name": "nose_fix_180", "children": roots,
         "rotation": [0.0, 1.0, 0.0, 0.0]})
    scene["nodes"] = [len(j["nodes"]) - 1]
    write_glb(a.out, j, rest)

    after = cues(a.out)
    if after["bonnet"] != "+x":
        raise SystemExit("REFUSED: the flip did not land — bonnet cue still "
                         f"says {after['bonnet']}")
    print(f"flipped 180 about Y; bonnet cue now {after['bonnet']} "
          f"(ratio {after['bonnet_ratio']:.2f})")
    print(f"wrote {a.out} ({os.path.getsize(a.out)} bytes; BIN verbatim)")


if __name__ == "__main__":
    main()
