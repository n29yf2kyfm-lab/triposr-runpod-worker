#!/usr/bin/env python3
"""normalmap_scale.py — attenuate (or remove) a baked normal map by name.

WHY. On the Tripo v3.1 Golf the owner flagged "bonnet reflections are
jagged/wavy -- possible topology or normal problems". Topology was
EXONERATED by measurement, not assumed: the clay pass shows smooth panels
and the world-normal pass shows smooth gradients, so the mesh and its vertex
normals are both fine. The decisive test was an A/B at one locked camera --
same mesh, same lights, normalTexture strength forced to 0 -- and the jagged
patches became clean continuous sweeps. The cause is the GENERATOR'S BAKED
NORMAL MAP, which encodes photographic shading noise as surface relief.

This matters because the instinctive fix is the wrong one. Smoothing the
MESH to cure a normal-MAP artefact destroys real geometry: this project has
already measured Taubin smoothing taking crease density 145 -> 36, and even
one iteration costing a third of sharp_share. The map is the thing to turn
down, and it is a single float per material in the glTF JSON.

`normalTexture.scale` is the glTF-standard multiplier on the map's X and Y
(the spec's `scaledNormal = normalize((<sampled> * 2 - 1) * vec3(scale,
scale, 1))`), so 0 is flat and 1 is as-baked. Default when absent is 1.

The BIN chunk is copied VERBATIM -- geometry, UVs and the texture images are
untouched, so this is reversible by re-running with --scale 1 and cannot
damage the mesh (the clay_rebuild / pose_fix pattern).

Run:
  python3 normalmap_scale.py <in.glb> <out.glb> --scale 0.3 [--materials carpaint,...]
"""
import argparse
import json
import os
import struct
import sys


def read_glb(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != b"glTF":
        raise SystemExit(f"REFUSED: {path} is not a binary glTF")
    n = struct.unpack("<I", data[12:16])[0]
    j = json.loads(data[20:20 + n])
    return j, data[20 + n:]


def write_glb(path, j, rest):
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + len(rest)
    with open(path, "wb") as fh:
        fh.write(b"glTF" + struct.pack("<II", 2, total))
        fh.write(struct.pack("<I", len(js)) + b"JSON" + js)
        fh.write(rest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--scale", type=float, required=True,
                    help="0 = flat, 1 = as baked")
    ap.add_argument("--materials", default=None,
                    help="comma list; default = every material with a normalTexture")
    a = ap.parse_args()
    if not 0.0 <= a.scale <= 4.0:
        raise SystemExit("REFUSED: --scale outside a sane 0..4")

    j, rest = read_glb(a.inp)
    want = set(a.materials.split(",")) if a.materials else None
    touched, skipped = [], []
    for m in j.get("materials", []):
        name = m.get("name", "")
        nt = m.get("normalTexture")
        if nt is None:
            continue
        if want is not None and name not in want:
            skipped.append(name)
            continue
        before = nt.get("scale", 1.0)
        nt["scale"] = a.scale
        touched.append((name, before, a.scale))

    if not touched:
        # a no-op write is the documented failure class: it ships a file that
        # looks like a fix and changes nothing
        raise SystemExit(
            f"REFUSED: no material was modified (materials with a normalTexture: "
            f"{[m.get('name') for m in j.get('materials', []) if 'normalTexture' in m]})")

    write_glb(a.out, j, rest)

    # verify by READING BACK, not by trusting the write
    j2, _ = read_glb(a.out)
    bad = [m.get("name") for m in j2.get("materials", [])
           if "normalTexture" in m and m.get("name") in {t[0] for t in touched}
           and abs(m["normalTexture"].get("scale", 1.0) - a.scale) > 1e-6]
    if bad:
        raise SystemExit(f"REFUSED: scale did not persist for {bad}")
    for name, b, af in touched:
        print(f"  {name}: normalTexture.scale {b} -> {af}")
    if skipped:
        print(f"  untouched (not selected): {skipped}")
    print(f"wrote {a.out} ({os.path.getsize(a.out)} bytes; BIN verbatim, "
          f"{len(touched)} material(s) rescaled)")


if __name__ == "__main__":
    main()
