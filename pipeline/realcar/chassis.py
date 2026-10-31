#!/usr/bin/env python3
"""chassis.py: the rest of each car's parts in the owner's catalogue (brakes, suspension and steering,
driveshafts and wheels, the fuel tank, electrics, cooling, exhaust, interior), as engines.py keeps its engines.

    python3 pipeline/realcar/chassis.py build CATALOGUE [CATALOGUE ...]   # -> $GLBMACHINE_HOME/chassis.json
    python3 pipeline/realcar/chassis.py look MAKE MODEL YEAR [ENGINE]     # a car's parts, by system

The index (chassis.json, in the machine's home, not in git: the catalogue is the owner's) keeps, for each make
and model, each part's name, OEM number, the catalogue's category, the engines it is listed for and the years.
A name that says nothing by itself ("Cap", "Seal") carries its category: "Cap (fuel system)".
"""
import collections
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engines  # noqa: E402

INDEX = os.path.join(engines.HOME, "chassis.json")

# a part's system, by words in its name (checked in this order); a part in none is the engine's (engines.py)
SYSTEMS = [
    ("Brakes", r"brake|rotor|caliper|\bpads?\b"),
    ("Suspension and steering", r"control arm|bushing|strut|shock absorber|coil spring|stabili[sz]er|sway bar|tie rod|"
                                r"ball joint|axle beam|steering|knuckle|wheel bearing|wheel hub"),
    ("Driveshafts and wheels", r"axle assembly|drive ?shaft|cv joint|cv boot|\bwheel\b|\btires?\b|lug (nut|bolt)|wheel bolt"),
    ("Fuel tank", r"fuel tank|fuel pump and sender|pump tank seal|fuel cap|filler neck|gravity valve|fuel filter|\(fuel"),
    ("Electrical", r"ignition switch|ignition lock|column lock|relay|starter|switch|wiper|headl|lamp|light|horn|battery|"
                   r"\bfuse|wiring"),
    ("Cooling and air conditioning", r"radiator|condenser|\ba/c\b|coolant"),
    ("Exhaust", r"exhaust pipe|muffler|silencer|catalytic|resonator|tail ?pipe|exhaust hanger|exhaust clamp|exhaust gasket"),
    ("Interior", r"\bseats?\b|dashboard|console|carpet|door panel|sun visor|seat belt|shift knob|gear shift|"
                 r"handbrake|parking brake lever"),
]
SYSTEMS = [(s, re.compile(p, re.I)) for s, p in SYSTEMS]
ENGINE_PART = re.compile(r"\bpiston|wrist pin|connecting rod|camshaft|crankshaft", re.I)   # the engine's, by any name
GENERIC = re.compile(r"^(cap|seal|gasket|bolt|nut|screw|clip|washer|bracket|cover|hose|o-?ring)$", re.I)


def named(name, category):
    """A part's name, with its category when the name alone says nothing."""
    if GENERIC.match(name.strip()) and category:
        return f"{name.strip()} ({category.replace('-', ' ')})"
    return name.strip()


def system_of(name):
    if ENGINE_PART.search(name):
        return None
    return next((s for s, pat in SYSTEMS if pat.search(name)), None)


def build(sources, out=INDEX):
    t0 = time.time()
    parts = collections.defaultdict(dict)        # make|model -> (name, oem) -> {system, category, engines, years}
    n = 0
    for src in sources:
        for r in engines.rows(src):
            n += 1
            make, model = engines.norm(r["make"]), engines.norm(r["model"])
            if not make or not model:
                continue
            nm = named(r["name"], r.get("category", ""))
            s = system_of(nm)
            if not s:
                continue
            p = parts[f"{make}|{model}"].setdefault((nm, r["oem"]), {"system": s, "category": r.get("category", ""),
                                                                     "engines": set(), "years": set()})
            p["engines"].update(e.strip() for e in r["engine"].split(";") if e.strip())
            if r["year"].isdigit():
                p["years"].add(int(r["year"]))
            if n % 200000 == 0:
                print(f"  {n} rows ({time.time() - t0:.0f} s)", flush=True)
    kept = {k: [[nm, oem, v["system"], v["category"], sorted(v["engines"]), sorted(v["years"])] for (nm, oem), v in ps.items()]
            for k, ps in parts.items()}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out + ".part", "w") as fh:
        json.dump({"built": time.strftime("%Y-%m-%d %H:%M"), "rows": n, "parts": kept}, fh, separators=(",", ":"))
    os.replace(out + ".part", out)
    return {"rows": n, "models": len(kept), "parts": sum(len(v) for v in kept.values()), "written": out,
            "seconds": round(time.time() - t0)}


_IDX = None


def index(path=INDEX):
    global _IDX
    if _IDX is None or _IDX[0] != path:
        _IDX = (path, json.load(open(path)) if os.path.exists(path) else {"parts": {}})
    return _IDX[1]


def look(make, model, years, litres=None, idx=None):
    """MAKE MODEL's parts listed for any of YEARS (a range) and, when LITRES is given, for an engine of that size
    or for every engine: by system, each [name, OEM number(s), how many of the years it is listed for]."""
    idx = idx or index()
    rows = idx["parts"].get(f"{engines.norm(make)}|{engines.norm(model)}", [])
    out = collections.defaultdict(dict)
    want = set(years)
    for nm, oem, s, _cat, engs, ys in rows:
        hit = want & set(ys)
        if not hit:
            continue
        if litres and engs and not any(f"{litres:.1f}L" in e for e in engs):
            continue
        cur = out[s].setdefault(nm, [nm, set(), 0])
        cur[1].update(o.strip() for o in oem.split(",") if o.strip())
        cur[2] = max(cur[2], len(hit))
    return {s: [[nm, ", ".join(sorted(oems)), n] for nm, oems, n in sorted(v.values(), key=lambda x: (-x[2], x[0]))]
            for s, v in out.items()}


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "build":
        print(json.dumps(build(sys.argv[2:]), indent=1))
    elif len(sys.argv) >= 5 and sys.argv[1] == "look":
        y = int(sys.argv[4])
        print(json.dumps(look(sys.argv[2], sys.argv[3], range(y, y + 1), float(sys.argv[5]) if len(sys.argv) > 5 else None), indent=1))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
