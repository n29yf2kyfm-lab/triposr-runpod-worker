"""Tests for quantities.py — the take-off the builder orders from.

The case that matters most is the DEFAULT one: a plain plate repeated
over two storeys leaves every wall with storeys=None, which in model3d
means "stands on every storey". Reading that as one storey halved the
brick order on every ordinary multi-storey job, and the only prior
multi-storey test used explicit storeys=2 so it never saw the default.
"""
import unittest

import model3d as M
import quantities as Q

ROOF = {"pitch_deg": 30.0, "kind": "gabled", "overhang": 0.3,
        "max_span_m": 12.0}


def _plate():
    return [M.Room("Living room", 0.0, 0.0, 4.0, 5.0, kind="room"),
            M.Room("Hall", 4.0, 0.0, 2.0, 5.0, kind="circulation")]


class TestExternalDefaultStoreys(unittest.TestCase):
    """Walls carrying storeys=None — the untested default path."""

    def test_the_default_two_storey_wall_is_counted_twice(self):
        m1 = M.build(_plate(), storeys=1, storey_height=2.7, roof=ROOF)
        m2 = M.build(_plate(), storeys=2, storey_height=2.7, roof=ROOF)
        # Precondition: this really is the default path.
        self.assertEqual({w.get("storeys") for w in m2["walls"]
                          if w.get("external")}, {None})
        n1, _, c1, _ = Q._external(m1)
        n2, _, c2, _ = Q._external(m2)
        # Two storeys of wall, not one. (Not exactly 2x: the ground
        # floor carries the entrance door, the upper floor does not.)
        self.assertGreater(n2, n1 * 1.9)
        # level=None openings repeat on every storey the wall stands.
        self.assertGreater(c2, c1)

    def test_explicit_wall_storeys_are_clamped_to_the_model(self):
        model = {"storeys": 2, "walls": [
            {"external": True, "length_m": 10.0, "height_m": 2.4,
             "storeys": 5, "base_level": 0, "openings": []}]}
        net, _, _, perim = Q._external(model)
        self.assertAlmostEqual(net, 10.0 * 2.4 * 2, places=6)
        self.assertAlmostEqual(perim, 10.0, places=6)

    def test_a_wall_based_above_the_roof_counts_nothing(self):
        model = {"storeys": 2, "walls": [
            {"external": True, "length_m": 10.0, "height_m": 2.4,
             "storeys": None, "base_level": 3, "openings": []}]}
        net, _, _, perim = Q._external(model)
        self.assertEqual(net, 0.0)
        self.assertEqual(perim, 0.0)      # not at dpc either

    def test_upper_only_wall_counts_its_own_storeys_and_no_dpc(self):
        model = {"storeys": 2, "walls": [
            {"external": True, "length_m": 6.0, "height_m": 2.4,
             "storeys": None, "base_level": 1, "openings": []}]}
        net, _, _, perim = Q._external(model)
        self.assertAlmostEqual(net, 6.0 * 2.4, places=6)
        self.assertEqual(perim, 0.0)


