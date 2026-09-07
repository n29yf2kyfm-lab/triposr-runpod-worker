#!/usr/bin/env python3
"""scale_normalise.py — put a catalogue car back into METRES.

WHY THIS EXISTS. A quarter of this library is not authored at life size.
The 2026-08-21 scale census measured 250 random approved assets and found
**25.2% with a world diagonal under 1 unit, clustered hard at ~0.05**, with
the whole catalogue spanning five orders of magnitude. Every tool in this
repo that carries an absolute distance — a camera lens, a light energy, a
clip plane, a cyclorama radius, a millimetre tolerance — is wrong for those
cars, and it fails SILENTLY:

  * the compression gate's PSNR passed ELEVEN BLANK FRAMES at 46 dB,
    because a 1000 m max orbit blanks a 0.05 m model (recorded 2026-08-21);
  * `showroom.py` rendered volkswagen-golf-2021-w12-v1 as a black fragment
    adrift in the plate (measured 2026-09-07) — the car is **43 mm long**
    in world space, so the studio rig framed and lit a speck.

Neither tool said "this car is 4 cm". They produced a plausible-looking
wrong answer, which is the expensive kind.

THE DEFECT IS A UNIT ERROR, NOT A SHAPE ERROR, and that is what makes it
safe to correct. On the Golf the mesh data is already in metres — accessor
extents 4.295 x 2.094 x 1.489 against a published Mk8 of 4.284 x 1.789 x
1.456 — and a single root node (`FINAL_MODEL_21.fbx`) carries a uniform
0.01, an FBX centimetre conversion applied to data that was already metric.
So the fix is to remove a spurious power of ten, never to restretch a car
onto a target. THIS TOOL WILL NOT STRETCH: it only ever multiplies by a
power of ten, so proportions are mathematically untouched and a car that is
genuinely the wrong SHAPE stays wrong and visible rather than being quietly
fitted to a number.

Refuses rather than guesses when no single power of ten lands the car in
the plausible band — a car that is 1.7x too big is not a unit error, and
silently scaling it would hide whatever really happened.

Edits the glTF JSON with the BIN chunk VERBATIM (the clay_rebuild /
glass_premium discipline), so geometry, UVs, textures, normals, tangents
and every KHR extension pass through untouched. A Blender round trip would
re-encode the textures and drop extensions — measured on 2026-09-07 as
6.68 MB -> 48.04 MB with two materials and two meshes lost.

Run:
  python3 scale_normalise.py <in.glb> <out.glb> [--min 2.0] [--max 7.0]
                             [--report-only]
"""
import argparse
import json
import math
import struct

import numpy as np

# A road car's longest dimension. A smart fortwo is 2.70 m and a long-wheel
# base Sprinter is 7.36 m, so this band is deliberately generous: its job is
# to catch factor-of-ten unit errors, not to police vehicle length.
BAND_LO, BAND_HI = 2.0, 7.0


def read(p):
    d = open(p, "rb").read()
    if d[:4] != b"glTF":
        raise SystemExit(f"REFUSED: {p} is not a binary glTF")
    n = struct.unpack("<I", d[12:16])[0]
    return json.loads(d[20:20 + n]), d[20 + n:]


def write(p, j, rest):
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    with open(p, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + len(rest)))
        f.write(struct.pack("<I", len(js)) + b"JSON" + js + rest)


def node_matrix(nd):
    """glTF stores `matrix` COLUMN-major; TRS is translation @ rotation @ scale."""
    if "matrix" in nd:
        return np.array(nd["matrix"], dtype=float).reshape(4, 4).T
    m = np.eye(4)
    if "scale" in nd:
        m[:3, :3] = np.diag(nd["scale"]) @ m[:3, :3]
    if "rotation" in nd:
        x, y, z, w = nd["rotation"]                     # glTF is (x,y,z,w)
        r = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        m[:3, :3] = r @ m[:3, :3]
    if "translation" in nd:
        m[:3, 3] = nd["translation"]
    return m


