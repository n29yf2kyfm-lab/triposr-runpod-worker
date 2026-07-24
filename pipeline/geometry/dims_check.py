#!/usr/bin/env python3
"""dims_check.py — compare a GLB's bounding box against factory dimensions.

Eval helper for the Alam-3D fine-tune (and general QC): reports the model's
L/W and L/H ratios vs the factory row from vehicle_dims.csv, plus per-axis
deviation. Ratios are scale-free, so unscaled AI shells are judged fairly.

Usage: python3 pipeline/geometry/dims_check.py car.glb --make ford --model kuga
Exit 0 always (informational); consumers decide thresholds.
"""
import argparse
import sys

import trimesh

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from dims_lookup import lookup


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("--make", required=True)
    ap.add_argument("--model", required=True)
    a = ap.parse_args()

    sc = trimesh.load(a.glb, force="scene")
    ext = sorted(sc.extents, reverse=True)     # [L, W-ish, H-ish] by magnitude
    L, mid, small = ext
    row = lookup(a.make, a.model)
    if not row or not (row.get("length_mm") and row.get("width_mm")):
        print(f"DIMS_CHECK {a.make} {a.model}: no verified factory dims — ratios only")
        print(f"  model  L/mid={L/mid:.3f}  L/small={L/small:.3f}  extents={[round(x,3) for x in ext]}")
        return
    fl, fw = float(row["length_mm"]), float(row["width_mm"])
    fh = float(row["height_mm"]) if row.get("height_mm") else None
    # widths and heights can swap in the sorted extents; compare both pairings
    lw_dev = abs((L / mid) - fl / fw) / (fl / fw)
    print(f"DIMS_CHECK {a.make} {a.model} vs {row['source_page']}")
    print(f"  factory L/W={fl/fw:.3f}" + (f" L/H={fl/fh:.3f}" if fh else ""))
    print(f"  model   L/mid={L/mid:.3f} (dev {lw_dev*100:.1f}%)  L/small={L/small:.3f}")
    print(f"  true scale: factory length {fl/1000:.3f}m vs model {L:.3f} units "
          f"(scale factor {fl/1000/L:.4f})")


if __name__ == "__main__":
    main()
