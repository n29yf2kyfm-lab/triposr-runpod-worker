"""Tests for printable.py — a scale model that would actually print."""
import os
import struct
import tempfile
import unittest

import model3d as M
import printable


def _house(storeys=2):
    rooms = [M.Room("Living room", 0.0, 0.0, 4.0, 5.0, kind="room"),
             M.Room("Hall", 4.0, 0.0, 2.0, 5.0, kind="circulation")]
    if storeys > 1:
        rooms += [M.Room("Bedroom 1", 0.0, 0.0, 4.0, 5.0, kind="room",
                         base_level=1, storeys=1),
                  M.Room("Landing", 4.0, 0.0, 2.0, 5.0, kind="circulation",
                         base_level=1, storeys=1)]
    model = M.build(rooms, storeys=storeys, storey_height=2.7,
                    roof={"pitch_deg": 35.0, "kind": "gabled",
                          "overhang": 0.3, "max_span_m": 12.0})
    M.apply_facade_openings(model, [
        {"kind": "door", "along": 4.6, "width": 0.95, "height": 2.05,
         "sill": 0.0, "level": 0},
        {"kind": "window", "along": 1.0, "width": 1.8, "height": 1.35,
         "sill": 0.9, "level": 0},
    ], facade_y=0.0)
    return model


class TestPrintable(unittest.TestCase):
    def setUp(self):
        self.model = _house()

    def test_binary_stl_is_well_formed(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "m.stl")
            _, rep = printable.write_stl(self.model, p, scale_denom=50)
            raw = open(p, "rb").read()
            n = struct.unpack("<I", raw[80:84])[0]
            # 80-byte header + count + 50 bytes per triangle, exactly
            self.assertEqual(len(raw), 84 + n * 50)
            self.assertEqual(n, rep["triangles"])
            self.assertGreater(n, 100)

    def test_every_solid_is_closed(self):
        """Watertightness: each directed edge must have its reverse.

        Elements overlap, so this does not prove one manifold shell — it
        proves every element is individually closed, which is what a
        slicer needs to union them.
        """
        mesh, _ = printable.build(self.model, scale_denom=50)
        edges = {}
        for _, a, b, c in mesh.tris:
            k = lambda p: (round(p[0], 5), round(p[1], 5), round(p[2], 5))
            for u, v in ((a, b), (b, c), (c, a)):
                edges[(k(u), k(v))] = edges.get((k(u), k(v)), 0) + 1
        unmatched = [e for e in edges if (e[1], e[0]) not in edges]
        self.assertEqual(unmatched, [], f"{len(unmatched)} open edges")

    def test_scale_is_true_in_millimetres(self):
        _, rep = printable.build(self.model, scale_denom=100,
                                 base_plate=False)
        ex = self.model["extent_m"]
        rf = self.model["roof"]["footprint_m"]
        # the roof overhangs the walls, so the print's footprint is the
        # roof band, in mm at 1:100
        want_x = (max(ex["x"][1], rf["x"][1]) - min(ex["x"][0], rf["x"][0]))
        self.assertAlmostEqual(rep["size_mm"]["x"], want_x * 1000 / 100,
                               delta=0.5)
        want_z = self.model["roof"]["ridge_z_m"] + M.DEFAULT_SLAB_M
        self.assertAlmostEqual(rep["size_mm"]["z"], want_z * 1000 / 100,
                               delta=0.5)

    def test_thin_partitions_are_thickened_and_declared(self):
        # 100mm partitions print 1.0mm at 1:100 — under the 1.5mm floor
        _, at100 = printable.build(self.model, scale_denom=100)
        self.assertTrue(at100["thickened"])
        t = at100["thickened"][0]
        self.assertEqual(t["kind"], "partition")
        self.assertLess(t["as_designed_mm"], printable.MIN_WALL_MM)
        self.assertGreaterEqual(t["printed_mm"], printable.MIN_WALL_MM)
        # and the report must SAY the model is no longer dimensionally true
        self.assertTrue(any("thickened" in n for n in at100["notes"]))
        # at 1:50 the same wall is 2.0mm and nothing is touched
        _, at50 = printable.build(self.model, scale_denom=50)
        self.assertEqual(at50["thickened"], [])

    def test_upper_only_walls_are_declared_when_thickened(self):
        """A wall that only exists upstairs must still be reported.

        The report used to be gated on level == 0, so the partition of a
        set-back upper storey (base_level 1) was silently fattened: the
        model changed and the 'not dimensionally true' note never
        appeared. Ground floor here is one open room — its only thin
        walls are the two bedrooms' shared partition, upstairs only.
        """
        rooms = [M.Room("Living room", 0.0, 0.0, 6.0, 5.0, kind="room",
                        storeys=1),
                 M.Room("Bedroom 1", 0.0, 0.0, 3.0, 5.0, kind="room",
                        base_level=1, storeys=1),
                 M.Room("Bedroom 2", 3.0, 0.0, 3.0, 5.0, kind="room",
                        base_level=1, storeys=1)]
        model = M.build(rooms, storeys=2, storey_height=2.7)
        _, rep = printable.build(model, scale_denom=100)
        # 100mm partition at 1:100 prints 1.0mm and is lifted to 1.6mm
        # (four 0.4mm nozzle widths) — and it must SAY so.
        self.assertTrue(rep["thickened"], "upper-only wall not reported")
        for t in rep["thickened"]:
            self.assertEqual(t["kind"], "partition")
            self.assertAlmostEqual(t["as_designed_mm"], 1.0, places=2)
            self.assertEqual(t["printed_mm"], 1.6)
            self.assertEqual(
                model["walls"][t["wall"]].get("base_level"), 1,
                "the reported wall should be the upstairs partition")
        self.assertTrue(any("thickened" in n for n in rep["notes"]))

    def test_thickening_rounds_to_whole_nozzle_widths(self):
        _, rep = printable.build(self.model, scale_denom=100)
        for t in rep["thickened"]:
            n = t["printed_mm"] / printable.NOZZLE_MM
            self.assertAlmostEqual(n, round(n), places=6)

    def test_openings_are_cut_not_painted(self):
        """A facade with openings must produce more geometry than a blank
        one — the wall is split around the void."""
        blank = _house()
        for w in blank["walls"]:
            w["openings"] = []
        with_openings, _ = printable.build(self.model, scale_denom=50)
        without, _ = printable.build(blank, scale_denom=50)
        self.assertGreater(len(with_openings.tris), len(without.tris))

    def test_oversized_model_warns_about_the_bed(self):
        _, rep = printable.build(self.model, scale_denom=20)
        self.assertTrue(any("bed" in n for n in rep["notes"]))


if __name__ == "__main__":
    unittest.main()
