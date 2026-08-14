"""Tests for heatloss.py and ventilation.py against hand calculations.

The fixture is deliberately tiny — one heated box and one bathroom — so
every expected number can be worked longhand in the comments beside it.
"""
import unittest

import model3d as M
import electrics
import heatloss
import ventilation


def _box_model():
    """One 4x5 living room, one storey, one 1.2x1.2 window in the front."""
    rooms = [M.Room("Living room", 0.0, 0.0, 4.0, 5.0, kind="room")]
    model = M.build(rooms, storeys=1, storey_height=2.7,
                    roof={"pitch_deg": 30.0, "kind": "gabled",
                          "overhang": 0.3, "max_span_m": 12.0})
    M.apply_facade_openings(model, [
        {"kind": "window", "along": 1.4, "width": 1.2, "height": 1.2,
         "sill": 0.9, "level": 0},
    ], facade_y=0.0)
    return model


class TestHeatLoss(unittest.TestCase):
    def setUp(self):
        self.model = _box_model()
        self.out = heatloss.design(self.model)
        self.room = self.out["rooms"][0]

    def test_hand_calculation_matches(self):
        # Geometry: perimeter 2*(4+5)=18 m, wall height 2.4 m ->
        # gross 43.2 m2, minus rule windows model3d added plus our 1.44 m2.
        r = self.room
        glazed = r["glazing_m2"]
        wall_net = r["wall_net_m2"]
        # model3d places a rule entrance door as well as rule windows, so
        # the balance of the 43.2 m2 gross not in wall or glass is door.
        door = 43.2 - wall_net - glazed
        self.assertGreater(door, 0.0)
        self.assertLess(door, 2.5)
        # Fabric W/K: (wall*0.18 + glass*1.2 + door*1.0 + 20*0.11 roof
        # + 20*0.13 floor) * 1.15 bridging.
        expect_fabric = (wall_net * 0.18 + glazed * 1.2 + door * 1.0
                         + 20.0 * 0.11 + 20.0 * 0.13) * 1.15
        self.assertAlmostEqual(r["fabric_WK"], expect_fabric, places=0)
        # Vent W/K: 0.33 * 0.5 ach * 48 m3 = 7.92.
        self.assertAlmostEqual(r["vent_WK"], 0.33 * 0.5 * 20.0 * 2.4,
                               places=1)
        # Loss at 21 - (-3) = 24 K.
        self.assertAlmostEqual(
            r["loss_W"], (r["fabric_WK"] + r["vent_WK"]) * 24.0, delta=1.0)

    def test_radiator_under_window_and_sized_up(self):
        rad = self.room["radiator"]
        self.assertIsNotNone(rad)
        # Delta-T 45 correction means nominal output exceeds the loss.
        self.assertGreaterEqual(rad["output_W"], self.room["loss_W"])
        # Placed on the front wall (y=0), inside the room.
        self.assertLess(rad["y"], 0.5)
        self.assertGreater(rad["y"], 0.0)

    def test_wet_rooms_get_towel_rail_and_18C_for_wc(self):
        rooms = [M.Room("Living room", 0.0, 0.0, 4.0, 5.0, kind="room"),
                 M.Room("Bathroom", 4.0, 0.0, 2.0, 2.5, kind="wet"),
                 M.Room("WC", 4.0, 2.5, 2.0, 2.5, kind="wet")]
        model = M.build(rooms, storeys=1, storey_height=2.7,
                        roof={"pitch_deg": 30.0, "kind": "gabled",
                              "overhang": 0.3, "max_span_m": 12.0})
        out = heatloss.design(model)
        by_name = {r["name"]: r for r in out["rooms"]}
        self.assertEqual(by_name["Bathroom"]["temp_C"], 22.0)
        self.assertEqual(by_name["WC"]["temp_C"], 18.0)
        rad = by_name["Bathroom"]["radiator"]
        self.assertIsNotNone(rad)
        self.assertEqual(rad["type"], "towel")

    def test_totals_are_sums(self):
        total = sum(r["loss_W"] for r in self.out["rooms"])
        self.assertAlmostEqual(self.out["totals"]["loss_W"], total, delta=2)


