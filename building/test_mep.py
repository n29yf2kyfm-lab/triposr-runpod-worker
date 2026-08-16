"""Tests for mep.py — the pipes and wires as actual routes."""
import unittest

import electrics
import heatloss
import mep
import model3d as M
import quantities
import ventilation


def _house():
    rooms = [
        M.Room("Living room", 0.0, 0.0, 3.6, 4.6, kind="room", storeys=1),
        M.Room("Hall", 3.6, 0.0, 2.9, 4.6, kind="circulation", storeys=1),
        M.Room("Kitchen", 0.0, 4.6, 4.6, 2.6, kind="kitchen", storeys=1),
        M.Room("WC", 4.6, 4.6, 1.9, 1.2, kind="wet", storeys=1),
        M.Room("Utility", 4.6, 5.8, 1.9, 1.4, kind="wet", storeys=1),
        M.Room("Bedroom 1", 0.0, 0.0, 3.6, 4.6, kind="room",
               storeys=1, base_level=1),
        M.Room("Landing", 3.6, 0.0, 2.9, 4.6, kind="circulation",
               storeys=1, base_level=1),
        M.Room("Bathroom", 3.6, 4.6, 2.9, 2.6, kind="wet",
               storeys=1, base_level=1),
        M.Room("Bedroom 2", 0.0, 4.6, 3.6, 2.6, kind="room",
               storeys=1, base_level=1),
    ]
    model = M.build(rooms, storeys=2, storey_height=2.7,
                    roof={"pitch_deg": 35.0, "kind": "gabled",
                          "overhang": 0.3, "max_span_m": 12.0})
    M.apply_facade_openings(model, [
        {"kind": "window", "along": 0.9, "width": 1.8, "height": 1.35,
         "sill": 0.9, "level": 0},
        {"kind": "door", "along": 4.35, "width": 0.95, "height": 2.05,
         "sill": 0.0, "level": 0},
    ], facade_y=0.0)
    return model


