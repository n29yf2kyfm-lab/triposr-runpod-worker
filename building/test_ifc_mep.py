"""Tests for the SERVICES half of the IFC export.

Same discipline as test_ifc.py: parse the WRITTEN FILE back and count what
is actually in it. A federated model is the claim — architecture and first
fix in one IFC4 file — so these tests check that a contractor opening it
finds pipes, cables, radiators and systems, not just walls.
"""
import os
import tempfile
import unittest

import electrics
import heatloss
import mep
import model3d as M
import ventilation

try:
    import ifcopenshell
    HAVE_IFC = True
except ImportError:                              # pragma: no cover
    HAVE_IFC = False


def _serviced_model():
    rooms = [
        M.Room("Living room", 0.0, 0.0, 3.6, 4.6, kind="room", storeys=1),
        M.Room("Hall", 3.6, 0.0, 2.9, 4.6, kind="circulation", storeys=1),
        M.Room("Kitchen", 0.0, 4.6, 4.6, 2.6, kind="kitchen", storeys=1),
        M.Room("Utility", 4.6, 4.6, 1.9, 2.6, kind="wet", storeys=1),
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
    heat = heatloss.design(model)
    elec = electrics.design(model, heat=heat)
    vent = ventilation.design(model)
    model["heat"], model["elec"], model["vent"] = heat, elec, vent
    model["mep"] = mep.design(model, heat=heat, elec=elec, vent=vent)
    return model


@unittest.skipUnless(HAVE_IFC, "ifcopenshell not installed")
class TestIfcServices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = _serviced_model()
        cls.dir = tempfile.TemporaryDirectory()
        path = os.path.join(cls.dir.name, "m.ifc")
        M.write_ifc(cls.model, path)
        cls.f = ifcopenshell.open(path)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def _segments(self):
        return (self.f.by_type("IfcPipeSegment")
                + self.f.by_type("IfcCableSegment"))

    def test_the_file_carries_pipes_and_cables(self):
        self.assertGreater(len(self.f.by_type("IfcPipeSegment")), 10)
        self.assertGreater(len(self.f.by_type("IfcCableSegment")), 10)

    def test_no_orphan_elements(self):
        """A segment with no placement or no geometry is junk in somebody
        else's model, and it validates as a real object."""
        for el in self._segments():
            self.assertIsNotNone(el.ObjectPlacement, el)
            self.assertIsNotNone(el.Representation, el)

    def test_every_segment_sits_in_a_storey(self):
        contained = set()
        for rel in self.f.by_type("IfcRelContainedInSpatialStructure"):
            for o in rel.RelatedElements:
                contained.add(o.id())
        for el in self._segments():
            self.assertIn(el.id(), contained, el)

    def test_systems_are_grouped_and_typed(self):
        systems = {s.PredefinedType: s
                   for s in self.f.by_type("IfcDistributionSystem")}
        for want in ("HEATING", "ELECTRICAL", "DRAINAGE"):
            self.assertIn(want, systems)
        for s in systems.values():
            members = sum(len(r.RelatedObjects)
                          for r in self.f.by_type("IfcRelAssignsToGroup")
                          if r.RelatingGroup == s)
            self.assertGreater(members, 0, f"{s.Name} has no members")

    def test_terminals_are_real_ifc_objects(self):
        rads = self.f.by_type("IfcSpaceHeater")
        want = sum(1 for r in self.model["heat"]["rooms"] if r["radiator"])
        self.assertEqual(len(rads), want)
        self.assertEqual(len(self.f.by_type("IfcBoiler")), 1)
        self.assertEqual(len(self.f.by_type("IfcElectricDistributionBoard")),
                         1)
        self.assertGreater(len(self.f.by_type("IfcAirTerminal")), 0)
        self.assertGreater(len(self.f.by_type("IfcAlarm")), 0)

    def test_services_land_inside_the_building(self):
        ex = self.model["extent_m"]["x"]
        ey = self.model["extent_m"]["y"]
        for el in self._segments():
            x, y, z = el.ObjectPlacement.RelativePlacement.Location.Coordinates
            self.assertGreaterEqual(x, ex[0] - 0.5)
            self.assertLessEqual(x, ex[1] + 0.5)
            self.assertGreaterEqual(y, ey[0] - 0.5)
            self.assertLessEqual(y, ey[1] + 0.5)
            self.assertGreater(z, -1.5)

    def test_the_architecture_is_still_there(self):
        """Adding services must not cost the shell."""
        self.assertGreater(len(self.f.by_type("IfcWall")), 5)
        self.assertGreater(len(self.f.by_type("IfcSpace")), 5)
        self.assertGreater(len(self.f.by_type("IfcSlab")), 0)

    def test_a_model_without_services_still_exports(self):
        plain = _serviced_model()
        plain.pop("mep")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "plain.ifc")
            M.write_ifc(plain, p)
            g = ifcopenshell.open(p)
            self.assertEqual(len(g.by_type("IfcPipeSegment")), 0)
            self.assertGreater(len(g.by_type("IfcWall")), 5)


class TestRadiusLabels(unittest.TestCase):
    def test_pipe_sizes_parse_to_sane_radii(self):
        self.assertAlmostEqual(M._mep_radius_m("15mm copper"), 0.0075)
        self.assertAlmostEqual(M._mep_radius_m("110mm PVCu"), 0.055)
        # a flat twin-and-earth is not round; the radius is a drawing
        # convenience, small and constant
        self.assertAlmostEqual(M._mep_radius_m("2.5mm2 T&E"), 0.003)
        self.assertGreater(M._mep_radius_m("nonsense"), 0.0)


if __name__ == "__main__":
    unittest.main()