def world_bbox(j):
    """Bbox from accessor min/max through the node tree — no BIN decode.

    Cheap enough to run on every asset in the catalogue, which matters:
    this is the check nothing was doing.
    """
    nodes = j.get("nodes", [])
    meshes = j.get("meshes", [])
    acc = j.get("accessors", [])
    scene = j.get("scenes", [{}])[j.get("scene", 0)]
    roots = scene.get("nodes")
    if roots is None:
        kids = {c for nd in nodes for c in nd.get("children", [])}
        roots = [i for i in range(len(nodes)) if i not in kids]
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    seen = 0
    stack = [(i, np.eye(4)) for i in roots]
    while stack:
        i, parent = stack.pop()
        nd = nodes[i]
        M = parent @ node_matrix(nd)
        if nd.get("mesh") is not None:
            for prim in meshes[nd["mesh"]].get("primitives", []):
                a = acc[prim["attributes"]["POSITION"]]
                if "min" not in a or "max" not in a:
                    continue
                mn, mx = a["min"], a["max"]
                corners = np.array([[mn[0] if b & 1 else mx[0],
                                     mn[1] if b & 2 else mx[1],
                                     mn[2] if b & 4 else mx[2], 1.0]
                                    for b in range(8)])
                w = (M @ corners.T).T[:, :3]
                lo = np.minimum(lo, w.min(axis=0))
                hi = np.maximum(hi, w.max(axis=0))
                seen += 1
        for c in nd.get("children", []):
            stack.append((c, M))
    if not seen:
        raise SystemExit("REFUSED: no positioned geometry found — cannot "
                         "measure scale, so cannot correct it")
    return lo, hi, roots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--min", type=float, default=BAND_LO,
                    help="shortest plausible car length in metres")
    ap.add_argument("--max", type=float, default=BAND_HI,
                    help="longest plausible car length in metres")
    ap.add_argument("--report-only", action="store_true",
                    help="measure and print; write nothing")
    a = ap.parse_args()
    if not a.report_only and not a.out:
        raise SystemExit("REFUSED: give an output path, or --report-only")

    j, rest = read(a.inp)
    lo, hi, roots = world_bbox(j)
    ext = hi - lo
    L = float(ext.max())
    print(f"measured world extents "
          f"{ext[0]:.4f} x {ext[1]:.4f} x {ext[2]:.4f} (longest {L:.4f} m)")

    if a.min <= L <= a.max:
        print(f"already life size — inside {a.min}-{a.max} m; nothing to do")
        if a.out and not a.report_only:
            write(a.out, j, rest)
            print(f"copied unchanged to {a.out}")
        return

    # ONLY a power of ten. A unit error is a power of ten; anything else is
    # a modelling problem this tool must not paper over.
    k = 10.0 ** round(math.log10(((a.min + a.max) / 2) / L))
    if not (a.min <= L * k <= a.max):
        raise SystemExit(
            f"REFUSED: longest extent {L:.4f} m, and no power of ten lands "
            f"it inside {a.min}-{a.max} m (x{k:g} gives {L * k:.4f} m). "
            f"That is not a unit error — measure this car before scaling it")
    print(f"unit error: applying x{k:g} -> longest {L * k:.4f} m")

    if a.report_only:
        return

    # Scale ABOVE the roots so nothing below them is touched, and so an
    # instanced master keeps one shared mesh (the recorded instance-collapse
    # class bites anything that rebuilds a scene per geometry).
    S = np.eye(4)
    S[:3, :3] *= k
    for i in roots:
        nd = j["nodes"][i]
        M = S @ node_matrix(nd)
        for key in ("matrix", "translation", "rotation", "scale"):
            nd.pop(key, None)
        nd["matrix"] = [float(x) for x in M.T.reshape(16)]   # back to column-major

    write(a.out, j, rest)

    # verify the WRITTEN file, never the intent
    j2, _ = read(a.out)
    lo2, hi2, _ = world_bbox(j2)
    ext2 = hi2 - lo2
    L2 = float(ext2.max())
    assert a.min <= L2 <= a.max, f"post-scale longest {L2:.4f} m outside band"
    ratio = ext2 / np.maximum(ext, 1e-12)
    assert np.allclose(ratio, k, rtol=1e-6), (
        f"proportions moved: per-axis factors {ratio} against a uniform {k}")
    print(f"verified in {a.out}: "
          f"{ext2[0]:.3f} x {ext2[1]:.3f} x {ext2[2]:.3f} m, "
          f"uniform x{k:g} on all three axes")


if __name__ == "__main__":
    main()