class TestRouting(unittest.TestCase):
    def setUp(self):
        self.model = _house()
        self.heat = heatloss.design(self.model)
        self.elec = electrics.design(self.model, heat=self.heat)
        self.vent = ventilation.design(self.model)
        self.d = mep.design(self.model, heat=self.heat, elec=self.elec,
                            vent=self.vent)

    def test_every_radiator_gets_a_flow_and_a_return(self):
        rads = [r for r in self.heat["rooms"] if r.get("radiator")]
        self.assertTrue(rads)
        for hr in rads:
            rad = hr["radiator"]
            got = set()
            for run in self.d["runs"]:
                if run["system"] != "heating" or run["size"] != "15mm copper":
                    continue
                last = run["points"][-1]
                if (abs(last[0] - rad["x"]) < 0.2
                        and abs(last[1] - rad["y"]) < 0.2):
                    got.add(run["service"])
            self.assertEqual(got, {"flow", "return"},
                             f"{hr['name']} radiator not connected both ways")

    def test_every_run_is_a_real_polyline(self):
        for run in self.d["runs"]:
            self.assertGreaterEqual(len(run["points"]), 2, run)
            self.assertGreater(run["length_m"], 0.0, run)
            for p in run["points"]:
                self.assertEqual(len(p), 3)

    def test_routes_stay_inside_the_building(self):
        """Only the underground drain may leave — it goes to the boundary."""
        ex = self.model["extent_m"]["x"]
        ey = self.model["extent_m"]["y"]
        for run in self.d["runs"]:
            if run["service"] == "underground drain":
                continue
            for x, y, _ in run["points"]:
                self.assertGreaterEqual(x, ex[0] - 0.35, run)
                self.assertLessEqual(x, ex[1] + 0.35, run)
                self.assertGreaterEqual(y, ey[0] - 0.35, run)
                self.assertLessEqual(y, ey[1] + 0.35, run)

    def test_cable_reaches_accessories_by_a_vertical_drop(self):
        """BS 7671 522.6.202: the last leg to an outlet is vertical."""
        checked = 0
        for run in self.d["runs"]:
            if run["service"] != "ring final" or "outlet" not in \
                    run.get("note", ""):
                continue
            a, b = run["points"][-2], run["points"][-1]
            self.assertAlmostEqual(a[0], b[0], places=3, msg=run)
            self.assertAlmostEqual(a[1], b[1], places=3, msg=run)
            self.assertNotAlmostEqual(a[2], b[2], places=3, msg=run)
            checked += 1
        self.assertGreater(checked, 5)

    def test_waste_falls_towards_the_stack(self):
        falls = 0
        for run in self.d["runs"]:
            if run["system"] != "drainage":
                continue
            if run["service"] not in ("soil", "waste"):
                continue
            self.assertLess(run["points"][-1][2], run["points"][0][2],
                            f"{run.get('note')} does not fall")
            falls += 1
        self.assertGreater(falls, 2)

    def test_soil_stack_vents_above_the_roof_eaves(self):
        stack = [r for r in self.d["runs"] if r["service"] == "soil stack"]
        self.assertEqual(len(stack), 1)
        top = stack[0]["points"][-1][2]
        self.assertGreater(top, self.model["eaves_z_m"] - 0.5)
        self.assertLess(stack[0]["points"][0][2], 0.0)   # starts below ground

    def test_boiler_lands_in_the_utility(self):
        b = mep.plant(self.model)
        self.assertEqual(b["room"], "Utility")
        self.assertEqual(b["kind"], "combi")

    def test_boiler_falls_back_to_the_kitchen(self):
        rooms = [M.Room("Kitchen", 0.0, 0.0, 4.0, 4.0, kind="kitchen"),
                 M.Room("Hall", 4.0, 0.0, 2.0, 4.0, kind="circulation")]
        m = M.build(rooms, storeys=1, storey_height=2.7,
                    roof={"pitch_deg": 30.0, "kind": "gabled",
                          "overhang": 0.3, "max_span_m": 12.0})
        self.assertEqual(mep.plant(m)["room"], "Kitchen")

    def test_totals_are_the_sum_of_the_runs(self):
        by_key = {}
        for r in self.d["runs"]:
            k = f"{r['system']}:{r['size']}"
            by_key[k] = by_key.get(k, 0.0) + r["length_m"]
        for k, v in by_key.items():
            self.assertAlmostEqual(self.d["totals_m"][k], v, places=1)

    def test_a_house_with_no_wet_rooms_still_routes(self):
        rooms = [M.Room("Studio", 0.0, 0.0, 5.0, 5.0, kind="room"),
                 M.Room("Kitchen", 5.0, 0.0, 3.0, 5.0, kind="kitchen")]
        m = M.build(rooms, storeys=1, storey_height=2.7,
                    roof={"pitch_deg": 30.0, "kind": "gabled",
                          "overhang": 0.3, "max_span_m": 12.0})
        d = mep.design(m, heat=heatloss.design(m),
                       elec=electrics.design(m), vent=ventilation.design(m))
        self.assertEqual([r for r in d["runs"]
                          if r["service"] == "soil stack"], [])
        self.assertTrue(d["runs"])          # heating and power still routed

    def test_it_does_not_claim_clash_free_coordination(self):
        joined = " ".join(self.d["notes"]).lower()
        self.assertIn("not clash-checked", joined)


class TestBillUsesRoutedLengths(unittest.TestCase):
    def test_routed_beats_rules_of_thumb_when_available(self):
        model = _house()
        heat = heatloss.design(model)
        elec = electrics.design(model, heat=heat)
        d = mep.design(model, heat=heat, elec=elec)

        routed = quantities.bill(model, heat=heat, elec=elec, mep=d)
        rules = quantities.bill(model, heat=heat, elec=elec, mep={})
        r_basis = " ".join(L["basis"] for L in routed["groups"]["services"])
        k_basis = " ".join(L["basis"] for L in rules["groups"]["services"])
        self.assertIn("routed", r_basis)
        self.assertNotIn("routed", k_basis)
        # and the routed bill knows about drainage, which no rule of thumb
        # in this codebase ever estimated
        self.assertTrue(any("drainage" in L["item"]
                            for L in routed["groups"]["services"]))

    def test_pipeline_carries_the_routes(self):
        model = _house()
        extra = M._with_buildability(model)
        M._absorb_buildability(model, extra)
        self.assertIn("mep", model)
        self.assertGreater(model["mep"]["counts"]["runs"], 10)
        svc = model["quantities_bill"]["groups"]["services"]
        self.assertTrue(any("routed" in L["basis"] for L in svc))


if __name__ == "__main__":
    unittest.main()
