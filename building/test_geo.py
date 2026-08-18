"""Tests for geo.py — the model on the actual planet."""
import json
import math
import os
import tempfile
import unittest

import geo
import model3d as M

try:
    import geolibre                              # noqa: F401
    HAVE_GEOLIBRE = True
except ImportError:                              # pragma: no cover
    HAVE_GEOLIBRE = False

BHAM = (52.4862, -1.8904)


def _house(l_shape=False):
    rooms = [M.Room("Living room", 0.0, 0.0, 4.0, 5.0, kind="room"),
             M.Room("Hall", 4.0, 0.0, 2.0, 5.0, kind="circulation")]
    if l_shape:
        rooms.append(M.Room("Kitchen", 0.0, 5.0, 4.0, 3.0, kind="kitchen"))
    return M.build(rooms, storeys=2, storey_height=2.7,
                   roof={"pitch_deg": 35.0, "kind": "gabled",
                         "overhang": 0.3, "max_span_m": 12.0})


class TestAnchor(unittest.TestCase):
    def test_impossible_positions_are_refused(self):
        with self.assertRaises(ValueError):
            geo.Anchor(95.0, 0.0)
        with self.assertRaises(ValueError):
            geo.Anchor(52.0, 200.0)

    def test_bearing_wraps(self):
        self.assertAlmostEqual(geo.Anchor(*BHAM, bearing_deg=370).bearing_deg,
                               10.0)

    def test_the_anchor_records_where_it_came_from(self):
        a = geo.Anchor(*BHAM, source="phone GPS")
        d = a.as_dict()
        self.assertEqual(d["source"], "phone GPS")
        self.assertIn("absolute accuracy", d["note"])


class TestTransform(unittest.TestCase):
    def setUp(self):
        self.a = geo.Anchor(*BHAM, bearing_deg=20.0)

    def test_round_trip_is_exact_to_a_millimetre(self):
        for x, y in [(0, 0), (9.4, 7.2), (3.3, 5.1), (-2.0, 14.0)]:
            lon, lat = geo.local_to_wgs84(self.a, x, y)
            bx, by = geo.wgs84_to_local(self.a, lon, lat)
            self.assertAlmostEqual(bx, x, places=3)
            self.assertAlmostEqual(by, y, places=3)

    def test_the_origin_lands_on_the_anchor(self):
        lon, lat = geo.local_to_wgs84(self.a, 0, 0)
        self.assertAlmostEqual(lat, self.a.lat, places=9)
        self.assertAlmostEqual(lon, self.a.lon, places=9)

    def test_bearing_zero_sends_plan_north_to_true_north(self):
        a = geo.Anchor(*BHAM, bearing_deg=0.0)
        lon, lat = geo.local_to_wgs84(a, 0, 10.0)      # 10 m up the plan
        self.assertGreater(lat, a.lat)                  # went north
        self.assertAlmostEqual(lon, a.lon, places=9)    # and nowhere east

    def test_bearing_ninety_sends_plan_north_to_the_east(self):
        a = geo.Anchor(*BHAM, bearing_deg=90.0)
        lon, lat = geo.local_to_wgs84(a, 0, 10.0)
        self.assertGreater(lon, a.lon)                  # went east
        self.assertAlmostEqual(lat, a.lat, places=9)

    def test_ten_metres_north_is_ten_metres(self):
        a = geo.Anchor(*BHAM, bearing_deg=0.0)
        lon, lat = geo.local_to_wgs84(a, 0, 10.0)
        m_lat, _ = geo._m_per_deg(a.lat)
        self.assertAlmostEqual((lat - a.lat) * m_lat, 10.0, places=3)

    def test_rotation_preserves_distance(self):
        a0 = geo.Anchor(*BHAM, bearing_deg=0.0)
        a1 = geo.Anchor(*BHAM, bearing_deg=47.0)
        for anch in (a0, a1):
            lon, lat = geo.local_to_wgs84(anch, 6.0, 8.0)   # 10 m away
            x, y = geo.wgs84_to_local(anch, lon, lat)
            self.assertAlmostEqual(math.hypot(x, y), 10.0, places=3)


