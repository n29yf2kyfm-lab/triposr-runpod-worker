"""Tests for the chassis index (chassis.py) and the car page (car_page.py)."""
import csv
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import car_page  # noqa: E402
import chassis  # noqa: E402
import engines  # noqa: E402

COLS = ["Brand", "Model", "Trim / Body", "Engine", "Year", "Category", "Part Name", "OEM Number", "Description"]


def catalogue(tmp_path, rows):
    p = tmp_path / "master.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        for r in rows:
            w.writerow([r.get("make", "Volkswagen"), r.get("model", "Golf"), "", r["engine"], r["year"], r.get("category", ""),
                        r["name"], r.get("oem", ""), ""])
    eng, ch = tmp_path / "engines.json", tmp_path / "chassis.json"
    engines.build([str(p)], out=str(eng))
    chassis.build([str(p)], out=str(ch))
    return json.load(open(eng)), json.load(open(ch))


def test_a_part_with_a_name_that_says_nothing_carries_its_category_and_engine_parts_stay_out():
    assert chassis.named("Cap", "fuel-system") == "Cap (fuel system)"
    assert chassis.named("Wiper Arm", "wiper-blades") == "Wiper Arm"
    assert chassis.system_of("Cap (fuel system)") == "Fuel tank"
    assert chassis.system_of("Disc Brake Rotor Rear") == "Brakes"
    assert chassis.system_of("Lower Control Arm Rear Bushing") == "Suspension and steering"
    assert chassis.system_of("Engine Piston Wrist Pin Bushing") is None       # a bushing, but the engine's
    assert chassis.system_of("Timing Belt") is None


def test_the_car_page_is_the_car_asked_for_with_its_catalogue_parts(tmp_path):
    rows = [{"engine": "1.9L L4 - Diesel", "year": 2006, "name": "Timing Belt", "oem": "038-109-119-P", "category": "belts"},
            {"engine": "1.9L L4 - Diesel", "year": 2004, "name": "Disc Brake Caliper", "oem": "1J0-615-424-H", "category": "brakes"},
            {"engine": "1.8L L4 - Gas; 1.9L L4 - Diesel", "year": 2001, "name": "Fuel Tank Strap", "oem": "1J0-201-653-J", "category": "fuel-system"},
            {"engine": "2.8L V6 - Gas", "year": 2001, "name": "Ignition Coil", "oem": "022-905-715-C", "category": "ignition"},
            {"engine": "1.9L L4 - Diesel", "year": 1990, "name": "Wiper Motor", "oem": "OLD", "category": "wiper-blades"}]
    eidx, cidx = catalogue(tmp_path, rows)
    chassis._IDX = (chassis.INDEX, cidx)
    try:
        cfg = car_page.config("golf 2008 1.9 tdi", eidx, engine_url="https://example.invalid/engine")
    finally:
        chassis._IDX = None
    assert cfg["car"]["generation"] == "Mk4" and cfg["car"]["wheelbase"] == 2.511 and cfg["car"]["drive_side"] == "right"
    flat = {r[0]: r[1] for v in cfg["parts"].values() for r in v}
    assert flat["Disc Brake Caliper"] == "1J0-615-424-H" and "Fuel Tank Strap" in flat and "Timing Belt" in flat
    assert "Wiper Motor" not in flat           # another generation's year
    assert "Ignition Coil" not in flat         # a petrol V6's
    assert cfg["engine_systems"] and all(not s.startswith("Car: ") for s in cfg["engine_systems"])
    page = open(car_page.write(cfg, str(tmp_path / "out"))).read()
    assert "/*KIT*/" not in page and "/*BUILD*/" not in page and "BUILD = CAR;" in page and "const ENGINE" in page
    assert "<title>Volkswagen Golf Mk4, part by part</title>" in page and "1J0-615-424-H" in page


def test_a_car_not_drawn_yet_says_so(tmp_path):
    eidx, cidx = catalogue(tmp_path, [{"engine": "1.9L L4 - Diesel", "year": 2012, "name": "Timing Belt", "oem": "X"}])
    chassis._IDX = (chassis.INDEX, cidx)
    try:
        with pytest.raises(SystemExit):
            car_page.config("golf 2012 1.9 tdi", eidx)
    finally:
        chassis._IDX = None
