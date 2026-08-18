#!/usr/bin/env python3
"""carspec.py — per-car specification files for the machine.

The machine is CAR-AGNOSTIC SOFTWARE. Everything that describes a
particular vehicle — published dimensions, tyre fitment, node-label
conventions of its source mesh — lives in a JSON spec file, never in
stage code. Stage code reads the spec; anything the spec does not
provide is MEASURED from the geometry and tagged "approximate" in the
stage's QC output (rule: approximate data is never presented as
verified OEM data).

Spec format (all dimension values are {"value": <num>, "source": <str>}
so every number carries provenance; omit a key entirely when unknown):

{
  "identity":  {"make": "...", "model": "...", "note": "..."},
  "dimensions": {"wheelbase_m": {...}, "track_front_m": {...},
                 "track_rear_m": {...}, "length_m": {...},
                 "width_m": {...}, "height_m": {...}},
  "tyre":      {"spec": "225/45R17", "source": "..."},
  "labels":    {"body": "carpaint",
                "wheel_strip_prefixes": [...], "liner_name": "ARCH_LINER"},
  "expect":    {"axle_x": {"front": ..., "rear": ...},   # detector self-test
                "tolerance_m": 0.06}
}

Use: spec = CarSpec.load("specs/vw_golf_mk8.json")
     spec.dim("track_front_m")        -> (value, source) or (None, None)
     spec.tyre()                      -> dict of tyre dims + provenance
"""
import json
import os
import re


class CarSpec:
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
        """Parse a tyre spec string like '225/45R17' into metric dims."""
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


if __name__ == "__main__":
    import sys
    sp = CarSpec.load(sys.argv[1])
    print(json.dumps(sp.identity(), indent=1))
    print("tyre:", sp.tyre())
    for k in ("wheelbase_m", "track_front_m", "track_rear_m"):
        print(k, sp.dim(k))
