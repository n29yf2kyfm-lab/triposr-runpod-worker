"""Tests for the first-fix electrical design.

The behaviour pinned hardest here is detection. AD B's minimum is Grade D2
Category LD3 — a smoke alarm in the circulation space of EVERY storey,
because the circulation IS the escape route. Placement used to be keyed on
the room's NAME starting "hall" or "landing", so a corridor by any other
name got no smoke alarm while the output notes went on claiming the LD3
minimum was met. The alarm follows the KIND; and when a storey genuinely
has no circulation to carry one, the notes must say the minimum is NOT met
rather than assert it anyway.

Pure, no network. Run: python building/test_electrics.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import electrics as E   # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


def room(name, x, y, w, d, kind="room", base=0, storeys=1):
    return {"name": name, "kind": kind, "x": x, "y": y,
            "width_m": w, "depth_m": d, "base_level": base,
            "storeys": storeys, "height_m": 2.4,
            "area_m2": round(w * d, 2)}


def model(rooms, storeys=1):
    return {"rooms": rooms, "storeys": storeys, "walls": []}


def smokes(design):
    return [a for a in design["alarms"] if a["type"] == "smoke"]


# --- 1. the alarm follows the kind, not the name ----------------------------
# A circulation space called Corridor is the escape route exactly as much
# as one called Hall. It gets the smoke alarm, at the centre of the room.
d = E.design(model([
    room("Corridor", 0.0, 0.0, 4.0, 1.2, kind="circulation"),
    room("Kitchen", 0.0, 1.2, 4.0, 3.0, kind="kitchen"),
    room("Living", 0.0, 4.2, 4.0, 4.0, kind="living"),
]))
s = smokes(d)
check("1a a circulation room named Corridor gets a smoke alarm",
      len(s) == 1 and s[0]["name"] == "Corridor", str(d["alarms"]))
check("1b centred in the room — 4.0 x 1.2 at the origin puts it at (2, 0.6)",
      s and s[0]["x"] == 2.0 and s[0]["y"] == 0.6, str(s))
check("1c the kitchen still gets its heat alarm",
      any(a["type"] == "heat" and a["name"] == "Kitchen"
          for a in d["alarms"]), str(d["alarms"]))
check("1d with every storey covered, the notes may claim the LD3 minimum",
      any("Grade D2 Category LD3" in n and "exceeds that minimum" in n
          for n in d["notes"]), str(d["notes"]))

# The same plan with the circulation called Hall behaves identically —
# the name never mattered to the fire.
d2 = E.design(model([
    room("Hall", 0.0, 0.0, 4.0, 1.2, kind="circulation"),
    room("Kitchen", 0.0, 1.2, 4.0, 3.0, kind="kitchen"),
    room("Living", 0.0, 4.2, 4.0, 4.0, kind="living"),
]))
check("1e a Hall gets exactly the same smoke alarm",
      len(smokes(d2)) == 1 and smokes(d2)[0]["x"] == 2.0,
      str(d2["alarms"]))


# --- 2. every storey, whatever its circulation is called --------------------
d = E.design(model([
    room("Entrance", 0.0, 0.0, 2.0, 5.0, kind="circulation"),
    room("Living", 2.0, 0.0, 4.0, 5.0, kind="living"),
    room("Stairs", 0.0, 0.0, 2.0, 5.0, kind="circulation", base=1),
    room("Bed 1", 2.0, 0.0, 4.0, 5.0, kind="bedroom", base=1),
], storeys=2))
s = smokes(d)
check("2a a two-storey house gets one smoke alarm per storey",
      sorted(a["level"] for a in s) == [0, 1], str(s))
check("2b on the escape route of each — the Entrance and the Stairs",
      {a["name"] for a in s} == {"Entrance", "Stairs"}, str(s))

# A repeated-plate hall (storeys=None means it stands on every storey)
# carries the alarm on each level it exists on.
d = E.design(model([
    room("Hall", 0.0, 0.0, 2.0, 5.0, kind="circulation", storeys=None),
    room("Living", 2.0, 0.0, 4.0, 5.0, kind="living", storeys=None),
], storeys=2))
check("2c a hall present on both storeys alarms both",
      sorted(a["level"] for a in smokes(d)) == [0, 1], str(smokes(d)))


# --- 3. no circulation means the LD3 claim is withdrawn, not repeated -------
# A studio with no circulation space has nowhere for the loop to put a
# smoke alarm. Stating the AD B minimum over a bare alarm list would be
# the silent mislead; the note has to say it is NOT met as drawn.
d = E.design(model([
    room("Studio", 0.0, 0.0, 5.0, 4.0, kind="room"),
    room("Kitchen", 0.0, 4.0, 5.0, 2.0, kind="kitchen"),
]))
check("3a no circulation, no smoke alarm placed", smokes(d) == [],
      str(d["alarms"]))
check("3b and the notes say the minimum is NOT met, naming the storey",
      any("NOT met" in n and "0" in n for n in d["notes"]), str(d["notes"]))
check("3c the covered-case wording is gone",
      not any("exceeds that minimum" in n for n in d["notes"]),
      str(d["notes"]))


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
