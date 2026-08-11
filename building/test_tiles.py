"""Offline guards for the Google 3D Tiles path.

No network: these lock the two findings that cost hours — the geoid
correction and the ENU/ECEF geometry — as pure-math assertions. The live
descent is exercised by running `python tiles.py <dir>` against a real key.

Run: python building/test_tiles.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import tiles as T   # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


# --- 1. the geoid correction is applied, and in the right direction ---------
# The whole night's bug: ground_od_m is Ordnance Datum, ECEF wants ellipsoid
# height, and OD sits ~48m BELOW the ellipsoid in the UK. fetch_house must
# ADD the separation, lifting the target OUT of the ground.
lat, lon, od = 52.490637625, -1.996275446, 184.81
p_od = T.ecef(lat, lon, od)                        # wrong: buried 48m
p_ell = T.ecef(lat, lon, od + T.GEOID_SEPARATION_M)  # right: at the surface
r_od = math.sqrt(sum(c * c for c in p_od))
r_ell = math.sqrt(sum(c * c for c in p_ell))
check("1a the ellipsoid point is farther from Earth's centre than the OD point",
      r_ell > r_od, f"{r_ell:.1f} vs {r_od:.1f}")
check("1b by very close to the geoid separation",
      abs((r_ell - r_od) - T.GEOID_SEPARATION_M) < 0.5,
      f"{r_ell - r_od:.2f}m")
check("1c the separation is a sane UK value (45-50m)",
      45.0 <= T.GEOID_SEPARATION_M <= 50.0, str(T.GEOID_SEPARATION_M))


# --- 2. the ENU basis is orthonormal and oriented right ---------------------
east, north, up = T.enu_basis(lat, lon)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


for nm, v in (("east", east), ("north", north), ("up", up)):
    check(f"2 {nm} is unit length", abs(math.sqrt(dot(v, v)) - 1.0) < 1e-9)
check("2d east.north orthogonal", abs(dot(east, north)) < 1e-9)
check("2e east.up orthogonal", abs(dot(east, up)) < 1e-9)
check("2f north.up orthogonal", abs(dot(north, up)) < 1e-9)
# Up must point away from Earth's centre: its dot with the ECEF position is
# positive (roughly the geocentric radius).
pos = T.ecef(lat, lon, 0.0)
check("2g up points outward", dot(up, pos) > 0, str(dot(up, pos)))
# East has no vertical (Z) component anywhere on Earth.
check("2h east is horizontal", abs(east[2]) < 1e-12, str(east[2]))


# --- 3. box containment, the test that gates the whole descent --------------
# A unit box at the origin. Padding lets a point just outside still count —
# that slack is what tolerates the geoid wobble at depth.
box = [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]     # half-extents 1m each axis
check("3a a point inside is contained", T._in_box(box, (0.5, 0.5, 0.5), 1.0))
check("3b a point well outside is rejected",
      not T._in_box(box, (5.0, 0.0, 0.0), 1.0))
check("3c padding admits a point just beyond the face",
      T._in_box(box, (1.2, 0.0, 0.0), 1.3))
check("3d but not one beyond the pad", not T._in_box(box, (1.6, 0, 0), 1.3))
check("3e default pad is the tuned value", abs(T.BOX_PAD - 1.30) < 1e-9)


# --- 4. no key means no crash, just an empty result -------------------------
_saved = {k: os.environ.pop(k, None)
          for k in ("GOOGLE_SOLAR_API_KEY", "GOOGLE_AI_API_KEY")}
try:
    check("4a a missing key returns [], does not raise",
          T.fetch_house(lat, lon, od, "/tmp/nope_tiles") == [])
finally:
    for k, v in _saved.items():
        if v is not None:
            os.environ[k] = v


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