class TestBrickworkOverAnExtension(unittest.TestCase):
    """A wall can be plastered downstairs and brick upstairs.

    Over a single-storey rear extension, the first-floor wall behind it
    faces open sky. The plan probe cannot see that — it finds a room on
    both sides in PLAN — so model3d exports shared_storeys and the mesh
    and heat loss read it. The take-off did not, and a real 3 m rear
    extension on this project's own 94 Parkfield Road model came back
    63 bricks instead of about a thousand.
    """

    def _house_with_rear_extension(self):
        rooms = [
            M.Room("Hall", 0.0, 0.0, 1.92, 7.0, kind="circulation",
                   storeys=1),
            M.Room("Living room", 1.92, 0.0, 3.2, 4.0, kind="room",
                   storeys=1),
            M.Room("Dining room", 1.92, 4.0, 3.2, 3.0, kind="room",
                   storeys=1),
            # runs 3 m PAST the first floor, which stops at y = 9.88
            M.Room("Kitchen/diner", 0.0, 7.0, 5.12, 5.88, kind="kitchen",
                   storeys=1),
            M.Room("Landing", 0.0, 0.0, 1.92, 7.0, kind="circulation",
                   storeys=1, base_level=1),
            M.Room("Bedroom 1", 1.92, 0.0, 3.2, 4.0, kind="room",
                   storeys=1, base_level=1),
            M.Room("Bedroom 2", 1.92, 4.0, 3.2, 3.0, kind="room",
                   storeys=1, base_level=1),
            M.Room("Bathroom", 0.0, 7.0, 5.12, 2.88, kind="wet",
                   storeys=1, base_level=1),
        ]
        return M.build(rooms, storeys=2, storey_height=2.65, roof=ROOF)

    def test_the_wall_above_the_extension_is_counted_as_brickwork(self):
        m = self._house_with_rear_extension()
        wall = next(w for w in m["walls"]
                    if abs(w["start"][1] - 9.88) < 1e-6
                    and abs(w["end"][1] - 9.88) < 1e-6)
        # Precondition: the plan probe calls it internal. Only
        # shared_storeys records that it stands open above the extension.
        self.assertFalse(wall["external"])
        self.assertEqual(wall["shared_storeys"], 1)
        self.assertEqual(wall["base_level"], 1)

        net, _, _, _ = Q._external(m)
        # What the OLD rule gave: external-flagged walls only.
        old = 0.0
        storeys = m["storeys"]
        for w in m["walls"]:
            if not w.get("external"):
                continue
            n = len(Q._levels_of(w, storeys))
            gross = w["length_m"] * w["height_m"] * n
            op = sum(o["width"] * o["height"]
                     * (n if o.get("level") is None else 1)
                     for o in w.get("openings", []))
            old += max(0.0, gross - op)
        # The difference IS that wall: 5.12 x 2.4 less its openings.
        opens = sum(o["width"] * o["height"] for o in wall["openings"])
        expect = 5.12 * 2.4 - opens
        self.assertGreater(expect, 8.0)          # a real wall, not a sliver
        self.assertAlmostEqual(net - old, expect, delta=0.05)

    def test_it_is_worth_hundreds_of_bricks(self):
        m = self._house_with_rear_extension()
        wall = next(w for w in m["walls"]
                    if abs(w["start"][1] - 9.88) < 1e-6
                    and abs(w["end"][1] - 9.88) < 1e-6)
        opens = sum(o["width"] * o["height"] for o in wall["openings"])
        bricks_for_it = (5.12 * 2.4 - opens) * Q.BRICKS_PER_M2
        self.assertGreater(bricks_for_it, 500,
                           "the wall this fix adds should be worth "
                           "hundreds of bricks, or the test proves little")

    def test_the_ground_floor_half_stays_out_of_the_brick_order(self):
        """Below the extension's ceiling that same line is a partition
        with kitchen on both sides. It must NOT be brickwork: the fix
        counts the levels at or above shared_storeys, not the wall."""
        m = self._house_with_rear_extension()
        wall = next(w for w in m["walls"]
                    if abs(w["start"][1] - 9.88) < 1e-6
                    and abs(w["end"][1] - 9.88) < 1e-6)
        # it stands on ONE level (the first floor) and that is the only
        # level counted — the ground floor line is a different wall
        self.assertEqual(len(list(Q._levels_of(wall, m["storeys"]))), 1)
        self.assertEqual(list(Q._levels_of(wall, m["storeys"])), [1])


class TestBillNotes(unittest.TestCase):
    def test_the_bill_does_not_claim_a_pricing_path_that_does_not_exist(self):
        """The shipped note said 'takeoff.py prices this bill', but
        takeoff.py only prices a roof-mode takeoff dict — nothing in the
        repo prices the masonry, finishes or services groups. The note
        must say what is actually true: the bill is measured, and those
        trades are unpriced until a rate-card pricing path exists."""
        model = M.build(_plate(), storeys=1, storey_height=2.7, roof=ROOF)
        notes = " ".join(Q.bill(model)["notes"])
        self.assertNotIn("prices this bill", notes)
        self.assertIn("unpriced", notes)
        self.assertIn("roof-mode takeoffs only", notes)


class TestBrickSanityAnchor(unittest.TestCase):
    def test_a_three_bed_detached_lands_in_the_trade_band(self):
        """The module's own stated anchor: a 3-bed detached takes
        7,000-10,000 facing bricks. Before the storeys=None fix this
        computed roughly half that."""
        rooms = [M.Room("Living room", 0.0, 0.0, 5.4, 7.2, kind="room"),
                 M.Room("Kitchen diner", 5.4, 0.0, 4.0, 7.2,
                        kind="kitchen")]
        model = M.build(rooms, storeys=2, storey_height=2.7, roof=ROOF)
        b = Q.bill(model)
        bricks = next(L for L in b["groups"]["masonry"]
                      if L["item"] == "Facing bricks")
        self.assertGreater(bricks["quantity"], 7000)
        self.assertLess(bricks["quantity"], 10000)


if __name__ == "__main__":
    unittest.main()
