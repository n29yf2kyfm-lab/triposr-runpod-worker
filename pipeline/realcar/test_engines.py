"""engines.py: a car's own engine and parts from a parts catalogue, tested on a small made-up catalogue in the
master file's layout (the owner's catalogue is not in git).

    python3 -m pytest pipeline/realcar/test_engines.py -q
"""
import csv
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engines  # noqa: E402
import page  # noqa: E402

COLS = ["Brand", "Model", "Trim / Body", "Engine", "Year", "Category", "Part Name", "OEM Number", "Description"]


def catalogue(tmp_path, rows):
    p = tmp_path / "master.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        for r in rows:
            w.writerow([r.get("make", "BMW"), r["model"], r.get("trim", ""), r["engine"], r["year"], "Engine",
                        r["name"], r.get("oem", ""), ""])
    out = tmp_path / "engines.json"
    engines.build([str(p)], out=str(out))
    return json.load(open(out))


def names(r, system):
    return [x[0] for x in r["parts"].get(system, [])]


@pytest.mark.parametrize("text, layout, cylinders, fuel", [
    ("2.0L L4 - Gas", "inline", 4, "petrol"),
    ("L84 5.3L Petrol V8", "v", 8, "petrol"),          # L84 is GM's engine code, V8 the layout
    ("3.0L H6 - Gas", "flat", 6, "petrol"),
    ("2.0L L4 - Diesel", "inline", 4, "diesel"),
    ("BATTERY EV (EV/BEV)", "electric", 0, "electric"),
])
def test_an_engines_words_read_as_its_layout(text, layout, cylinders, fuel):
    s = engines.spec(text)
    assert (s["layout"], s["cylinders"], s["fuel"]) == (layout, cylinders, fuel)


def test_a_cc_engine_reads_its_litres():
    assert engines.spec("1368 PT (1.4)")["litres"] == 1.4


@pytest.mark.parametrize("name, system", [
    ("Engine Valve Spring", "Valvetrain"), ("Exhaust Valve", "Valvetrain"), ("Engine Timing Belt", "Timing"),
    ("Bmw M Valve Stem Caps - Black", None), ("Laser Slimline Kit With Bmw M Logo Valve Stem", None),
    ("Brake Pad Set", None),
])
def test_a_parts_system_by_its_name(name, system):
    # a tyre's valve stem caps are not an engine's valves
    assert engines.system_of(name) == system


def test_a_models_parts_are_its_own_not_every_car_with_the_same_engine_words(tmp_path):
    # "3.0L L6 - Gas" is the words on an M3 and an X5: the M3's list once held the X5's parts
    idx = catalogue(tmp_path, [
        {"model": "M3", "engine": "3.0L L6 - Gas", "year": 2023, "name": "Engine Oil Cooler", "oem": "M3-1"},
        {"model": "X5", "engine": "3.0L L6 - Gas", "year": 2023, "name": "Engine Oil Pan", "oem": "X5-1"},
    ])
    r = engines.look("bmw", "m3", 2023, idx=idx)
    assert names(r, "Lubrication") == ["Engine Oil Cooler"]
    assert r["part_count"] == 1


def test_a_part_of_other_years_is_not_listed_for_the_year_asked(tmp_path):
    idx = catalogue(tmp_path, [
        {"model": "M3", "engine": "3.0L L6 - Gas", "year": y, "name": "Engine Oil Pan", "oem": "NEW"} for y in (2021, 2022, 2023)
    ] + [{"model": "M3", "engine": "3.0L L6 - Gas", "year": 2015, "name": "Engine Oil Pump", "oem": "OLD"}])
    assert names(engines.look("bmw", "m3", 2023, idx=idx), "Lubrication") == ["Engine Oil Pan"]
    assert names(engines.look("bmw", "m3", 2015, idx=idx), "Lubrication") == ["Engine Oil Pump"]


def test_one_part_in_many_numbers_is_one_row_with_its_numbers(tmp_path):
    # an ignition switch in 14 paints is one switch
    idx = catalogue(tmp_path, [
        {"model": "M3", "engine": "3.0L L6 - Gas", "year": 2023, "name": "Ignition Switch", "oem": f"SW-{i}"} for i in range(5)
    ])
    rows = engines.look("bmw", "m3", 2023, idx=idx)["parts"]["Sensors and control"]
    assert len(rows) == 1 and rows[0][0] == "Ignition Switch"
    assert rows[0][1].endswith("+3 more") and rows[0][1].count("SW-") == 2


def test_a_trim_picks_the_engine_named_on_it(tmp_path):
    rows = []
    for i in range(4):
        rows += [{"make": "Volkswagen", "model": "Golf", "trim": "S;SE", "engine": "1.4L L4 - Gas", "year": 2021,
                  "name": "Spark Plug", "oem": f"A{i}"},
                 {"make": "Volkswagen", "model": "Golf", "trim": "GTI", "engine": "2.0L L4 - Gas", "year": 2021,
                  "name": "Spark Plug", "oem": f"B{i}"}]
    idx = catalogue(tmp_path, rows)
    assert engines.look("volkswagen", "golf", 2021, idx=idx, trim="gti")["spec"]["litres"] == 2.0
    assert engines.look("volkswagen", "golf", 2021, idx=idx, trim="se")["spec"]["litres"] == 1.4


def test_an_electric_cars_engine_rows_are_left_out(tmp_path):
    idx = catalogue(tmp_path, [
        {"make": "Porsche", "model": "Taycan", "engine": "Electric", "year": 2022, "name": "Fuel Pump Housing", "oem": "F1"},
        {"make": "Porsche", "model": "Taycan", "engine": "Electric", "year": 2022, "name": "Radiator Coolant Hose", "oem": "C1"},
    ])
    r = engines.look("porsche", "taycan", 2022, idx=idx)
    assert r["spec"]["electric"] and "Fuel" not in r["parts"] and names(r, "Cooling") == ["Radiator Coolant Hose"]
    assert r["left_out"] == 1


def test_a_trim_read_as_a_model_only_when_that_model_was_asked(tmp_path, monkeypatch):
    # "911 Carrera": the 911's engine, not the Carrera GT's (a model of its own, holding the word "carrera")
    idx = catalogue(tmp_path, [
        {"make": "Porsche", "model": "911", "trim": "Carrera", "engine": "3.0L H6 - Gas", "year": 2019, "name": "Spark Plug", "oem": f"P{i}"}
        for i in range(3)] + [
        {"make": "Porsche", "model": "Carrera GT", "engine": "5.7L V10 - Gas", "year": 2005, "name": "Spark Plug", "oem": "GT"}])
    monkeypatch.setattr(engines, "INDEX", str(tmp_path / "engines.json"))
    monkeypatch.setattr(engines, "_IDX", idx)
    own = page.own_engine({"make": "porsche", "model_words": "911", "spec": "carrera", "year": 2019}, False)
    assert own["spec"]["layout"] == "flat"
