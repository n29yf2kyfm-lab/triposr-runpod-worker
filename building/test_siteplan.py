"""Tests for siteplan.py — the site as a live GeoLibre project.

The solar tests are the ones that matter: a shadow drawn wrong is an
argument lost with a neighbour, so they check against textbook solar
geometry rather than against whatever the code happens to produce.
"""
import math
import os
import tempfile
import unittest

import geo
import model3d as M
import siteplan as S

try:
    import geolibre                              # noqa: F401
    HAVE_GEOLIBRE = True
except ImportError:                              # pragma: no cover
    HAVE_GEOLIBRE = False

LAT, LON = 52.4862, -1.8904                      # Birmingham


def _house():
    rooms = [M.Room("Living room", 0.0, 0.0, 4.0, 5.0, kind="room"),
             M.Room("Hall", 4.0, 0.0, 2.0, 5.0, kind="circulation")]
    return M.build(rooms, storeys=2, storey_height=2.7,
                   roof={"pitch_deg": 35.0, "kind": "gabled",
                         "overhang": 0.3, "max_span_m": 12.0})


class TestSolar(unittest.TestCase):
    """Noon altitude at a solstice is 90 - |lat -+ 23.44|, exactly."""

    def test_winter_solstice_noon_altitude(self):
        alt, _ = S.sun_position(LAT, 355, 12.0)
        self.assertAlmostEqual(math.degrees(alt), 90 - LAT - 23.44, delta=0.3)

    def test_summer_solstice_noon_altitude(self):
        alt, _ = S.sun_position(LAT, 172, 12.0)
        self.assertAlmostEqual(math.degrees(alt), 90 - LAT + 23.44, delta=0.3)

    def test_the_noon_sun_is_due_south(self):
        _, az = S.sun_position(LAT, 172, 12.0)
        self.assertAlmostEqual(math.degrees(az), 180.0, delta=1.0)

    def test_morning_sun_is_east_and_evening_west(self):
        _, morning = S.sun_position(LAT, 172, 8.0)
        _, evening = S.sun_position(LAT, 172, 16.0)
        self.assertLess(math.degrees(morning), 180.0)
        self.assertGreater(math.degrees(evening), 180.0)

    def test_the_sun_sets_in_a_birmingham_december(self):
        alt, _ = S.sun_position(LAT, 355, 17.0)
        self.assertLess(alt, 0.0)


class TestShadow(unittest.TestCase):
    def setUp(self):
        self.m = _house()
        self.a = geo.Anchor(LAT, LON, bearing_deg=0.0, source="test")

    def test_a_winter_shadow_is_long_and_a_summer_one_short(self):
        _, w = S.shadow_local(self.m, self.a, 355, 12.0)
        _, s = S.shadow_local(self.m, self.a, 172, 12.0)
        self.assertGreater(w["reach_m"], s["reach_m"] * 4)

    def test_reach_is_height_over_tangent_of_altitude(self):
        _, info = S.shadow_local(self.m, self.a, 355, 12.0)
        alt = math.radians(info["altitude_deg"])
        self.assertAlmostEqual(info["reach_m"],
                               info["height_m"] / math.tan(alt), delta=0.05)

    def test_a_shadow_below_the_horizon_is_refused_not_drawn(self):
        """A shadow 400 m long is not a drawing, it is a warning."""
        ring, info = S.shadow_local(self.m, self.a, 355, 17.0)
        self.assertEqual(ring, [])
        self.assertIn("note", info)

    def test_the_noon_shadow_falls_north(self):
        ring, _ = S.shadow_local(self.m, self.a, 355, 12.0)
        ey = self.m["extent_m"]["y"][1]
        self.assertGreater(max(y for _, y in ring), ey + 10.0)

    def test_the_shadow_contains_the_building(self):
        ring, _ = S.shadow_local(self.m, self.a, 355, 12.0)
        fp, _ = geo.footprint_local(self.m)
        self.assertGreater(geo._area(ring), geo._area(fp))


class TestPermittedDevelopment(unittest.TestCase):
    def setUp(self):
        self.m = _house()

    def test_detached_gets_four_metres_and_others_three(self):
        _, d = S.permitted_development_local(self.m, detached=True)
        _, o = S.permitted_development_local(self.m, detached=False)
        self.assertEqual(d["depth_m"], 4.0)
        self.assertEqual(o["depth_m"], 3.0)

    def test_prior_approval_doubles_the_reach(self):
        _, d = S.permitted_development_local(self.m, detached=True,
                                             larger=True)
        self.assertEqual(d["depth_m"], 8.0)
        self.assertIn("prior-approval", d["note"])

    def test_two_storey_is_three_metres_and_names_the_boundary_rule(self):
        _, t = S.permitted_development_local(self.m, two_storey=True)
        self.assertEqual(t["depth_m"], 3.0)
        self.assertIn("7 m", t["note"])

    def test_it_never_calls_itself_permission(self):
        _, d = S.permitted_development_local(self.m)
        self.assertIn("NOT PERMISSION", d["warning"])
        self.assertIn("Article 4", d["warning"])

    def test_the_envelope_sits_beyond_the_rear_wall(self):
        ring, info = S.permitted_development_local(self.m, detached=True)
        ey = self.m["extent_m"]["y"][1]
        self.assertAlmostEqual(min(y for _, y in ring), ey, places=6)
        self.assertAlmostEqual(max(y for _, y in ring), ey + info["depth_m"],
                               places=6)


