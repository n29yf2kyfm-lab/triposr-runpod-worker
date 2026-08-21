#!/usr/bin/env python3
"""test_compress_regex.py -- two-directional validation of compress_catalogue's
material-class regexes against a REAL corpus of catalogue material names.

WHY THIS EXISTS
---------------
`compress_catalogue.TYRE_MAT` was written with word-boundary lookarounds
(`(?<![a-z0-9])tire(?![a-z0-9])`). Measured 2026-08-21 against 60 random live
catalogue cars, that regex MISSED a tyre material in **10 of them** -- and the
dominant miss is the plain English PLURAL, because the trailing `(?![a-z0-9])`
refuses the `s`:

    Tires · tires · Pneus · M_2022_Mercedes_AMG_GLS63_Tires
    M_2021_Ford_Mondeo_Hybrid_Tires · M_2020_Kia_Niro_Hybrid_Tires
    M_2022_Audi_Q4_e_tron_Tires · XJ220MI_Thick_Tire1 · tirea0
    advantyre.001 · rubberSmooth.003 · Meshestire0021Mtl (the controls car)

G2 reports `no tyre-NAMED material in this car -- G2 has nothing to check` in
that case, which reads like a fact about the car and was a fact about the regex.
That is the "gate empty by construction" class this project has now paid for
four separate times.

`glass_probe.GLASSY` does NOT have this problem because it is a plain substring
match, which is why glazing area was measured on the same cars that had no tyre
area measured. The two classes were simply inconsistent.

THE FIX, and its two-sided obligation
-------------------------------------
Relaxing a regex is the direction that manufactures FALSE POSITIVES, so it is
only allowed with a corpus test that checks BOTH directions. This file is that
test. It runs against 3,082 distinct material names harvested from 191 random
live catalogue cars, plus the hand-written trap list below -- every name this
project has recorded as a documented misclassification:

  * `M_0132_LightGray` -- the 2026 Clio's BODY material. A naive /light/ ate it
    and the probe reported "no confident body material" on a car whose body was
    right there.
  * `backlight_glass` / `lights_glass` -- glazing, not lamps.
  * `Airconditioningbuttonwindscreenventilationicons1Mtl` -- a dashboard icon
    sheet, not a windscreen.
  * `retired` / `entire` / `attire` / `satire` / `tired` -- English words
    containing `tire`, the reason the lookarounds were there in the first place.

Run:  python3 pipeline/machine/test_compress_regex.py
Exit 0 = every assertion holds. Non-zero = do not ship the regex change.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "mobile"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)),
                                "pipeline", "ingest"))

import compress_catalogue as CC          # noqa: E402

CORPUS = os.environ.get("MATNAME_CORPUS",
                        "/tmp/compress_out/corpus/matnames.json")

# ---- names each class MUST catch -----------------------------------------
MUST_TYRE = [
    "tire", "tires", "Tires", "Tyre", "tyres", "TYRE",
    "Meshestire0021Mtl", "Meshestire0031Mtl",          # the controls Porsche
    "M_2022_Mercedes_AMG_GLS63_Tires", "M_2021_Ford_Mondeo_Hybrid_Tires",
    "M_2020_Kia_Niro_Hybrid_Tires", "M_2022_Audi_Q4_e_tron_Tires",
    "XJ220MI_Thick_Tire1", "tirea0", "advantyre.001", "rubberSmooth.003",
    "Pneus", "pneu", "Reifen", "tire.001", "EXT_Rubber", "rubber",
    "Tyre_Rubber", "tire_mat3", "neumatico",
]
MUST_NOT_TYRE = [
    # English words containing the stem -- the reason the lookarounds existed
    "retired", "entire", "Entire_Body", "attire", "satire", "tired",
    "RetiredPanel", "entirely", "tiredLook",
    # and things that are simply other parts
    "carpaint", "Glass_Windscreen", "Rim_Alloy", "chrome", "interior",
    "M_0132_LightGray", "steel", "Caliper1Mtl", "brake_disc",
]

MUST_LAMP = [
    "Lamp_Lens", "headlight", "Headlamp", "taillight", "tail_lamp",
    "Meshes911gt3light10011Mtl", "lens", "phare", "Scheinwerfer",
    "rear_lights", "TailLights", "lamps",
]
MUST_NOT_LAMP = [
    # the documented Clio trap: `light` followed by a COLOUR word is a body name
    "M_0132_LightGray", "LightGrey", "light_blue", "LightSilver",
    "Light_Green", "lightbeige", "LightBrown", "light red",
    "carpaint", "tire", "Glass_Windscreen", "chrome",
]

MUST_RIM = [
    "Rim_Alloy", "rim", "rims", "alloy", "wheel", "Wheels",
    "Meshes911gt3wheels0031Mtl", "jante", "Felge", "rines", "llanta",
    "brake_disc", "Caliper1Mtl", "Disc1Mtl", "Meshescaliper0021Mtl",
]
MUST_NOT_RIM = [
    "carpaint", "tire", "Tyre_Rubber", "Glass_Windscreen",
    "M_0132_LightGray", "interior", "chrome_trim",
    # `rims?` with no left boundary matched every one of these
    "trim", "Trim_Black", "primer", "Primer_Grey",
    # `disc` with no guard books every Land Rover Discovery material as a
    # brake disc, which is a FALSE LEAK on a gated class
    "Discovery_Body", "discovery_paint",
    # `wheel` inside a STEERING wheel is interior, not an exterior rim -- kept
    # as a KNOWN, ACCEPTED false positive and asserted so nobody "discovers" it
    # later and thinks it is new. It is safe: RIM only gates the G3 leak test
    # and a steering wheel is behind glazing, which G3 excludes from sampling.
]
KNOWN_RIM_FALSE_POSITIVES = ["steering_wheel", "SteeringWheel"]


def check(name, rx, must, must_not):
    bad = []
    for n in must:
        if not rx.search(n):
            bad.append("MISS  %-42s %s should match" % (repr(n), name))
    for n in must_not:
        if rx.search(n):
            bad.append("FALSE %-42s %s must NOT match" % (repr(n), name))
    return bad


def main():
    fails = []
    fails += check("TYRE_MAT", CC.TYRE_MAT, MUST_TYRE, MUST_NOT_TYRE)
    fails += check("LAMP_MAT", CC.LAMP_MAT, MUST_LAMP, MUST_NOT_LAMP)
    fails += check("RIM_MAT", CC.RIM_MAT, MUST_RIM, MUST_NOT_RIM)

    for n in KNOWN_RIM_FALSE_POSITIVES:
        if not CC.RIM_MAT.search(n):
            fails.append("STALE %-42s documented as a KNOWN RIM false positive "
                         "but no longer matches -- update the note" % repr(n))

    print("hand-written traps: %d assertions, %d failures"
          % (len(MUST_TYRE) + len(MUST_NOT_TYRE) + len(MUST_LAMP)
             + len(MUST_NOT_LAMP) + len(MUST_RIM) + len(MUST_NOT_RIM),
             len(fails)))

    # ---- corpus: report movement, and forbid overlap that cannot be right --
    if os.path.exists(CORPUS):
        corp = json.load(open(CORPUS))
        names = sorted({n for v in corp.values() for n in v})
        print("corpus: %d cars, %d distinct material names" % (len(corp), len(names)))
        STRICT = re.compile(
            r"(?<![a-z0-9])(tyre|tire|rubber|pneu|neumatico|reifen)(?![a-z0-9])", re.I)
        gained = [n for n in names if CC.TYRE_MAT.search(n) and not STRICT.search(n)]
        lost = [n for n in names if STRICT.search(n) and not CC.TYRE_MAT.search(n)]
        cars_strict = sum(1 for v in corp.values() if any(STRICT.search(n) for n in v))
        cars_new = sum(1 for v in corp.values()
                       if any(CC.TYRE_MAT.search(n) for n in v))
        print("TYRE: cars with a tyre material  strict %d -> new %d  (of %d)"
              % (cars_strict, cars_new, len(corp)))
        print("TYRE: names GAINED %d, names LOST %d" % (len(gained), len(lost)))
        for n in gained[:25]:
            print("   +", repr(n))
        for n in lost:
            fails.append("REGRESSION: %r matched the strict regex and no longer "
                         "matches -- a relaxation must never lose a name" % n)

        # A material must not be BOTH glazing and tyre: those two classes decide
        # opposite things (glazing is exempt from the G3 leak test, tyre is
        # gated by it), so an overlap silently disarms the leak test.
        both = [n for n in names if CC.GLASSY.search(n) and CC.TYRE_MAT.search(n)]
        if both:
            fails.append("OVERLAP glazing AND tyre (%d): %s"
                         % (len(both), both[:8]))
        # paint-hint vs tyre: BODYISH deliberately contains `tire`/`tyre`
        # (glass_probe uses it to spot the flat shell), so this overlap is
        # EXPECTED and is not asserted -- classify_materials checks paint by
        # exact recorded NAME, never by BODYISH, so it cannot bite here.
    else:
        print("corpus %s absent -- hand traps only (run the harvester first)"
              % CORPUS)

    if fails:
        print("\n%d FAILURES" % len(fails))
        for f in fails:
            print("  " + f)
        return 1
    print("\nALL ASSERTIONS HOLD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
