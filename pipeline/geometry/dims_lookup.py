"""dims_lookup.py — shared access to platform/geometry/vehicle_dims.csv.

Factory exterior dimensions (mm) per make+model, Wikipedia-sourced with a
citable source_page per row (see fetch_dims.py). Keys are normalised
(lowercase, spaces/hyphens stripped) to match the catalogue's loose naming.
"""
import csv
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CSV = os.path.join(REPO, "platform", "geometry", "vehicle_dims.csv")


def nkey(s):
    return (s or "").strip().lower().replace(" ", "").replace("-", "")


def load(path=None):
    table = {}
    with open(path or DEFAULT_CSV) as f:
        for r in csv.DictReader(f):
            k = (nkey(r["make"]), nkey(r["model"]))
            if k not in table or (r.get("length_mm") and not table[k].get("length_mm")):
                table[k] = r
    return table


def lookup(make, model, table=None):
    """Return the dims row for make+model, or None. Values are strings; blank
    means 'not verified' — never substitute a guess."""
    return (table if table is not None else load()).get((nkey(make), nkey(model)))


def ref_lw(make, model, table=None):
    """Factory length/width ratio for the G1 proportion gate, or None."""
    r = lookup(make, model, table)
    if r and r.get("length_mm") and r.get("width_mm"):
        return float(r["length_mm"]) / float(r["width_mm"])
    return None
