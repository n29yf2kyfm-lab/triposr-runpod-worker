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


def _l_plan_house():
    """The _house fixture with Bedroom 2 removed, so level 1 is an
    L-shaped plate with an open-air notch at x<3.6, y>4.6. On this plan
    the bounding box and the building are different things, which is
    exactly what the routing once got wrong."""
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
    ]
    return M.build(rooms, storeys=2, storey_height=2.7,
                   roof={"pitch_deg": 35.0, "kind": "gabled",
                         "overhang": 0.3, "max_span_m": 12.0})


def _covered_by_a_room(model, x, y, level, tol=0.35):
    """Is (x, y) within a room that stands on `level` (None = any),
    with no more slack than a wall's thickness?"""
    for r in model["rooms"]:
        base = int(r.get("base_level") or 0)
        n = r.get("storeys")
        top = model["storeys"] if n is None else min(base + int(n),
                                                     model["storeys"])
        if level is not None and not (base <= level < top):
            continue
        if (r["x"] - tol <= x <= r["x"] + r["width_m"] + tol
                and r["y"] - tol <= y <= r["y"] + r["depth_m"] + tol):
            return True
    return False


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

    def test_l_plan_routes_stay_in_rooms_not_the_bounding_box(self):
        """The building is the rooms, not the box around them. The old
        extent-only containment let the Bedroom 1 heating branch cross
        the level-1 notch through (1.625, 7.0) — open air — on this
        exact fixture, so every interior point must now sit within a
        room on the run's own level, wall tolerance only."""
        m = _l_plan_house()
        heat = heatloss.design(m)
        elec = electrics.design(m, heat=heat)
        d = mep.design(m, heat=heat, elec=elec, vent=ventilation.design(m))
        for run in d["runs"]:
            if run["service"] == "underground drain":
                continue
            for x, y, _ in run["points"]:
                self.assertTrue(
                    _covered_by_a_room(m, x, y, run["level"]),
                    f"{run['service']} ({run.get('note')}) passes through "
                    f"({x}, {y}) outside every room on level "
                    f"{run['level']}")
        # Corner selection upstairs, proven directly rather than counted:
        # a point count also matches straight legs once their jog and
        # rise points are appended, so it proves nothing. From Bedroom 1
        # to the Bathroom the corner (1.8, 6.0) is the open-air notch, so
        # the leg must turn at (5.0, 2.0) inside the Landing.
        pts, warn = mep._leg(m, (1.8, 2.0), (5.0, 6.0),
                             1 * 2.7 - mep.FLOOR_VOID_M, level=1)
        self.assertIsNone(warn)
        self.assertEqual((pts[1][0], pts[1][1]), (5.0, 2.0))

    def test_leg_takes_the_corner_that_stays_in_a_room(self):
        """Living 5x8 plus Kitchen 5x2 leaves a notch at x>5, y>2.
        From (2.5, 6) to (7.5, 1) the corner (7.5, 6) is open air, so
        the leg must turn at (2.5, 1) inside the Living room."""
        rooms = [M.Room("Living", 0.0, 0.0, 5.0, 8.0, kind="room"),
                 M.Room("Kitchen", 5.0, 0.0, 5.0, 2.0, kind="kitchen")]
        m = M.build(rooms, storeys=1, storey_height=2.7,
                    roof={"pitch_deg": 30.0, "kind": "gabled",
                          "overhang": 0.3, "max_span_m": 12.0})
        pts, warn = mep._leg(m, (2.5, 6.0), (7.5, 1.0), -0.08, level=0)
        self.assertIsNone(warn)
        self.assertEqual((pts[1][0], pts[1][1]), (2.5, 1.0))

    def test_leg_warns_instead_of_pretending_a_route_exists(self):
        """Two disjoint wings: both corners of the L land in open air,
        so the leg must say so rather than silently draw through it."""
        m = {"rooms": [{"name": "A", "x": 0.0, "y": 0.0,
                        "width_m": 2.0, "depth_m": 2.0},
                       {"name": "B", "x": 3.0, "y": 3.0,
                        "width_m": 2.0, "depth_m": 2.0}],
             "storeys": 1}
        pts, warn = mep._leg(m, (1.0, 1.0), (4.0, 4.0), 0.0, level=0)
        self.assertIsNotNone(warn)
        self.assertIn("LEAVES THE BUILDING", warn)

    def test_upper_ring_final_rises_and_returns(self):
        """A ring is two legs at the consumer unit. In the fixture
        (per=2.7, CU at level 0) each riser spans -0.08 to 2.62, i.e.
        exactly 2.7 m of 2.5mm2 T&E each way."""
        risers = [r for r in self.d["runs"]
                  if r["service"] == "ring final riser"]
        self.assertEqual(len(risers), 2)
        for r in risers:
            self.assertAlmostEqual(r["length_m"], 2.7, places=2)
            zs = {p[2] for p in r["points"]}
            self.assertEqual(zs, {-0.08, 2.62})
        self.assertTrue(any("returns" in r["note"] for r in risers))

    def test_upper_lighting_gets_a_riser_from_the_consumer_unit(self):
        """Level-1 lighting lives at z = 2*2.7 - 0.06 = 5.34; the feed
        from the CU floor void at -0.08 is 5.42 m of 1.5mm2 T&E that
        used to be missing from the totals."""
        risers = [r for r in self.d["runs"]
                  if r["service"] == "lighting riser"]
        self.assertEqual(len(risers), 1)
        self.assertAlmostEqual(risers[0]["length_m"], 5.42, places=2)
        self.assertEqual([p[2] for p in risers[0]["points"]],
                         [-0.08, 5.34])

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

    def test_waste_fall_is_distributed_over_every_leg(self):
        """Dropping only the end point left the leg round the corner
        dead level, and a level waste pipe does not drain. Every
        segment must now fall at the stated 1:40 of its own plan
        length (0.0025 tolerance covers coordinate rounding)."""
        multi = 0
        for run in self.d["runs"]:
            if run["service"] not in ("soil", "waste"):
                continue
            if len(run["points"]) >= 3:
                multi += 1
            for a, b in zip(run["points"], run["points"][1:]):
                plan = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
                self.assertAlmostEqual(a[2] - b[2], plan / 40.0, delta=0.0025,
                                       msg=f"{run.get('note')} segment "
                                           f"{a}->{b} is not at 1:40")
        self.assertGreater(multi, 0)     # a cornered run must be exercised

    def test_underground_drain_falls_at_its_stated_1_in_40(self):
        """The drain once dropped a fixed 0.3 m whatever its length,
        while its note claimed 1:40 min. In the fixture the stack sits
        at y=7.0 and the boundary at y=11.2: 4.2 m of run, so the
        outfall must be 4.2/40 = 0.105 m below the -0.6 stack base."""
        drain = [r for r in self.d["runs"]
                 if r["service"] == "underground drain"]
        self.assertEqual(len(drain), 1)
        a, b = drain[0]["points"][0], drain[0]["points"][-1]
        plan = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        self.assertAlmostEqual(plan, 4.2, places=2)
        self.assertAlmostEqual(a[2], -0.6, places=3)
        self.assertAlmostEqual(b[2], -0.705, places=3)
        self.assertGreaterEqual(a[2] - b[2] + 1e-6, plan / 40.0)

    def test_heating_and_power_runs_are_orthogonal(self):
        """The module promises orthogonal polylines; the radiator tail
        used to move in x and z at once. Dry runs (pipes fall, cables
        do not) must change one axis per segment, never two."""
        for run in self.d["runs"]:
            if run["system"] not in ("heating", "power"):
                continue
            for a, b in zip(run["points"], run["points"][1:]):
                moved = sum(1 for i in range(3)
                            if abs(b[i] - a[i]) > 1e-6)
                self.assertLessEqual(moved, 1,
                                     f"{run.get('note')} has a diagonal "
                                     f"segment {a}->{b}")

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

    def test_boiler_sits_against_a_genuinely_external_wall(self):
        """The Utility (x 4.6-6.5, y 5.8-7.2) reaches the envelope on
        its right and back faces only; the boiler must sit 0.35 m off
        one of them, not against an internal partition, and needs no
        unresolved-flue note."""
        b = mep.plant(self.model)
        ex = self.model["extent_m"]
        d = min(abs(b["x"] - ex["x"][0]), abs(ex["x"][1] - b["x"]),
                abs(b["y"] - ex["y"][0]), abs(ex["y"][1] - b["y"]))
        self.assertAlmostEqual(d, 0.35, places=3)
        self.assertNotIn("note", b)

    def test_boiler_with_no_external_wall_says_so(self):
        """A kitchen walled in on all four sides cannot take a combi
        flue; the old two-face check would have called its partitions
        external. The boiler is still placed, but the record must say
        the flue is unresolved rather than silently mislead."""
        rooms = [M.Room("Living", 0.0, 0.0, 10.0, 2.0, kind="room"),
                 M.Room("Hall", 0.0, 2.0, 3.0, 3.0, kind="circulation"),
                 M.Room("Kitchen", 3.0, 2.0, 4.0, 3.0, kind="kitchen"),
                 M.Room("Study", 7.0, 2.0, 3.0, 3.0, kind="room"),
                 M.Room("Back", 0.0, 5.0, 10.0, 3.0, kind="room")]
        m = M.build(rooms, storeys=1, storey_height=2.7,
                    roof={"pitch_deg": 30.0, "kind": "gabled",
                          "overhang": 0.3, "max_span_m": 12.0})
        b = mep.plant(m)
        self.assertEqual(b["room"], "Kitchen")
        self.assertIn("unresolved", b.get("note", ""))
        # and still inside the kitchen: 0.35 in from its own right wall
        self.assertAlmostEqual(b["x"], 6.65, places=3)
        self.assertAlmostEqual(b["y"], 3.5, places=3)

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