class TestLayers(unittest.TestCase):
    def setUp(self):
        self.m = _house()
        self.a = geo.Anchor(LAT, LON, source="test")

    def test_the_building_is_drawn_last_so_it_reads_on_top(self):
        names = [n for n, _, _ in S.layers(self.m, self.a)]
        self.assertEqual(names[-1], "Building")

    def test_optional_layers_are_off_by_default(self):
        names = [n for n, _, _ in S.layers(self.m, self.a)]
        for absent in ("Rooms", "Services", "Permitted development envelope"):
            self.assertNotIn(absent, names)

    def test_asking_for_them_gets_them(self):
        names = [n for n, _, _ in S.layers(
            self.m, self.a, rooms=True, pd={"detached": True},
            shadow={"day_of_year": 355, "solar_hour": 12.0})]
        self.assertIn("Rooms", names)
        self.assertIn("Permitted development envelope", names)
        self.assertTrue(any(n.startswith("Shadow") for n in names))

    def test_every_layer_is_valid_geojson_with_a_style(self):
        for name, data, style in S.layers(self.m, self.a, rooms=True,
                                          pd={"detached": True}):
            self.assertEqual(data["type"], "FeatureCollection")
            self.assertTrue(data["features"], name)
            self.assertIn("line_color", style)
            for f in data["features"]:
                self.assertIn(f["geometry"]["type"], ("Polygon", "LineString"))

    def test_services_ride_onto_the_map_when_the_model_has_them(self):
        self.m["mep"] = {"runs": [
            {"system": "heating", "service": "flow", "size": "15mm copper",
             "length_m": 4.2, "points": [[0, 0, 0], [4, 0, 0], [4, 3, 0]]}]}
        names = [n for n, _, _ in S.layers(self.m, self.a, services=True)]
        self.assertIn("Services", names)


@unittest.skipUnless(HAVE_GEOLIBRE, "geolibre not installed")
class TestProject(unittest.TestCase):
    def test_a_written_project_reloads_with_its_layers(self):
        from geolibre import authoring as gla
        m, a = _house(), geo.Anchor(LAT, LON, source="test")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "site.json")
            path, summary = S.write_project(
                m, a, p, name="Test site", rooms=True,
                pd={"detached": True})
            self.assertTrue(os.path.getsize(path) > 500)
            back = gla.load_project(path)
            names = [layer["name"] for layer in gla.layers_of(back)]
            self.assertIn("Building", names)
            self.assertIn("Red line", names)
            self.assertIn("Aerial imagery", names)
            self.assertEqual(back["name"], "Test site")

    def test_the_view_lands_on_the_anchor(self):
        m, a = _house(), geo.Anchor(LAT, LON, source="test")
        proj = S.project(m, a, zoom=18)
        view = proj["mapView"]
        self.assertAlmostEqual(view["center"][0], LON, places=4)
        self.assertAlmostEqual(view["center"][1], LAT, places=4)
        self.assertAlmostEqual(view["zoom"], 18.0, places=3)


class TestPluginParity(unittest.TestCase):
    """The GeoLibre plugin reimplements this maths in JavaScript.

    Two implementations of the same geometry is a promise to keep them
    equal, so this runs the plugin under node and compares. If node is
    absent the test skips rather than pretending to have checked.
    """

    def test_javascript_agrees_with_python(self):
        import json
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        here = os.path.dirname(os.path.abspath(__file__))
        entry = os.path.join(here, "web", "geolibre-plugin", "dist",
                             "index.js")
        if not os.path.exists(entry):
            self.skipTest("plugin bundle not present")

        m = _house()
        a = geo.Anchor(LAT, LON, bearing_deg=20.0, source="test")
        with tempfile.TemporaryDirectory() as d:
            mp = os.path.join(d, "model.json")
            with open(mp, "w") as fh:
                json.dump(m, fh)
            script = (
                "import fs from 'node:fs';"
                f"const m = await import({entry!r});"
                f"const model = JSON.parse(fs.readFileSync({mp!r},'utf8'));"
                "const L = m.buildLayers(model,"
                f"{{lon:{LON},lat:{LAT},bearing:20}},"
                "{redLineMargin:6,pd:true,pdDetached:true,shadow:true,"
                "day:355,hour:12});"
                "const s = m.sunPosition(%r,355,12);" % LAT +
                "console.log(JSON.stringify({"
                "footprint:L.building.features[0].properties.footprint_m2,"
                "reach:L.info.reach, alt:s.alt*180/Math.PI,"
                "pd:L.info.pdDepth}));"
            )
            out = subprocess.run(
                [node, "--input-type=module", "-e", script],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(out.returncode, 0, out.stderr[:400])
            js = json.loads(out.stdout.strip().splitlines()[-1])

        fp, _ = geo.footprint_local(m)
        self.assertAlmostEqual(js["footprint"], geo._area(fp), delta=0.02)

        _, info = S.shadow_local(m, a, 355, 12.0)
        self.assertAlmostEqual(js["reach"], info["reach_m"], delta=0.05)
        self.assertAlmostEqual(js["alt"], info["altitude_deg"], delta=0.05)

        _, pd = S.permitted_development_local(m, detached=True)
        self.assertEqual(js["pd"], pd["depth_m"])


if __name__ == "__main__":
    unittest.main()
