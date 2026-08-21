#!/usr/bin/env python3
"""cabin_rigcfg.py — write the cabin gate's frozen camera config without Blender.

`cabin/aperture_open.py` rasterises the car through `raster.cams_from_cfg`,
which reads `rig_cfg.json`.  That file is normally produced as a side effect of
running `cabin/cabin_rig.py` INSIDE Blender, which freezes ABSOLUTE camera
transforms so a later edit to the car cannot move them.

The cameras are a pure function of the car's Blender-space bounding box, so
reproducing that function here costs nothing and removes a Blender round-trip
from the pipeline.  The formula below is `cabin_rig.py`'s, line for line:

    CTR  = bbox centre           DIAG = bbox diagonal
    r    = DIAG * dist_mult
    loc  = CTR + (r cos(az) cos(el), r sin(az) cos(el), r sin(el) + DIAG*0.055)
    look = CTR

and the axis map is `raster.gltf_to_blender`: (x, y, z)_gltf -> (x, -z, y).

The eight views are the ones the cabin gate itself froze, so the operation
replayed here is the operation that gate ran.
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glbmeas                                                   # noqa: E402

VIEWS = {"az180_e08": (180.0, 8.0), "az145_e10": (145.0, 10.0),
         "az215_e10": (215.0, 10.0), "az270_e05": (270.0, 5.0),
         "az090_e05": (90.0, 5.0), "az035_e10": (35.0, 10.0),
         "az325_e10": (325.0, 10.0), "az000_e08": (0.0, 8.0)}


def write(glb, out, hide=()):
    """hide: node-name prefixes excluded from the bbox, as cabin_rig's hide= is."""
    g = glbmeas.GLB(glb)
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    for ni, name, W, mi in g.graph():
        if name.startswith(tuple(hide)) if hide else False:
            continue
        for p in g.g["meshes"][mi]["primitives"]:
            V = g.accessor(p["attributes"]["POSITION"]).astype(np.float64)
            V = V @ W[:3, :3].T + W[:3, 3]
            lo = np.minimum(lo, V.min(0))
            hi = np.maximum(hi, V.max(0))
    # glTF -> Blender
    B = np.array([[lo[0], hi[0]], [-hi[2], -lo[2]], [lo[1], hi[1]]])
    CTR = [float((a + b) / 2) for a, b in B]
    DIAG = float(math.sqrt(sum((b - a) ** 2 for a, b in B)))
    cfg = {"resolution": [1400, 900], "beauty_samples": 96,
           "world_rgb": [0.22, 0.22, 0.23],
           "sun": {"energy": 3.2, "euler_deg": [52, 0, 150], "angle_deg": 1.5},
           "fill": {"energy": 1.1, "euler_deg": [62, 0, -40]},
           "lens_mm": 62.0, "dist_mult": 2.35,
           "views": {k: list(v) for k, v in VIEWS.items()},
           "cameras": {}, "_bbox_blender": B.tolist(), "_diag": DIAG,
           "_source": os.path.abspath(glb)}
    for name, (az, el) in VIEWS.items():
        r = DIAG * cfg["dist_mult"]
        a, e = math.radians(az), math.radians(el)
        cfg["cameras"][name] = {
            "loc": [CTR[0] + r * math.cos(a) * math.cos(e),
                    CTR[1] + r * math.sin(a) * math.cos(e),
                    CTR[2] + r * math.sin(e) + DIAG * 0.055],
            "look": list(CTR)}
    json.dump(cfg, open(out, "w"), indent=1)
    return cfg


if __name__ == "__main__":
    c = write(sys.argv[1], sys.argv[2])
    print(f"froze {len(c['cameras'])} cameras, diag {c['_diag']:.4f} -> {sys.argv[2]}")