class TestVentilation(unittest.TestCase):
    def _three_bed(self):
        rooms = [
            M.Room("Living room", 0.0, 0.0, 4.0, 5.0, kind="room"),
            M.Room("Kitchen", 4.0, 0.0, 3.0, 5.0, kind="kitchen"),
            M.Room("Bed 1", 0.0, 0.0, 4.0, 5.0, kind="room", base_level=1,
                   storeys=1),
            M.Room("Bed 2", 4.0, 0.0, 3.0, 2.5, kind="room", base_level=1,
                   storeys=1),
            M.Room("Bathroom", 4.0, 2.5, 3.0, 2.5, kind="wet",
                   base_level=1, storeys=1),
            M.Room("Master bedroom", 0.0, 0.0, 4.0, 5.0, kind="room",
                   base_level=0, storeys=1),
        ]
        # Master overlaps living in plan? No — keep it simple: separate
        # dwellings aren't the point, bedroom COUNTING is. Rename to a
        # non-overlapping strip.
        rooms[-1] = M.Room("Master bedroom", 0.0, 5.0, 7.0, 2.0,
                           kind="room")
        return M.build(rooms, storeys=2, storey_height=2.7,
                       roof={"pitch_deg": 30.0, "kind": "gabled",
                             "overhang": 0.3, "max_span_m": 12.0})

    def test_bedroom_count_and_whole_dwelling_rate(self):
        out = ventilation.design(self._three_bed())
        self.assertEqual(out["bedrooms"], 3)
        self.assertEqual(out["by_bedrooms_ls"], 31.0)
        # Floor area 7x5 + 7x2 = 49 both storeys... the build computes it;
        # whichever governs, the whole-dwelling figure is the max of both.
        self.assertEqual(out["whole_dwelling_ls"],
                         max(out["by_bedrooms_ls"],
                             out["by_floor_area_ls"]))

    def test_extract_rates_by_wet_room_name(self):
        rooms = [M.Room("Living room", 0.0, 0.0, 4.0, 5.0, kind="room"),
                 M.Room("Kitchen", 4.0, 0.0, 3.0, 5.0, kind="kitchen"),
                 M.Room("Bathroom", 0.0, 5.0, 2.0, 2.0, kind="wet"),
                 M.Room("WC", 2.0, 5.0, 2.0, 2.0, kind="wet"),
                 M.Room("Utility", 4.0, 5.0, 3.0, 2.0, kind="wet")]
        model = M.build(rooms, storeys=1, storey_height=2.7,
                        roof={"pitch_deg": 30.0, "kind": "gabled",
                              "overhang": 0.3, "max_span_m": 12.0})
        out = ventilation.design(model)
        rates = {f["name"]: f["extract_ls"] for f in out["extract_fans"]}
        self.assertEqual(rates["Kitchen"], 60.0)
        self.assertEqual(rates["Bathroom"], 15.0)
        self.assertEqual(rates["WC"], 6.0)
        self.assertEqual(rates["Utility"], 30.0)

    def test_habitable_rooms_get_trickle_vents_circulation_does_not(self):
        rooms = [M.Room("Living room", 0.0, 0.0, 4.0, 5.0, kind="room"),
                 M.Room("Hall", 4.0, 0.0, 2.0, 5.0, kind="circulation")]
        model = M.build(rooms, storeys=1, storey_height=2.7,
                        roof={"pitch_deg": 30.0, "kind": "gabled",
                              "overhang": 0.3, "max_span_m": 12.0})
        out = ventilation.design(model)
        names = [v["name"] for v in out["background_ventilators"]]
        self.assertIn("Living room", names)
        self.assertNotIn("Hall", names)

    def test_pipeline_carries_heat_and_vent(self):
        # the exported model must know its radiators and its fans
        model = self._three_bed()
        extra = M._with_buildability(model)
        M._absorb_buildability(model, extra)
        self.assertIn("heat", model)
        self.assertIn("vent", model)
        self.assertIn("elec", model)
        self.assertGreater(model["heat"]["totals"]["loss_W"], 0)
        self.assertTrue(model["vent"]["extract_fans"])


class TestElectrics(unittest.TestCase):
    def _model(self):
        rooms = [M.Room("Living room", 0.0, 0.0, 4.0, 5.0, kind="room"),
                 M.Room("Kitchen", 4.0, 0.0, 3.0, 5.0, kind="kitchen"),
                 M.Room("Hall", 0.0, 5.0, 3.0, 2.0, kind="circulation"),
                 M.Room("Bathroom", 3.0, 5.0, 2.0, 2.0, kind="wet"),
                 M.Room("Bed 1", 5.0, 5.0, 2.0, 2.0, kind="room")]
        return M.build(rooms, storeys=1, storey_height=2.7,
                       roof={"pitch_deg": 30.0, "kind": "gabled",
                             "overhang": 0.3, "max_span_m": 12.0})

    def setUp(self):
        self.out = electrics.design(self._model())
        self.by_name = {r["name"]: r for r in self.out["rooms"]}

    def test_socket_counts_follow_room_use(self):
        self.assertEqual(self.by_name["Living room"]["sockets_twin"], 5)
        self.assertEqual(self.by_name["Kitchen"]["sockets_twin"], 6)
        # 2x2 bedroom is under 10 m2 -> single-bed count
        self.assertEqual(self.by_name["Bed 1"]["sockets_twin"], 3)
        # bathrooms get none, BS 7671 section 701
        self.assertEqual(self.by_name["Bathroom"]["sockets_twin"], 0)
        self.assertEqual(self.by_name["Bathroom"]["placed"], [])

    def test_sockets_land_on_the_rooms_own_walls(self):
        for r in self.out["rooms"]:
            room = next(m for m in self._model()["rooms"]
                        if m["name"] == r["name"])
            x0, y0 = room["x"], room["y"]
            x1, y1 = x0 + room["width_m"], y0 + room["depth_m"]
            for s in r["placed"]:
                on_edge = (abs(s["y"] - y0) < 1e-6 or abs(s["y"] - y1) < 1e-6
                           or abs(s["x"] - x0) < 1e-6
                           or abs(s["x"] - x1) < 1e-6)
                self.assertTrue(on_edge, f"{r['name']} socket off-wall: {s}")
                self.assertTrue(x0 <= s["x"] <= x1 and y0 <= s["y"] <= y1)

    def test_kitchen_sockets_at_worktop_height(self):
        self.assertEqual(self.by_name["Kitchen"]["socket_height_m"], 1.10)
        self.assertEqual(self.by_name["Living room"]["socket_height_m"], 0.45)

    def test_detection_grade_d1(self):
        kinds = {(a["type"], a["name"]) for a in self.out["alarms"]}
        self.assertIn(("smoke", "Hall"), kinds)
        self.assertIn(("heat", "Kitchen"), kinds)

    def test_consumer_unit_in_hall_and_circuits_match_storeys(self):
        self.assertEqual(self.out["consumer_unit"]["room"], "Hall")
        names = [c["name"] for c in self.out["circuits"]]
        self.assertNotIn("Ring final - first floor", names)  # one storey
        self.assertIn("Ring final - ground floor", names)
        self.assertIn("Kitchen ring final", names)


if __name__ == "__main__":
    unittest.main()
