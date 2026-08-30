#!/usr/bin/env python3
"""verify_car.py — measure the pipeline's OWN OUTPUT with the library ruler.

The close of the owner's 2026-08-30 order ("measure them all as reference…
no more guessing"): the finished car goes through libmeasure.py — the SAME
instrument that measured the 1,044-car library — and every number is held
against the spec (published + library-measured cabin) and the population
priors. Until this stage existed, the chain's gates each checked their own
stage and NOTHING asked at the end whether the car, as a whole, measures
like a car: a Golf with all gates green shipped 150 mm in the air, and an
A-Class shipped with its dashboard on the bonnet.

Verdicts per row:
    PASS   inside the tolerance / population band
    CHECK  outside it — a candidate for the eye, never an auto-scrap
    n/a    the measure could not be made (never silently invented)

This stage REPORTS; it does not block the render. Every automated audit in
this project is a candidate finder — the render plus the owner's eye is
the verdict (standing rule). Exit code 0 always; the count of CHECKs is in
VERDICT.json for the driver to print loudly.

Run: python3 verify_car.py <CAR_FINAL.glb> --spec specs/car.json
                           [--priors reference/LIBRARY_PRIORS.json]
                           [--out verdict.json]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from carspec import CarSpec
from libmeasure import measure, maybe_decompress

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PRIORS = os.path.join(HERE, "reference", "LIBRARY_PRIORS.json")


def main():
    car = sys.argv[1]
    spec_p = priors_p = out_p = None
    for i, a in enumerate(sys.argv):
        if a == "--spec":
            spec_p = sys.argv[i + 1]
        if a == "--priors":
            priors_p = sys.argv[i + 1]
        if a == "--out":
            out_p = sys.argv[i + 1]
    spec = CarSpec.load(spec_p) if spec_p else CarSpec.empty()
    priors = {}
    pp = priors_p or DEFAULT_PRIORS
    if os.path.exists(pp):
        priors = json.load(open(pp))

    p2 = maybe_decompress(car)
    m = measure(p2 or car, os.path.basename(car))
    rows = []

    def row(name, value, ref, verdict, source):
        rows.append({"measure": name, "value": value, "ref": ref,
                     "verdict": verdict, "source": source})

    if not m.get("ok"):
        row("measurable", False, True, "CHECK",
            m.get("error", "measure failed"))
    else:
        # ---- published dimensions (the spec is the law here) -------------
        for key, mkey in (("length_m", "L"),):
            tgt, src = spec.dim(key)
            if tgt and m.get(mkey):
                d = abs(m[mkey] - tgt) / tgt
                row(key, round(m[mkey], 3), tgt,
                    "PASS" if d < 0.015 else "CHECK", src)
        for key, mkey in (("width_m", "W_over_L"), ("height_m", "H_over_L")):
            tgt, src = spec.dim(key)
            Lt, _ = spec.dim("length_m")
            if tgt and Lt and m.get(mkey) is not None:
                got = m[mkey] * m["L"]
                d = abs(got - tgt) / tgt
                row(key, round(got, 3), tgt,
                    "PASS" if d < 0.015 else "CHECK", src)
        # ---- library-measured cabin landmarks ----------------------------
        cab = spec.data.get("cabin", {})
        for key, tol in (("scuttle_frac_from_nose", 0.05),
                         ("beltline_frac", 0.06), ("rail_frac", 0.05),
                         ("backlight_frac_from_nose", 0.05)):
            if key in cab and m.get(key) is not None:
                d = abs(m[key] - float(cab[key]))
                row(key, m[key], cab[key],
                    "PASS" if d <= tol else "CHECK", "library reference")
            elif key in cab:
                row(key, None, cab[key], "n/a",
                    "library reference (car unmeasurable: " +
                    str(m.get(key.replace("_frac_from_nose", "_rejected"),
                              "no glazing sample")) + ")")
        # roof profile against the library car, rear stations — where the
        # generated A-Class was suspected of losing its rear greenhouse
        prof_ref = cab.get("roof_profile_frac_from_nose", {})
        prof_got = m.get("roof_profile", {})
        worst = None
        for st, refv in prof_ref.items():
            gv = prof_got.get(f"{float(st):.2f}")
            if gv is not None:
                d = abs(gv - float(refv))
                if worst is None or d > worst[1]:
                    worst = (st, round(d, 3), gv, refv)
        if worst:
            row("roof_profile_max_dev", worst[1],
                f"station {worst[0]}: {worst[2]} vs {worst[3]}",
                "PASS" if worst[1] <= 0.06 else "CHECK", "library reference")
        # ---- population priors -------------------------------------------
        for key in ("W_over_L", "H_over_L", "axle_front_frac",
                    "axle_rear_frac", "glass_area_over_L2"):
            pr = priors.get(key)
            if pr and m.get(key) is not None:
                v = m[key]
                ok = pr["p10"] * 0.9 <= v <= pr["p90"] * 1.1
                row(key + "_vs_population", round(v, 3),
                    f"p10-p90 {pr['p10']}-{pr['p90']} (n={pr['n']})",
                    "PASS" if ok else "CHECK", "library population")

    checks = sum(1 for r in rows if r["verdict"] == "CHECK")
    print(f"\nVERIFY {os.path.basename(car)} — {len(rows)} measures, "
          f"{checks} CHECK")
    for r in rows:
        print(f"  {r['verdict']:5s} {r['measure']:28s} "
              f"{str(r['value']):>10s}  vs {str(r['ref']):28s} [{r['source']}]")
    if out_p:
        json.dump({"rows": rows, "checks": checks}, open(out_p, "w"),
                  indent=1)
    if p2 and p2 != car and os.path.exists(p2):
        os.remove(p2)


if __name__ == "__main__":
    main()
