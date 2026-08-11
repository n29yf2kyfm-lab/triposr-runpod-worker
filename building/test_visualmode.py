"""Guards for the orbit-vs-elevation decision.

The wrong mode is a hallucination: orbiting an attached house shows a fake
flank or the neighbour. These lock the rule that geometry outranks text and
that elevation is the safe default.

Run: python building/test_visualmode.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import visualmode as V   # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


OPEN = {"east": 12.0, "west": 12.0, "north": 12.0, "south": 12.0}
PARTY = {"east": 0.0, "west": 12.0, "north": 12.0, "south": 12.0}


# --- 1. Basons: a semi routes to ELEVATION ----------------------------------
r = V.choose_mode(dwelling_type="semi-detached", side_clearances=PARTY)
check("1a a semi with a party wall is elevation", r["mode"] == "elevation")
check("1b at high confidence", r["confidence"] == "high", r["confidence"])
check("1c and the render hint is the front photo, no orbit",
      r["render"]["kind"] == "elevation")


# --- 2. geometry outranks a wrong listing -----------------------------------
# A listing that says "detached" cannot override a measured party wall.
r = V.choose_mode(dwelling_type="detached", side_clearances=PARTY)
check("2a 'detached' + a zero flank is still elevation — geometry wins",
      r["mode"] == "elevation", r["mode"])
check("2b and the reason cites the flank, not the listing",
      "wall" in r["reason"] or "flank" in r["reason"], r["reason"])


# --- 3. a confirmed detached house orbits -----------------------------------
r = V.choose_mode(dwelling_type="detached", side_clearances=OPEN)
check("3a detached + both flanks clear is orbit", r["mode"] == "orbit")
check("3b high confidence", r["confidence"] == "high")
check("3c orbit rides at drone height, off the tile mesh",
      r["render"]["pitch_deg"] == V.ORBIT_PITCH_DEG
      and r["render"]["source"] == "google_tiles_mesh")


# --- 4. a mapped row never orbits -------------------------------------------
r = V.choose_mode(dwelling_type="detached", side_clearances=OPEN, is_row=True)
check("4a a terrace/semi row is elevation even if clearances look open",
      r["mode"] == "elevation", r["mode"])


# --- 5. missing signals default to the SAFE side ----------------------------
check("5a nothing known -> elevation, not orbit",
      V.choose_mode()["mode"] == "elevation")
check("5b low confidence when guessing",
      V.choose_mode()["confidence"] == "low")
# Type unknown but geometry clearly free -> orbit is allowed (medium).
r = V.choose_mode(side_clearances=OPEN)
check("5c open geometry with no type -> orbit at medium confidence",
      r["mode"] == "orbit" and r["confidence"] == "medium", str(r))
# Detached listing but NO geometry to check -> orbit, flagged medium.
r = V.choose_mode(dwelling_type="detached")
check("5d detached listing, no flank data -> orbit but medium",
      r["mode"] == "orbit" and r["confidence"] == "medium", str(r))


# --- 6. one open + one blocked flank is attached ----------------------------
half = {"east": 0.3, "west": 12.0}
check("6a a single party wall is enough to force elevation",
      V.choose_mode(dwelling_type="detached",
                    side_clearances=half)["mode"] == "elevation")


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
