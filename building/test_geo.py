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

    def test_a_detached_annex_is_not_passed_off_as_traced(self):
        """Two buildings are two wall loops. The chain used to close the
        first loop and return it as THE footprint, traced=True — a 6x5
        main house plus a 3x3 detached annex reported 30 m2 as measured
        when 39 m2 stands on the plot. The honest answer is the extent
        rectangle (0..12 x 0..5 = 60 m2 here), flagged as a fallback."""
        rooms = [M.Room("Living room", 0.0, 0.0, 6.0, 5.0, kind="room"),
                 M.Room("Annex", 9.0, 0.0, 3.0, 3.0, kind="room")]
        m = M.build(rooms, storeys=1, storey_height=2.7,
                    roof={"pitch_deg": 35.0, "kind": "gabled",
                          "overhang": 0.3, "max_span_m": 12.0})
        ring, traced = geo.footprint_local(m)
        self.assertFalse(traced)
        self.assertAlmostEqual(geo._area(ring), 12.0 * 5.0, delta=0.01)
        f = geo.geojson(m, geo.Anchor(*BHAM))["features"][0]
        self.assertIn("single closed ring", f["properties"]["outline"])


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


class TestStaticMap(unittest.TestCase):
    """The location plan as an IMAGE.

    geolibre's to_html embeds the hosted app in an iframe, so on a worker
    or in a headless browser the map comes back blank. The tile maths and
    the scale statement are pure, so they are tested without a network;
    the fetch itself is exercised only when tiles are reachable.
    """

    def test_web_mercator_matches_the_slippy_map_definition(self):
        # At zoom 0 the whole world is one tile: (0,0) sits at the centre.
        x, y = geo._tile_xy(0.0, 0.0, 0)
        self.assertAlmostEqual(x, 0.5, places=9)
        self.assertAlmostEqual(y, 0.5, places=9)
        # Greenwich at the equator, zoom 1: the meridian is the seam.
        x, y = geo._tile_xy(0.0, 0.0, 1)
        self.assertAlmostEqual(x, 1.0, places=9)
        # Longitude increases eastward, y increases SOUTHWARD (screen order).
        xe, _ = geo._tile_xy(0.0, 10.0, 8)
        xw, _ = geo._tile_xy(0.0, -10.0, 8)
        self.assertGreater(xe, xw)
        _, yn = geo._tile_xy(50.0, 0.0, 8)
        _, ys = geo._tile_xy(40.0, 0.0, 8)
        self.assertLess(yn, ys)

    def test_a_known_tile_number(self):
        """Birmingham at zoom 12, worked longhand from the definition:

            n = 2^12 = 4096
            x = (-1.8904 + 180)/360 * 4096            = 2026.5
            tan(52.4862 deg) = 1.30274
            asinh(1.30274)   = 1.080219
            y = (1 - 1.080219/pi)/2 * 4096            = 1343.9

        so the tile is (2026, 1343). Checked against the arithmetic, not
        against whatever the function returns.
        """
        x, y = geo._tile_xy(BHAM[0], BHAM[1], 12)
        self.assertAlmostEqual(x, 2026.5, delta=0.1)
        self.assertAlmostEqual(y, 1343.9, delta=0.1)
        self.assertEqual((int(x), int(y)), (2026, 1343))

    def test_metres_per_pixel_is_stated_and_sane(self):
        """A plan whose scale is unstated is not a plan. At zoom 19 in
        Birmingham a pixel is about 0.2 m."""
        m_per_px = (156543.03392 * math.cos(math.radians(BHAM[0]))
                    / (2.0 ** 19))
        self.assertGreater(m_per_px, 0.15)
        self.assertLess(m_per_px, 0.25)

    def test_it_draws_without_imagery_and_says_the_tiles_are_missing(self):
        """imagery=False fetches nothing, so this runs offline — the
        drawing, the scale bar and the honesty note still have to work."""
        m = _house()
        a = geo.Anchor(*BHAM, bearing_deg=20.0, source="test")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "site.png")
            path, info = geo.static_map(m, a, p, zoom=19, span=0,
                                        imagery=False)
            self.assertTrue(os.path.getsize(path) > 1000)
            self.assertEqual(info["tiles"], 0)
            self.assertEqual(info["size_px"], [256, 256])
            self.assertAlmostEqual(info["m_per_px"], 0.181, delta=0.02)

    def test_the_building_lands_inside_the_frame(self):
        """The footprint must project into the image, not off it — the
        whole point of centring on the anchor."""
        from PIL import Image
        m = _house()
        a = geo.Anchor(*BHAM, source="test")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "site.png")
            geo.static_map(m, a, p, zoom=19, span=1, imagery=False)
            img = Image.open(p).convert("RGB")
            w, h = img.size
            # the building is drawn in amber; find any strongly amber pixel
            hits = [(x, y) for x in range(0, w, 3) for y in range(0, h - 40, 3)
                    if img.getpixel((x, y))[0] > 180
                    and img.getpixel((x, y))[1] > 140
                    and img.getpixel((x, y))[2] < 90]
            self.assertTrue(hits, "no building outline drawn in the frame")


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