class TestFootprint(unittest.TestCase):
    def test_a_rectangle_traces_to_its_own_area(self):
        m = _house()
        ring, traced = geo.footprint_local(m)
        self.assertTrue(traced, "external walls did not chain into a ring")
        self.assertAlmostEqual(geo._area(ring), 6.0 * 5.0, delta=0.01)

    def test_an_l_shape_is_not_squared_off(self):
        """A location plan showing a rectangle over an L is a wrong
        drawing, not a simplified one."""
        m = _house(l_shape=True)
        ring, traced = geo.footprint_local(m)
        ex, ey = m["extent_m"]["x"], m["extent_m"]["y"]
        bbox = (ex[1] - ex[0]) * (ey[1] - ey[0])
        self.assertTrue(traced)
        self.assertLess(geo._area(ring), bbox - 1.0)
        self.assertAlmostEqual(geo._area(ring), 6.0 * 5.0 + 4.0 * 3.0,
                               delta=0.05)


class TestGeoJSON(unittest.TestCase):
    def setUp(self):
        self.m = _house()
        self.a = geo.Anchor(*BHAM, bearing_deg=20.0, source="test")
        self.g = geo.geojson(self.m, self.a, red_line_margin_m=6.0,
                             rooms=True)

    def test_it_is_a_valid_feature_collection(self):
        self.assertEqual(self.g["type"], "FeatureCollection")
        for f in self.g["features"]:
            self.assertEqual(f["type"], "Feature")
            self.assertIn(f["geometry"]["type"], ("Polygon", "LineString"))
            self.assertIn("layer", f["properties"])

    def test_rings_are_closed(self):
        for f in self.g["features"]:
            if f["geometry"]["type"] != "Polygon":
                continue
            ring = f["geometry"]["coordinates"][0]
            self.assertEqual(ring[0], ring[-1])

    def test_the_footprint_survives_the_trip_to_wgs84(self):
        """Area measured back off the geographic coordinates must match
        the model's own footprint."""
        f = next(x for x in self.g["features"]
                 if x["properties"]["layer"] == "building")
        back = [geo.wgs84_to_local(self.a, lon, lat)
                for lon, lat in f["geometry"]["coordinates"][0][:-1]]
        self.assertAlmostEqual(geo._area(back),
                               f["properties"]["footprint_m2"], delta=0.02)

    def test_the_red_line_contains_the_building(self):
        b = next(x for x in self.g["features"]
                 if x["properties"]["layer"] == "building")
        r = next(x for x in self.g["features"]
                 if x["properties"]["layer"] == "red line")
        self.assertGreater(r["properties"]["site_area_m2"],
                           b["properties"]["footprint_m2"])
        self.assertIn("title plan", r["properties"]["note"])

    def test_the_anchor_travels_with_the_data(self):
        self.assertEqual(self.g["properties"]["anchor"]["source"], "test")
        self.assertIn("4326", self.g["properties"]["crs"])

    def test_rooms_are_optional_and_carry_their_names(self):
        plain = geo.geojson(self.m, self.a)
        self.assertFalse([f for f in plain["features"]
                          if f["properties"]["layer"] == "room"])
        names = {f["properties"]["name"] for f in self.g["features"]
                 if f["properties"]["layer"] == "room"}
        self.assertIn("Living room", names)

    def test_it_writes_a_file_that_parses(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "site.geojson")
            geo.write_geojson(self.m, self.a, p, red_line_margin_m=6.0)
            with open(p) as fh:
                back = json.load(fh)
            self.assertEqual(back["type"], "FeatureCollection")


@unittest.skipUnless(HAVE_GEOLIBRE, "geolibre not installed")
class TestSiteMap(unittest.TestCase):
    def test_a_map_is_built_at_the_anchor(self):
        m = _house()
        a = geo.Anchor(*BHAM, source="test")
        mp = geo.site_map(m, a)
        self.assertAlmostEqual(mp.center[0], a.lon, places=6)
        self.assertAlmostEqual(mp.center[1], a.lat, places=6)

    def test_an_imagery_basemap_name_is_refused_with_a_reason(self):
        """GeoLibre carries five vector styles and no imagery; asking for
        a satellite basemap by name must say so rather than throw a bare
        library error."""
        m = _house()
        a = geo.Anchor(*BHAM)
        with self.assertRaises(ValueError) as cm:
            geo.site_map(m, a, basemap="Esri.WorldImagery")
        self.assertIn("imagery=True", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
