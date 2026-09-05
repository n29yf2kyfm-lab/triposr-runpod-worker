"""Tests for heatloss.py and ventilation.py against hand calculations.

The fixture is deliberately tiny — one heated box and one bathroom — so
every expected number can be worked longhand in the comments beside it.
"""
import unittest

import model3d as M
import electrics
import heatloss
import quantities
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

    def test_big_bathroom_keeps_towel_rail_and_adds_radiator(self):
        # A 4x3 bathroom at 22 C. Its y=3 return faces the plan's open
        # 4x2 notch — GARDEN, not a construction void (the void probe
        # once flagged any inside-the-bbox gap and dropped this wall,
        # understating the room by ~90 W). Gross external wall
        # (4+3+4)*2.4 = 26.4 m2; three 1.2x1.2 rule windows glaze
        # 4.32 m2, wall net 22.08. Fabric (22.08*0.18 + 4.32*1.2 +
        # 12*0.11 roof + 12*0.13 floor)*1.15 = 13.84 W/K; vent
        # 0.33*1.5*28.8 = 14.26 W/K; loss (13.84+14.26)*25 = 703 W.
        # Need 703/0.872 = 806 W nominal > 450 towel rail, so a panel for
        # the 356 W balance must JOIN the rail, not replace it — replacing
        # shipped the room exactly 450 W short.
        rooms = [M.Room("Living room", 0.0, 0.0, 4.0, 5.0, kind="room"),
                 M.Room("Bathroom", 4.0, 0.0, 4.0, 3.0, kind="wet")]
        model = M.build(rooms, storeys=1, storey_height=2.7,
                        roof={"pitch_deg": 30.0, "kind": "gabled",
                              "overhang": 0.3, "max_span_m": 12.0})
        out = heatloss.design(model)
        bath = next(r for r in out["rooms"] if r["name"] == "Bathroom")
        self.assertAlmostEqual(bath["loss_W"], 703, delta=2)
        rad, towel = bath["radiator"], bath.get("towel_rail")
        self.assertIsNotNone(rad)
        self.assertIsNotNone(towel)
        self.assertEqual(towel["type"], "towel")
        self.assertEqual(towel["output_W"], 450)
        self.assertNotEqual(rad["type"], "towel")
        # Combined nominal output covers the loss (need = loss/0.872, and
        # 450 + 440 = 890 >= 703): the room is no longer scheduled short.
        self.assertGreaterEqual(rad["output_W"] + towel["output_W"],
                                bath["loss_W"])
        self.assertNotIn("shortfall_W", rad)

    def _one_room_one_window(self, name, width, depth, win_w):
        """One room, all rule openings stripped, one window of win_w."""
        rooms = [M.Room(name, 0.0, 0.0, width, depth, kind="room")]
        model = M.build(rooms, storeys=1, storey_height=2.7,
                        roof={"pitch_deg": 30.0, "kind": "gabled",
                              "overhang": 0.3, "max_span_m": 12.0})
        for w in model["walls"]:
            w["openings"] = []
        front = next(w for w in model["walls"]
                     if abs(w["start"][1]) < 1e-6 and abs(w["end"][1]) < 1e-6)
        front["openings"].append({"kind": "window", "along": 1.0,
                                  "width": win_w, "height": 1.2,
                                  "sill": 0.9, "level": 0})
        return model

    def test_narrow_window_steps_up_panel_type(self):
        # 4x5 room, single 0.6 m window. Gross 18*2.4 = 43.2 m2, glazing
        # 0.72, wall net 42.48. Fabric (42.48*0.18 + 0.72*1.2 + 20*0.11 +
        # 20*0.13)*1.15 = 15.31 W/K; vent 0.33*0.5*48 = 7.92; loss
        # 23.23*24 = 557 W; need 557/0.872 = 639 W nominal. A K1 wants
        # 639/1100 = 0.58 m but the window only takes 0.6-0.05 = 0.55 m,
        # so the type steps up: K2 at 0.4 m = 760 W >= need. Clipping a
        # K1 to 0.55 m (605 W) would have shipped it short of the need.
        model = self._one_room_one_window("Living room", 4.0, 5.0, 0.6)
        out = heatloss.design(model)
        r = out["rooms"][0]
        self.assertAlmostEqual(r["loss_W"], 557, delta=2)
        rad = r["radiator"]
        self.assertEqual(rad["type"], "K2")
        self.assertAlmostEqual(rad["len_m"], 0.4, places=2)
        self.assertEqual(rad["output_W"], 760)
        self.assertNotIn("shortfall_W", rad)

    def test_narrow_window_shortfall_is_flagged(self):
        # 10x8 room, single 0.6 m window. Gross 36*2.4 = 86.4 m2, wall
        # net 85.68; fabric (85.68*0.18 + 0.72*1.2 + 80*0.11 + 80*0.13)
        # *1.15 = 40.81 W/K; vent 0.33*0.5*192 = 31.68; loss 72.49*24
        # = 1740 W; need 1740/0.872 = 1995 W. Even a K3 on the 0.55 m the
        # window takes gives 2500*0.55 = 1375 W, so the record must say
        # so: shortfall (1995-1375)*0.872 = 541 W of the design loss the
        # emitter cannot deliver, echoed in the notes.
        model = self._one_room_one_window("Hall of mirrors", 10.0, 8.0, 0.6)
        out = heatloss.design(model)
        r = out["rooms"][0]
        self.assertAlmostEqual(r["loss_W"], 1740, delta=2)
        rad = r["radiator"]
        self.assertEqual(rad["type"], "K3")
        self.assertAlmostEqual(rad["len_m"], 0.55, places=2)
        self.assertEqual(rad["output_W"], 1375)
        self.assertAlmostEqual(rad["shortfall_W"], 541, delta=2)
        self.assertTrue(any("fall short" in n for n in out["notes"]))

    def test_room_with_no_radiator_wall_is_said_out_loud(self):
        # Every external wall carries floor-to-ceiling glazing (sill 0,
        # so no window qualifies as a radiator perch and no wall run is
        # clear): the room still loses heat, and the design must say the
        # emitter is missing rather than leave a silent null.
        model = self._one_room_one_window("Glass box", 4.0, 5.0, 1.0)
        for w in model["walls"]:
            if w["external"]:
                w["openings"] = [{"kind": "window", "along": 0.5,
                                  "width": 1.0, "height": 2.2,
                                  "sill": 0.0, "level": 0}]
        out = heatloss.design(model)
        r = out["rooms"][0]
        self.assertIsNone(r["radiator"])
        self.assertGreater(r["loss_W"], heatloss.MIN_EMITTER_W)
        self.assertTrue(any("No emitter could be placed" in n
                            for n in out["notes"]))

    def test_wall_over_single_storey_wing_is_facade_and_wing_gets_roof(self):
        # Two-storey 4x5 house with a single-storey 4x3 kitchen wing
        # behind it. The y=5 wall between them is internal at ground
        # (kitchen behind it, shared_storeys=1) but faces open air over
        # the wing's roof at level 1.
        rooms = [M.Room("House", 0.0, 0.0, 4.0, 5.0, kind="room"),
                 M.Room("Kitchen", 0.0, 5.0, 4.0, 3.0, kind="kitchen",
                        base_level=0, storeys=1)]
        model = M.build(rooms, storeys=2, storey_height=2.7,
                        roof={"pitch_deg": 30.0, "kind": "gabled",
                              "overhang": 0.3, "max_span_m": 12.0})
        out = heatloss.design(model)
        by = {(r["name"], r["level"]): r for r in out["rooms"]}
        # Level 0 counts x=0, x=4 and y=0 (14 m of wall); level 1 adds
        # the 4 m wall over the wing: net difference exactly 4*2.4 = 9.6
        # m2 (same rule glazing and door both levels).
        self.assertAlmostEqual(
            by[("House", 1)]["wall_net_m2"] - by[("House", 0)]["wall_net_m2"],
            9.6, places=2)
        # The wing's top level (0) is below the building's top (1) with
        # sky above, so it gets the roof term: gross 10*2.4 = 24 m2,
        # glazing 4.32, net 19.68, fabric (19.68*0.18 + 4.32*1.2 +
        # 12*0.11 roof + 12*0.13 floor)*1.15 = 13.3 W/K. Without the
        # roof term it would read 11.8.
        self.assertAlmostEqual(by[("Kitchen", 0)]["fabric_WK"], 13.3,
                               delta=0.15)

    def test_room_with_heated_room_above_gets_no_roof_term(self):
        # Same wing, but with a bedroom built on top of the kitchen: the
        # kitchen ceiling is now heated both sides, so no roof term.
        # Fabric (19.68*0.18 + 4.32*1.2 + 12*0.13 floor)*1.15 = 11.8 W/K.
        rooms = [M.Room("House", 0.0, 0.0, 4.0, 5.0, kind="room"),
                 M.Room("Kitchen", 0.0, 5.0, 4.0, 3.0, kind="kitchen",
                        base_level=0, storeys=1),
                 M.Room("Bed 3", 0.0, 5.0, 4.0, 3.0, kind="room",
                        base_level=1, storeys=1)]
        model = M.build(rooms, storeys=2, storey_height=2.7,
                        roof={"pitch_deg": 30.0, "kind": "gabled",
                              "overhang": 0.3, "max_span_m": 12.0})
        out = heatloss.design(model)
        kit = next(r for r in out["rooms"] if r["name"] == "Kitchen")
        self.assertAlmostEqual(kit["fabric_WK"], 11.8, delta=0.15)

    def test_void_facing_walls_are_not_facade(self):
        # Two rooms drawn 0.5 m apart: both facing walls come out of the
        # build external=True but void_facing=True — the "outside" is a
        # cavity inside the plan, not the -3 C sky. Room A's counted
        # envelope is x=0, y=0 and y=5 only: gross 13*2.4 = 31.2 m2, so
        # wall net plus glazing is bounded by 31.2 (the balance is the
        # rule door); counting the void wall would push it towards 43.2.
        rooms = [M.Room("Room A", 0.0, 0.0, 4.0, 5.0, kind="room"),
                 M.Room("Room B", 4.5, 0.0, 4.0, 5.0, kind="room")]
        model = M.build(rooms, storeys=1, storey_height=2.7,
                        roof={"pitch_deg": 30.0, "kind": "gabled",
                              "overhang": 0.3, "max_span_m": 12.0})
        self.assertTrue(any(w.get("void_facing") for w in model["walls"]))
        out = heatloss.design(model)
        a = next(r for r in out["rooms"] if r["name"] == "Room A")
        self.assertLessEqual(a["wall_net_m2"] + a["glazing_m2"], 31.2 + 0.01)
        self.assertGreater(a["wall_net_m2"] + a["glazing_m2"], 31.2 - 2.5)
        # and nobody hangs a radiator on a wall facing the cavity
        for r in out["rooms"]:
            rad = r["radiator"]
            if rad:
                self.assertFalse(3.95 < rad["x"] < 4.55,
                                 f"radiator in the void strip: {rad}")


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