class TestInteractiveMapIsActuallyOffline(unittest.TestCase):
    """The whole point of the viewer is that it works with no signal.

    Every test here stubs the tile fetch, so the suite never touches the
    network — and the assertions are about what ends up IN the file,
    which is the property that decides whether it works down a hole with
    no reception.
    """

    @staticmethod
    def _read(path):
        with open(path) as fh:
            return fh.read()

    # A 256x256 JPEG, so the encoder path is real without a download.
    def _tile_bytes(self):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (256, 256), (30, 60, 30)).save(buf, "JPEG")
        return buf.getvalue()

    def _build(self, zooms=(17, 18, 19), span=1, missing=()):
        model = _house()
        model["name"] = "Test dwelling"
        anchor = geo.Anchor(*BHAM, bearing_deg=20.0, source="test fixture")
        blob = self._tile_bytes()

        def fake(anchor_, zooms_, span_, timeout_):
            tiles = {}
            for z in zooms_:
                cx, cy = geo._tile_xy(anchor_.lat, anchor_.lon, z)
                x0, y0 = int(cx) - span_, int(cy) - span_
                for i in range(2 * span_ + 1):
                    for j in range(2 * span_ + 1):
                        tiles[f"{z}/{x0 + i}/{y0 + j}"] = blob
            for k in missing:
                tiles.pop(k, None)
            return tiles, list(missing)

        real = geo._fetch_tiles
        geo._fetch_tiles = fake
        try:
            path = os.path.join(tempfile.mkdtemp(), "map.html")
            return geo.interactive_map(model, anchor, path, zooms=zooms,
                                       span=span), model, anchor
        finally:
            geo._fetch_tiles = real

    def test_nothing_in_the_page_points_at_the_network(self):
        (path, info), _, _ = self._build()
        body = self._read(path)
        self.assertTrue(info["offline"])
        # Every image source must be a data: URI. One http src and the
        # page is a grey box on a site with no signal.
        import re
        srcs = re.findall(r'src\s*=\s*["\']([^"\']+)', body)
        for s in srcs:
            self.assertTrue(s.startswith("data:"), f"external src: {s}")
        # No script/style/font pulled from anywhere either — and not
        # via <link href> or css url() fetches, the two channels the
        # first version of this test forgot to close.
        self.assertNotIn("<script src", body)
        self.assertNotIn("@import", body)
        self.assertNotIn("<link", body)
        import re as _re
        for u in _re.findall(r"url\(\s*[\"\']?([^)\"\']+)", body):
            self.assertFalse(u.startswith(("http", "//")),
                             f"css fetch: {u}")
        # The imagery host may appear ONLY as attribution text, never as
        # a URL the page would fetch.
        self.assertNotIn("https://server.arcgisonline.com", body)

    def test_every_tile_is_embedded_not_referenced(self):
        (path, info), _, _ = self._build(zooms=(18, 19), span=1)
        self.assertEqual(info["tiles"], 2 * 9)
        self.assertEqual(info["tiles"], info["tiles_expected"])
        body = self._read(path)
        self.assertEqual(body.count("data:image/jpeg;base64,"), 18)

    def test_the_drawing_travels_with_the_map(self):
        (path, _), model, anchor = self._build()
        body = self._read(path)
        # The footprint the model measured is in the page, georeferenced.
        data = geo.geojson(model, anchor, red_line_margin_m=6.0, rooms=True)
        lon, lat = data["features"][0]["geometry"]["coordinates"][0][0]
        self.assertIn(f"{round(lon, 6)}"[:8], body)
        for layer in ("building", "red line"):
            self.assertIn(layer, body)

    def test_missing_tiles_are_reported_not_hidden(self):
        cx, cy = geo._tile_xy(BHAM[0], BHAM[1], 19)
        gone = f"19/{int(cx) - 1}/{int(cy) - 1}"
        (path, info), _, _ = self._build(missing=(gone,))
        self.assertIn(gone, info["missing"])
        self.assertLess(info["tiles"], info["tiles_expected"])
        # The note must describe what the viewer actually draws: missing
        # tiles are filled, blurred, from a shipped lower zoom — "dark
        # squares" was only true before the parent-tile fallback existed.
        self.assertIn("lower-zoom", info["note"])

    def test_a_map_with_no_imagery_at_all_is_refused(self):
        """A blank page is worse than an error: it looks like a map that
        found nothing there, rather than a fetch that failed."""
        model = _house()
        anchor = geo.Anchor(*BHAM)
        real = geo._fetch_tiles
        geo._fetch_tiles = lambda *a, **k: ({}, ["19/1/1"])
        try:
            with self.assertRaises(RuntimeError) as cm:
                geo.interactive_map(model, anchor,
                                    os.path.join(tempfile.mkdtemp(), "m.html"))
            self.assertIn("blank page", str(cm.exception))
        finally:
            geo._fetch_tiles = real

    def test_the_anchor_provenance_survives_into_the_page(self):
        """static_map prints it; the viewer must too. A map that has lost
        the caveat about its own position is the dangerous kind."""
        (path, _), _, anchor = self._build()
        self.assertIn(anchor.source, self._read(path))

    def test_a_hostile_name_cannot_break_out_of_the_script_block(self):
        """model['name'] is job input and lands inside an inline
        <script>. json.dumps does not escape '</script>', and the HTML
        parser ends the element at the first one it sees regardless of
        JS string context — truncating the viewer and running whatever
        the name says next. The page must contain no literal '</script>'
        except the genuine closer, and no un-escaped '<' from the data."""
        model = _house()
        model["name"] = "Plot 7</script><script>alert(1)</script>"
        anchor = geo.Anchor(*BHAM, source="x</script><b>y")
        blob = self._tile_bytes()
        real = geo._fetch_tiles
        geo._fetch_tiles = lambda a, z, sp, t, **k: (
            {f"{zz}/1/1": blob for zz in z}, [])
        try:
            path = os.path.join(tempfile.mkdtemp(), "m.html")
            geo.interactive_map(model, anchor, path, zooms=(19,), span=0)
        finally:
            geo._fetch_tiles = real
        body = self._read(path)
        # Exactly the legitimate closers — none contributed by the data.
        self.assertEqual(body.lower().count("</script>"),
                         body.lower().count("<script>")
                         + body.lower().count("<script "))
        self.assertIn("\\u003c/script", body)   # the payload, escaped
        self.assertNotIn("<script>alert", body)

    def test_a_tile_order_too_big_for_a_phone_is_refused(self):
        model = _house()
        anchor = geo.Anchor(*BHAM)
        with self.assertRaises(ValueError) as cm:
            geo.interactive_map(model, anchor, "/tmp/never.html",
                                zooms=(15, 16, 17, 18, 19), span=4)
        self.assertIn("cap is 300", str(cm.exception))
        with self.assertRaises(ValueError):
            geo.interactive_map(model, anchor, "/tmp/never.html",
                                zooms=(2,), span=1)


if __name__ == "__main__":
    unittest.main()
