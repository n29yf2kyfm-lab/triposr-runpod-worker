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
