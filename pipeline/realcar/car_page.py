#!/usr/bin/env python3
"""car_page.py: the rest of a car, part by part, as a page: its interior, suspension and steering, brakes and
wheels, wiring and lights, exhaust and fuel tank, round its engine (engine_page.py's, in one piece) and gearbox,
inside a see-through body. Every part comes off and goes back; the parts the owner's catalogue lists for the car
carry their OEM numbers (chassis.py's index, and the engine's from engines.py's).

    python3 pipeline/realcar/car_page.py "golf 2008 1.9 tdi" OUT_DIR [--engine-url URL] [--left-hand-drive]

OUT_DIR gets index.html. The car's measurements are its maker's published ones (KNOWN); the parts are drawn to
fit them, not scanned. Cars not in KNOWN are not drawn yet.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chassis  # noqa: E402
import engine_page  # noqa: E402
import engines  # noqa: E402

# published measurements (metres): body, wheelbase, tracks, overhangs, tyre; the years each generation was sold
KNOWN = {
    ("volkswagen", "golf"): [
        {"generation": "Mk4", "years": (1998, 2006), "length": 4.149, "width": 1.735, "height": 1.444, "wheelbase": 2.511,
         "track_front": 1.513, "track_rear": 1.494, "front_overhang": 0.889, "rear_overhang": 0.749,
         "tyre": "195/65 R15", "tyre_radius": 0.3173, "tyre_width": 0.195, "wheel_offset": 0.038,
         "facts": "The fourth Golf, built from 1997 (sold in North America to 2006): 4,149 mm long, 1,735 mm wide, "
                  "1,444 mm high, on a 2,511 mm wheelbase with tracks of 1,513 mm front and 1,494 mm rear. MacPherson "
                  "struts and lower wishbones at the front on a subframe, a twist-beam axle with coil springs and "
                  "separate shock absorbers at the rear; power-assisted rack-and-pinion steering; vented discs at the "
                  "front and solid discs at the rear (the rear discs your catalogue lists); 195/65 R15 tyres on steel "
                  "wheels; a 5-speed manual gearbox. The battery sits over the gearbox, the fuel tank under the rear "
                  "seat, the exhaust runs down the tunnel to a silencer across the back."},
    ],
}


def generation(make, model, year):
    gens = KNOWN.get((make, model)) or []
    y = int(year) if year else None
    for g in gens:
        if y and g["years"][0] <= y <= g["years"][1]:
            return g
    return None


def config(request, idx=None, engine_url=None, drive_side="right"):
    eng = engine_page.config(request, idx)
    mk, model = engines.norm(eng["make"]), engines.norm(eng["model"])
    gen = generation(mk, model, eng["year"])
    if not gen:
        raise SystemExit(f"car_page: the {eng['make']} {eng['model']} {eng['year']} is not drawn yet "
                         f"(drawn so far: {', '.join(f'{m} {n}' for m, n in KNOWN)})")
    lo, hi = gen["years"]
    rows = chassis.look(mk, model, range(lo, hi + 1), eng["spec"].get("litres"))
    parts = {**eng["parts"], **{f"Car: {s}": v for s, v in rows.items()}}
    car = {k: v for k, v in gen.items() if k != "years"}
    car.update({"drive_side": drive_side, "engine_name": eng["dims"]["name"]})
    return {**eng, "car": car, "parts": parts, "engine_systems": list(eng["parts"]), "engine_url": engine_url,
            "part_count": sum(len(v) for v in parts.values())}


def write(cfg, out):
    os.makedirs(out, exist_ok=True)
    title = f"{cfg['make']} {cfg['model']} {cfg['car']['generation']}, part by part"
    page = engine_page.assemble(cfg, title, ["build_engine.js", "build_car.js"], "CAR")
    path = os.path.join(out, "index.html")
    with open(path, "w") as fh:
        fh.write(page)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("request"), ap.add_argument("out")
    ap.add_argument("--engine-url", default=None, help="the engine page's address, linked from the engine")
    ap.add_argument("--left-hand-drive", action="store_true")
    a = ap.parse_args()
    cfg = config(a.request, engine_url=a.engine_url, drive_side="left" if a.left_hand_drive else "right")
    path = write(cfg, a.out)
    print(json.dumps({"index": path, "car": f"{cfg['make']} {cfg['model']} {cfg['car']['generation']}", "year": cfg["year"],
                      "engine": cfg["engine"], "parts_listed": cfg["part_count"]}, indent=1))


if __name__ == "__main__":
    main()
