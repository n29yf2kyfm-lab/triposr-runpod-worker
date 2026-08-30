#!/usr/bin/env python3
"""libpriors.py — aggregate the library sweep into LIBRARY_PRIORS.json.

The other half of the owner's 2026-08-30 order: libmeasure.py rows in,
population statistics out. Every field carries N, median, p10 and p90 —
a gate that reads these knows how many cars stand behind the number, which
is the difference between a reference and a guess (standing rule: a
threshold with no positive control behind it is a guess; these have a
thousand).

Direction-dependent fields (scuttle, backlight, axles, roof profile) only
accept rows whose nose call had a real margin: the nose is decided by
which extreme end is LOWER, and a row at margin 0.02 H is a coin flip that
would smear front onto back. Direction-free fields (proportions, beltline,
glass area) take every ok row.

Run: python3 libpriors.py <results.jsonl> <out.json>
"""
import json
import sys

import numpy as np

NOSE_MARGIN_MIN = 0.04

SCALAR_ANY = ["W_over_L", "H_over_L", "beltline_frac", "rail_frac",
              "glass_area_over_L2", "tyre_radius_over_H"]
SCALAR_NOSE = ["scuttle_frac_from_nose", "ws_base_frac_H",
               "backlight_frac_from_nose", "axle_front_frac",
               "axle_rear_frac"]


def stats(vals):
    v = np.array([x for x in vals if x is not None], float)
    if len(v) < 10:
        return None
    return {"n": int(len(v)),
            "median": round(float(np.median(v)), 4),
            "p10": round(float(np.percentile(v, 10)), 4),
            "p90": round(float(np.percentile(v, 90)), 4)}


def main(res_path, out_path):
    rows = []
    for line in open(res_path):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("ok"):
            rows.append(r)
    nose_ok = [r for r in rows
               if (r.get("nose_margin_H") or 0) >= NOSE_MARGIN_MIN]
    out = {"_provenance": {
        "built_from": res_path,
        "rows_ok": len(rows),
        "rows_nose_confident": len(nose_ok),
        "nose_margin_min_H": NOSE_MARGIN_MIN,
        "note": "population statistics over the approved catalogue, "
                "measured by libmeasure.py; every field carries its own N — "
                "a field with small N is weak evidence and gates should "
                "treat it so"}}
    for f in SCALAR_ANY:
        s = stats([r.get(f) for r in rows])
        if s:
            out[f] = s
    for f in SCALAR_NOSE:
        s = stats([r.get(f) for r in nose_ok])
        if s:
            out[f] = s
    # roof profile per station, nose-confident rows only
    prof = {}
    for k in range(20):
        key = f"{k/20:.2f}"
        s = stats([(r.get("roof_profile") or {}).get(key) for r in nose_ok])
        if s:
            prof[key] = s
    out["roof_profile"] = prof
    # pillar width: every DLO gap between 1% and 8% of L across all cars
    widths = []
    for r in nose_ok:
        for pos, w in (r.get("pillar_gaps_frac") or []):
            widths.append(w)
    s = stats(widths)
    if s:
        s["note"] = ("width of a side-glazing gap as a fraction of L; "
                     "the population mixes B-pillars, C-pillars and "
                     "label holes — use as a band, not an identity")
        out["pillar_gap_width_frac"] = s
    json.dump(out, open(out_path, "w"), indent=1)
    print(f"wrote {out_path}: {len(rows)} ok rows, "
          f"{len(nose_ok)} nose-confident, {len(out)-1} fields")
    for k, v in out.items():
        if isinstance(v, dict) and "median" in v:
            print(f"  {k:28s} n={v['n']:4d}  {v['p10']:.3f} / "
                  f"{v['median']:.3f} / {v['p90']:.3f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
