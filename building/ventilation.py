"""Part F (2021, England) ventilation design from the measured model.

System 1 — natural ventilation with background ventilators and
intermittent extract fans — because that is what a small new-build or an
extension nearly always uses. The three checks Part F actually makes:

  1. Whole-dwelling ventilation rate: the greater of the bedroom-count
     figure (Table 1.3) and 0.3 l/s per m2 of internal floor area.
  2. Intermittent extract in each wet room (Table 1.1 rates).
  3. Background ventilators (trickle vents): minimum equivalent areas per
     room (Table 1.7 for System 1) with every habitable room served.

Bedrooms are counted the way the rest of this codebase counts them — by
name, "bed*"/"master*" — so the count matches what escape() protects.

Simplifications, stated: Table 1.7 strictly keys ventilator areas to the
dwelling's design air-permeability band; without a test figure the
leakier band's areas are used (8000 mm2 habitable / 4000 mm2 wet), which
is the conservative direction — more ventilator, never less.
"""

# Table 1.3: whole-dwelling ventilation rate by number of bedrooms, l/s.
WHOLE_DWELLING_LS = {1: 19.0, 2: 25.0, 3: 31.0, 4: 37.0, 5: 43.0}
EXTRA_BEDROOM_LS = 6.0          # each bedroom past five
FLOOR_RATE_LS_M2 = 0.3

# Table 1.1: minimum intermittent extract rates, l/s.
EXTRACT_LS = {
    "kitchen": 60.0,            # 30 if the fan sits within 300mm of the hob
    "utility": 30.0,
    "bathroom": 15.0,
    "ensuite": 15.0,
    "wet": 15.0,
    "wc": 6.0,
}

# Background ventilator minimum equivalent areas, mm2 (System 1,
# conservative air-permeability band).
TRICKLE_HABITABLE_MM2 = 8000
TRICKLE_WET_MM2 = 4000

HABITABLE = {"room", "bedroom", "living", "kitchen", "dining", "study",
             "office"}
WET = {"wet", "bathroom", "ensuite", "wc", "utility"}


def _is_bedroom(room):
    return (room.get("name") or "").lower().startswith(("bed", "master"))


def _levels_of(room, storeys):
    base = int(room.get("base_level") or 0)
    n = room.get("storeys")
    top = storeys if n is None else base + int(n)
    return range(base, min(top, storeys))


def design(model):
    """Part F System 1 design: rates, fans and trickle vents per room."""
    storeys = int(model.get("storeys") or 1)
    floor_area = float(model["totals"]["floor_area_m2"])
    bedrooms = sum(1 for r in model["rooms"] if _is_bedroom(r))

    by_beds = (WHOLE_DWELLING_LS[min(max(bedrooms, 1), 5)]
               + EXTRA_BEDROOM_LS * max(0, bedrooms - 5))
    by_floor = FLOOR_RATE_LS_M2 * floor_area
    whole = max(by_beds, by_floor)

    fans, vents, total_trickle = [], [], 0
    for room in model["rooms"]:
        kind = room.get("kind", "room")
        name = room.get("name", "room")
        lname = name.lower()
        for level in _levels_of(room, storeys):
            rate = EXTRACT_LS.get(kind)
            if kind == "wet":
                # the generic wet kind covers WCs and utilities too —
                # name tells them apart, and the rates differ 6/15/30
                if lname.startswith("wc"):
                    rate = EXTRACT_LS["wc"]
                elif lname.startswith("util"):
                    rate = EXTRACT_LS["utility"]
                elif lname.startswith("bath") or lname.startswith("ensuite"):
                    rate = EXTRACT_LS["bathroom"]
            if rate is not None:
                fans.append({"name": name, "level": level,
                             "extract_ls": rate,
                             "x": round(room["x"] + room["width_m"] / 2, 3),
                             "y": round(room["y"] + room["depth_m"] / 2, 3)})
            if kind in HABITABLE or _is_bedroom(room):
                need = TRICKLE_HABITABLE_MM2
            elif kind in WET or kind == "wet":
                need = TRICKLE_WET_MM2
            else:
                continue        # circulation needs no dedicated ventilator
            vents.append({"name": name, "level": level,
                          "equiv_area_mm2": need})
            total_trickle += need

    return {
        "system": "System 1: background ventilators + intermittent extract",
        "bedrooms": bedrooms,
        "whole_dwelling_ls": round(whole, 1),
        "governing": "bedrooms" if by_beds >= by_floor else "floor area",
        "by_bedrooms_ls": round(by_beds, 1),
        "by_floor_area_ls": round(by_floor, 1),
        "extract_fans": fans,
        "background_ventilators": vents,
        "trickle_total_mm2": total_trickle,
        "notes": [
            "Kitchen fan rated 60 l/s; 30 l/s is acceptable only within "
            "300 mm of the hob centreline.",
            "Ventilator areas use the conservative air-permeability band "
            "of Table 1.7 — a tested dwelling may need less.",
            "Trickle vents sit in window heads; every habitable room "
            "listed must get its ventilator in a real frame.",
        ],
    }
