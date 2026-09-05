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


def _house(l_shape=False):
    rooms = [M.Room("Living room", 0.0, 0.0, 4.0, 5.0, kind="room"),
             M.Room("Hall", 4.0, 0.0, 2.0, 5.0, kind="circulation")]
    if l_shape:
        # Kitchen wing over x 0-4 with its rear wall at y=8; the hall's
        # rear wall stays at y=5 — the recessed-wing case the PD
        # envelope must respect.
        rooms.append(M.Room("Kitchen", 0.0, 5.0, 4.0, 3.0, kind="kitchen"))
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

    def test_a_recessed_wing_keeps_its_own_rear_wall(self):
        """Hand-worked on the L-plan: kitchen wing (x 0-4) rear wall at
        y=8, hall (x 4-6) rear wall at y=5, detached depth 4 m. Each
        wing gets 4 m beyond ITS OWN rear wall — 8..12 and 5..9 — so
        the envelope area is 4x4 + 2x4 = 24 m2. The old extent-box line
        gave the hall a strip out to y=12, 7 m beyond its actual rear
        wall, where the GPDO grants 4."""
        m = _house(l_shape=True)
        ring, info = S.permitted_development_local(m, detached=True)
        self.assertEqual(set(ring),
                         {(0.0, 8.0), (4.0, 8.0), (4.0, 5.0), (6.0, 5.0),
                          (6.0, 9.0), (4.0, 9.0), (4.0, 12.0), (0.0, 12.0)})
        self.assertAlmostEqual(geo._area(ring), 24.0, places=6)
        self.assertLessEqual(
            max(y for x, y in ring if 4.0 < x <= 6.0), 9.0)
        self.assertIn("traced rear wall", info["rear_line"])

    def test_an_untraceable_footprint_says_so_on_the_envelope(self):
        """When the walls do not chain into one ring the envelope falls
        back to the extent rear line — and must say so rather than
        looking as authoritative as a traced one."""
        m = _house()
        m["walls"] = [w for w in m["walls"]
                      if not w.get("external")]      # nothing to trace
        ring, info = S.permitted_development_local(m, detached=True)
        ey = m["extent_m"]["y"][1]
        self.assertAlmostEqual(min(y for _, y in ring), ey, places=6)
        self.assertIn("could not be traced", info["rear_line"])


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

    def test_a_refused_shadow_still_appears_and_says_why(self):
        """Refuse rather than silently mislead: at 17:00 on day 355 the
        Birmingham sun is below the 3-degree cutoff, so shadow_local
        refuses. The refusal used to vanish here — no layer, no note —
        which read as 'casts no shadow at that hour'. Now it travels as
        an empty, named layer carrying shadow_local's note."""
        got = S.layers(self.m, self.a,
                       shadow={"day_of_year": 355, "solar_hour": 17.0})
        shadows = [(n, fc) for n, fc, _ in got if n.startswith("Shadow")]
        self.assertEqual(len(shadows), 1)
        name, fc = shadows[0]
        self.assertIn("refused", name)
        self.assertEqual(fc["features"], [])
        self.assertIn("below 3 degrees", fc["properties"]["note"])
        text = S.describe(self.m, self.a,
                          shadow={"day_of_year": 355, "solar_hour": 17.0})
        self.assertIn("no usable shadow", text)

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

    @staticmethod
    def _node():
        import shutil
        return shutil.which("node")

    def _run_node(self, script):
        import subprocess
        node = self._node()
        out = subprocess.run(
            [node, "--input-type=module", "-e", script],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[:800])
        import json
        return json.loads(out.stdout.strip().splitlines()[-1])

    def _entry(self):
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(here, "web", "geolibre-plugin", "dist",
                            "index.js")

    def test_javascript_agrees_with_python(self):
        """Parity on the L-SHAPED plan, where the two implementations
        can actually disagree: on a rectangle the traced ring and the
        bbox fallback have the same area, so a broken JS chaining loop
        would pass unseen; and reach/altitude are direction-blind, so a
        sign flip in theta/dx/dy would draw the shadow on the sunward
        side with the old four scalars still green."""
        import json

        if not self._node():
            self.skipTest("node not installed")
        entry = self._entry()
        if not os.path.exists(entry):
            self.skipTest("plugin bundle not present")

        m = _house(l_shape=True)
        a = geo.Anchor(LAT, LON, bearing_deg=20.0, source="test")
        with tempfile.TemporaryDirectory() as d:
            mp = os.path.join(d, "model.json")
            with open(mp, "w") as fh:
                json.dump(m, fh)
            script = (
                "import fs from 'node:fs';"
                f"const m = await import({entry!r});"
                f"const model = JSON.parse(fs.readFileSync({mp!r},'utf8'));"
                f"const anchor = {{lon:{LON},lat:{LAT},bearing:20}};"
                "const fpr = m.footprintRing(model);"
                # no redLineMargin on purpose: the exported API must
                # default it, not hand back NaN corners
                "const L = m.buildLayers(model,anchor,"
                "{pd:true,pdDetached:true,shadow:true,day:355,hour:12});"
                "const s = m.sunPosition(%r,355,12);" % LAT +
                "const pt = m.localToWgs84(anchor,3.3,5.1);"
                "console.log(JSON.stringify({"
                "ring:fpr.ring, traced:fpr.traced,"
                "footprint:L.building.features[0].properties.footprint_m2,"
                "reach:L.info.reach, alt:s.alt*180/Math.PI,"
                "az:L.info.azimuth, dx:L.info.dx, dy:L.info.dy,"
                "pd:L.info.pdDepth,"
                "pdCoords:L.pd.features[0].geometry.coordinates[0],"
                "redCoords:L.red.features[0].geometry.coordinates[0],"
                "pt:pt}));"
            )
            js = self._run_node(script)

        # the traced footprint ring, vertex for vertex
        fp, traced = geo.footprint_local(m)
        self.assertTrue(traced)
        self.assertTrue(js["traced"])
        self.assertEqual([(float(x), float(y)) for x, y in js["ring"]],
                         list(fp))
        self.assertAlmostEqual(js["footprint"], geo._area(fp), delta=0.02)

        # sun position and the direction the shadow is cast along
        alt, az = S.sun_position(LAT, 355, 12.0)
        _, info = S.shadow_local(m, a, 355, 12.0)
        self.assertAlmostEqual(js["reach"], info["reach_m"], delta=0.05)
        self.assertAlmostEqual(js["alt"], info["altitude_deg"], delta=0.05)
        self.assertAlmostEqual(js["az"], math.degrees(az), delta=0.01)
        height = info["height_m"]
        reach = height / math.tan(alt)
        theta = az - math.radians(a.bearing_deg)
        self.assertAlmostEqual(js["dx"], -reach * math.sin(theta),
                               delta=1e-6)
        self.assertAlmostEqual(js["dy"], -reach * math.cos(theta),
                               delta=1e-6)
        # hand-worked signs: noon sun due south casts the shadow north;
        # a plan bearing 20 deg east of north tips it slightly west in
        # the plan's frame, so dy > 0 and dx < 0
        self.assertGreater(js["dy"], 0.0)
        self.assertLess(js["dx"], 0.0)

        # the PD envelope ring, on the recessed-wing plan
        pd_ring, pd = S.permitted_development_local(m, detached=True)
        self.assertEqual(js["pd"], pd["depth_m"])
        want = [list(geo.local_to_wgs84(a, x, y)) for x, y in pd_ring]
        want.append(want[0])
        self.assertEqual(len(js["pdCoords"]), len(want))
        for got, exp in zip(js["pdCoords"], want):
            self.assertAlmostEqual(got[0], exp[0], places=9)
            self.assertAlmostEqual(got[1], exp[1], places=9)

        # the tangent-plane transform itself, and the defaulted red line
        lon, lat = geo.local_to_wgs84(a, 3.3, 5.1)
        self.assertAlmostEqual(js["pt"][0], lon, places=9)
        self.assertAlmostEqual(js["pt"][1], lat, places=9)
        bx, by = geo.wgs84_to_local(a, js["pt"][0], js["pt"][1])
        self.assertAlmostEqual(bx, 3.3, places=3)
        self.assertAlmostEqual(by, 5.1, places=3)
        ex, ey = m["extent_m"]["x"], m["extent_m"]["y"]
        corner = geo.local_to_wgs84(a, ex[0] - 6.0, ey[0] - 6.0)
        for c in js["redCoords"]:
            self.assertIsNotNone(c[0])          # NaN serializes as null
            self.assertIsNotNone(c[1])
        self.assertAlmostEqual(js["redCoords"][0][0], corner[0], places=9)
        self.assertAlmostEqual(js["redCoords"][0][1], corner[1], places=9)

    def test_a_redraw_clears_its_own_stale_layers(self):
        """Slide from noon to 17:00 on day 355: the sun drops below the
        cutoff, buildLayers returns no shadow — and the noon shadow must
        LEAVE the map, not linger under a 'sun too low' caption. Runs
        draw() under node against a stub host that records layer calls."""
        import json

        if not self._node():
            self.skipTest("node not installed")
        entry = self._entry()
        if not os.path.exists(entry):
            self.skipTest("plugin bundle not present")

        m = _house()
        with tempfile.TemporaryDirectory() as d:
            mp = os.path.join(d, "model.json")
            with open(mp, "w") as fh:
                json.dump(m, fh)
            script = (
                "import fs from 'node:fs';"
                "const fake = () => ({ append(){}, });"
                "globalThis.window = {};"
                "globalThis.document = {"
                "  createElement: () => fake(),"
                "  createTextNode: () => ({}),"
                "};"
                "const calls = [];"
                "const app = {"
                "  addGeoJsonLayer: (n) => calls.push('add:' + n),"
                "  removeGeoJsonLayer: (n) => calls.push('rm:' + n),"
                "  getMap: () => null,"
                "  registerFloatingPanel: ({render}) => { render(fake()); },"
                "};"
                f"const mod = await import({entry!r});"
                "const plugin = mod.default;"
                "plugin.activate(app);"
                "const st = plugin._state;"
                f"st.model = JSON.parse(fs.readFileSync({mp!r},'utf8'));"
                f"st.anchor = {{lon:{LON},lat:{LAT},bearing:0}};"
                "st.opts.day = 355; st.opts.hour = 12;"
                "calls.length = 0; st.draw();"
                "const noon = calls.slice();"
                "st.opts.hour = 17;"
                "calls.length = 0; st.draw();"
                "const dusk = calls.slice();"
                "console.log(JSON.stringify({noon, dusk}));"
            )
            js = self._run_node(script)

        # at noon the shadow is drawn — after clearing, so removals of
        # every plugin layer precede any add
        self.assertIn("add:Shadow", js["noon"])
        first_add = min(i for i, c in enumerate(js["noon"])
                        if c.startswith("add:"))
        for name in ("Shadow", "PD envelope", "Red line", "Building"):
            self.assertIn(f"rm:{name}", js["noon"][:first_add])
        # at 17:00 the sun is below the cutoff: the stale shadow is
        # removed and no new one is added, while the building remains
        self.assertIn("rm:Shadow", js["dusk"])
        self.assertNotIn("add:Shadow", js["dusk"])
        self.assertIn("add:Building", js["dusk"])


if __name__ == "__main__":
    unittest.main()
