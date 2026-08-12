"""Tests for the plain-English brief parser.

Pure, no network. What matters here is that a sentence a builder actually
says produces the rooms they meant — and that a brief which does not fit is
REFUSED with a number, not shrunk in silence.

Run: python building/test_brief.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import brief as B   # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


# --- 1. the sentence this was built for -------------------------------------
p = B.parse("two beds plus en-suite bathroom on top plus loft")
check("1a two bedrooms are found",
      p["rooms"].count("bedroom") + p["rooms"].count("master") == 2,
      str(p["rooms"]))
# "EN-SUITE BATHROOM" IS ONE ROOM. The bare patterns matched both "en-suite"
# and "bathroom" and designed a separate family bathroom nobody asked for —
# on the commonest phrasing there is.
check("1b an en-suite bathroom is ONE room, not two",
      p["rooms"].count("ensuite") == 1 and "bathroom" not in p["rooms"],
      str(p["rooms"]))
check("1c three rooms total", len(p["rooms"]) == 3, str(p["rooms"]))
check("1d 'on top' means building over an existing block",
      p["placement"] == "over", str(p["placement"]))
check("1e the loft is picked up", p["loft"] is True)
check("1f nothing was silently dropped", p["unrecognised"] == [],
      str(p["unrecognised"]))

# The first of several bedrooms becomes the master — that is how it is built
# and sold, not two identical boxes.
check("1g the first bedroom is promoted to master", "master" in p["rooms"])


# --- 2. an en-suite AND a bathroom is still two rooms ------------------------
p2 = B.parse("two beds with an en-suite and a family bathroom on top")
check("2a both are found when both are asked for",
      p2["rooms"].count("ensuite") == 1 and p2["rooms"].count("bathroom") == 1,
      str(p2["rooms"]))


# --- 3. counts, digits and words --------------------------------------------
check("3a '3 bed' gives three", len(B.parse("3 bed rear extension")["rooms"]) == 3)
check("3b 'four beds' gives four",
      len(B.parse("four beds on top")["rooms"]) == 4)
check("3c a bare 'bedroom' gives one",
      len(B.parse("a bedroom over the garage")["rooms"]) == 1)


# --- 4. placement -----------------------------------------------------------
for text, want in (("kitchen at the back", "rear"),
                   ("side extension with a utility", "side"),
                   ("bedroom over the garage", "over"),
                   ("wrap around kitchen diner", "wrap")):
    check(f"4 '{text}' -> {want}", B.parse(text)["placement"] == want,
          str(B.parse(text)["placement"]))

# No placement said: bedrooms imply upstairs, a kitchen implies the ground.
check("4e beds with no placement default to building over",
      B.to_extension_spec(B.parse("two beds"))["type"] == "over")
check("4f a kitchen with no placement defaults to a rear extension",
      B.to_extension_spec(B.parse("a kitchen"))["type"] == "rear")


# --- 5. sizing inside a MEASURED footprint ----------------------------------
sched, fits, short = B.schedule(["master", "bedroom", "ensuite"], 41.6)
check("5a it fits in the measured 41.6m2", fits and short == 0.0)
total = sum(r["area_m2"] for r in sched)
check("5b the rooms stay inside the usable floor",
      total <= 41.6 * (1 - B.CIRCULATION_FRACTION) + 0.2, f"{total}")
check("5c every room is at or above its minimum",
      all(r["area_m2"] >= B.ROOM_SIZES[r["room"]]["min"] - 0.05
          for r in sched), str(sched))
check("5d the master is the biggest bedroom",
      [r for r in sched if r["room"] == "master"][0]["area_m2"]
      > [r for r in sched if r["room"] == "bedroom"][0]["area_m2"])

# A BRIEF THAT DOES NOT FIT MUST SAY SO, with the number. Quietly shrinking
# four bedrooms into 41m2 produces rooms nobody can use and a take-off that
# lies.
big, fits2, short2 = B.schedule(
    ["master", "bedroom", "bedroom", "bedroom", "bathroom", "bathroom"], 41.6)
check("5e an oversized brief is refused", fits2 is False)
check("5f and the shortfall is reported in m2", short2 > 15.0, str(short2))
check("5g the schedule still comes back at minimums, to show what gives",
      all(r["at_minimum"] for r in big))


# --- 6. unrecognised words surface, never vanish ----------------------------
p6 = B.parse("two beds and a swimming pool on top")
check("6a an unparsed word is reported",
      any("swim" in w or "pool" in w for w in p6["unrecognised"]),
      str(p6["unrecognised"]))
check("6b but the rooms it did understand still come through",
      len(p6["rooms"]) == 2, str(p6["rooms"]))


# --- 7. empty and nonsense --------------------------------------------------
check("7a empty text gives no rooms", B.parse("")["rooms"] == [])
check("7b empty schedule fits trivially", B.schedule([], 40.0)[1] is True)
check("7c describe() says so rather than inventing",
      "Nothing to build" in B.describe(B.parse(""), [], True, 0.0, 40.0))


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