class TestQuantities(unittest.TestCase):
    """Longhand checks: one plain box whose arithmetic fits in a comment."""

    def _model(self):
        rooms = [M.Room("Living room", 0.0, 0.0, 4.0, 5.0, kind="room")]
        model = M.build(rooms, storeys=1, storey_height=2.7,
                        roof={"pitch_deg": 30.0, "kind": "gabled",
                              "overhang": 0.3, "max_span_m": 12.0})
        return model

    def test_brick_count_longhand(self):
        model = self._model()
        b = quantities.bill(model)
        bricks = next(L for L in b["groups"]["masonry"]
                      if L["item"] == "Facing bricks")
        # Perimeter 18 m x 2.4 m = 43.2 m2 gross, less the model's rule
        # openings; x60/m2, +5% waste. Bound it rather than chase the
        # rule-window areas: gross gives 2,592 + waste = 2,722 max.
        self.assertLess(bricks["quantity"], 43.2 * 60 * 1.05 + 1)
        self.assertGreater(bricks["quantity"], 30.0 * 60)
        self.assertIn("60/m2", bricks["basis"])

    def test_level_none_openings_repeat_per_storey(self):
        rooms = [M.Room("Living room", 0.0, 0.0, 4.0, 5.0, kind="room")]
        m1 = M.build(rooms, storeys=1, storey_height=2.7,
                     roof={"pitch_deg": 30.0, "kind": "gabled",
                           "overhang": 0.3, "max_span_m": 12.0})
        m2 = M.build([M.Room("Living room", 0.0, 0.0, 4.0, 5.0,
                             kind="room", storeys=2)], storeys=2,
                     storey_height=2.7,
                     roof={"pitch_deg": 30.0, "kind": "gabled",
                           "overhang": 0.3, "max_span_m": 12.0})
        n1, _, c1, _ = quantities._external(m1)
        n2, _, c2, _ = quantities._external(m2)
        # two storeys: roughly double the net wall and at least as many
        # opening repeats — never the single-storey figures
        self.assertGreater(n2, n1 * 1.7)
        self.assertGreaterEqual(c2, c1)

    def test_roof_tiles_from_sloped_area(self):
        model = self._model()
        b = quantities.bill(model)
        tiles = next(L for L in b["groups"]["roof"]
                     if L["item"].startswith("Roof covering"))
        area = model["roof"]["sloped_area_m2"]
        self.assertAlmostEqual(tiles["net_quantity"], area * 10.5,
                               delta=1.0)
        # switching covering changes the count by the coverage ratio
        b2 = quantities.bill(model, covering="plain_tile")
        tiles2 = next(L for L in b2["groups"]["roof"]
                      if L["item"].startswith("Roof covering"))
        self.assertAlmostEqual(tiles2["net_quantity"] / tiles["net_quantity"],
                               60.0 / 10.5, places=1)

    def test_services_lengths_follow_designs(self):
        model = self._model()
        heat = heatloss.design(model)
        elec = electrics.design(model, heat=heat)
        b = quantities.bill(model, heat=heat, elec=elec)
        cable = next(L for L in b["groups"]["services"]
                     if L["item"].startswith("2.5mm2"))
        self.assertAlmostEqual(
            cable["net_quantity"],
            elec["sockets_twin_total"] * quantities.CABLE_M_PER_SOCKET,
            delta=0.1)

    def test_pipeline_carries_the_bill(self):
        model = self._model()
        extra = M._with_buildability(model)
        M._absorb_buildability(model, extra)
        self.assertIn("quantities_bill", model)
        groups = model["quantities_bill"]["groups"]
        self.assertTrue(groups["masonry"] and groups["roof"]
                        and groups["finishes"])
        # sockets existed by the time the bill ran, so cable is non-zero
        cable = next(L for L in groups["services"]
                     if L["item"].startswith("2.5mm2"))
        self.assertGreater(cable["quantity"], 0)


if __name__ == "__main__":
    unittest.main()
