#!/usr/bin/env python3
"""orient_catalogue.py — rotate an authored car GLB to the CATALOGUE axes.

The carglb chain authors in its own frame (length on X, nose +X, Y up) —
every internal tool (fit_panes, wheel_swap, photo_project) assumes it. The
CATALOGUE convention, measured on the shipped Golf GTI mk8 (2026-08-15), is
length on Z with the NOSE at -Z, Y up. The mismatch is not cosmetic: the
studio rig's azimuths are absolute, so at az 125 the catalogue car shows its
front-right three-quarter and the carglb car showed its front-LEFT — every
tile in a wave sheet would be the wrong view.

Fix = one rotation, +90 degrees about Y: x' = z, y' = y, z' = -x
(nose +X -> nose -Z; determinant +1, no mirror). Applied as a root-node
QUATERNION with the BIN chunk copied verbatim — the pose_fix pattern, so it
cannot damage geometry, normals or windings by construction.

Usage:
    python3 pipeline/carglb/orient_catalogue.py in.glb out.glb
(in-place is fine: pass the same path twice)
"""
import json
import struct
import sys

# +90 about Y as glTF [x, y, z, w]
QUAT = [0.0, 0.7071067811865476, 0.0, 0.7071067811865476]


def orient(src, dst):
    raw = open(src, "rb").read()
    magic, ver, total = struct.unpack("<III", raw[:12])
    assert magic == 0x46546C67, "not a GLB"
    jlen, jtype = struct.unpack("<II", raw[12:20])
    assert jtype == 0x4E4F534A
    gltf = json.loads(raw[20:20 + jlen])
    rest = raw[20 + jlen:]                      # BIN chunk(s), verbatim

    scene = gltf.get("scenes", [{}])[gltf.get("scene", 0)]
    roots = scene.get("nodes", [])
    if not roots:
        raise SystemExit("GLB has no scene roots")
    for ni in roots:
        node = gltf["nodes"][ni]
        if "matrix" in node:
            raise SystemExit(f"root node {ni} uses a matrix — refusing to "
                             "compose; re-author instead")
        if "rotation" in node and node["rotation"] != [0, 0, 0, 1]:
            raise SystemExit(f"root node {ni} already rotated "
                             f"({node['rotation']}) — refusing to compose "
                             "blind; already oriented?")
        node["rotation"] = QUAT
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    out = struct.pack("<III", magic, ver, 12 + 8 + len(js) + len(rest))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js + rest
    open(dst, "wb").write(out)
    print(f"oriented to catalogue axes (length Z, nose -Z): {dst}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    orient(sys.argv[1], sys.argv[2])
