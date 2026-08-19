"""Offline guards for the house-verification cross-check.

No network: distance maths and the verdict thresholds are pure and tested
here. The live legs (Street View, Solar, postcodes.io, web) are exercised by
running verify.cross_check with a real key.

Run: python building/test_verify.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import verify as V   # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


# --- 1. distance maths ------------------------------------------------------
# One degree of latitude is ~111.32km; a small step should read in metres.
d = V._metres((52.49, -1.996), (52.49 + 1 / 111320.0, -1.996))
check("1a one metre north reads as ~1m", abs(d - 1.0) < 0.01, f"{d:.3f}")
check("1b the same point is zero apart",
      V._metres((52.49, -1.996), (52.49, -1.996)) == 0.0)


# --- 2. the verdict, on the real Basons numbers -----------------------------
# The building-level sources (street view, gps, solar) fell within ~3m; the
# postcode centroid sat ~30m off on the corner plot. Judging on all four gave
# 36m -> UNCONFIRMED on a house we KNOW is right. Judging on the building
# sources gives CONFIRMED, and the postcode is just a note.
basons = {
    "street_view": (52.49076911, -1.99640539),
    "gps": (52.490637625, -1.996275446),
    "solar_building": (52.4906346, -1.9962391),
    "postcode": (52.490855, -1.996637),
}
verdict, spread, msg = V.agreement(basons)
check("2a a correct corner house is CONFIRMED once the postcode is set aside",
      verdict == "CONFIRMED", f"{verdict} at {spread:.1f}m")
check("2b and the judged spread is the tight building-level one, not 36m",
      spread < V.CONFIRM_M, f"{spread:.1f}m")

# With the postcode INCLUDED in a raw all-points judge it would have failed —
# prove the old behaviour would have, so the fix is not vacuous.
raw = [basons[k] for k in basons]
raw_spread = max(V._metres(raw[i], raw[j])
                 for i in range(len(raw)) for j in range(i + 1, len(raw)))
check("2c the raw all-points spread really was past the threshold",
      raw_spread > V.CONFIRM_M, f"{raw_spread:.1f}m")


# --- 3. the thresholds behave at the boundaries -----------------------------
o = (52.49, -1.996)


def offset(m, bearing_deg=90):
    b = math.radians(bearing_deg)
    return (o[0] + (m * math.cos(b)) / 111320.0,
            o[1] + (m * math.sin(b)) / (111320.0 * math.cos(math.radians(o[0]))))


check("3a two building sources 10m apart -> CONFIRMED",
      V.agreement({"gps": o, "solar_building": offset(10)})[0] == "CONFIRMED")
check("3b 45m apart -> UNCONFIRMED (maybe the neighbour)",
      V.agreement({"gps": o, "solar_building": offset(45)})[0] == "UNCONFIRMED")
check("3c 90m apart -> CONFLICT (different buildings)",
      V.agreement({"gps": o, "street_view": offset(90)})[0] == "CONFLICT")
check("3d one source alone -> UNCONFIRMED, never CONFIRMED",
      V.agreement({"gps": o})[0] == "UNCONFIRMED")
check("3e no source -> UNLOCATABLE",
      V.agreement({})[0] == "UNLOCATABLE")


# --- 4. postcode-only (no building source) still gets judged, not dropped ---
# When ONLY weak sources exist, fall back to judging them rather than
# returning nothing — a coarse answer with a caveat beats silence. But the
# postcode centroid is a street point, not a building, so agreement in the
# fallback set is capped at UNCONFIRMED: a false CONFIRMED here once claimed
# "2 independent building-level sources agree" off a road geocode and the
# postcode centre, which cannot name a house.
pv = V.agreement({"postcode": o, "street_view_road": offset(5)})
check("4a with no building-level pair it judges what it has, capped",
      pv[0] == "UNCONFIRMED", f"{pv[0]}: {pv[2]}")
check("4b and the message says what was judged, not 'building-level'",
      "fewer than two are building-level" in pv[2], pv[2])

# One building-level source plus the postcode is still not a confirmation —
# the module's own rule is that one building-level source alone stays
# UNCONFIRMED, and adding the street-level centroid cannot upgrade that.
sp = V.agreement({"street_view": o, "postcode": offset(10)})
check("4c street_view + postcode within 10m is UNCONFIRMED",
      sp[0] == "UNCONFIRMED", f"{sp[0]}: {sp[2]}")
check("4d and no longer claims building-level agreement",
      "independent building-level sources agree" not in sp[2], sp[2])

# Two genuine building-level sources are unaffected by the cap.
check("4e two building-level sources still CONFIRM",
      V.agreement({"street_view": o,
                   "solar_building": offset(10)})[0] == "CONFIRMED")

# Past the CONFIRM threshold the fallback still degrades honestly.
check("4f a wide fallback spread is still UNCONFIRMED/CONFLICT, never "
      "CONFIRMED",
      V.agreement({"postcode": o,
                   "street_view_road": offset(45)})[0] == "UNCONFIRMED")


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
