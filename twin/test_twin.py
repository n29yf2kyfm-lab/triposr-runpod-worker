"""Stage 1 tests. Offline by default; live tests are opt-in and marked.

The split matters. Unit tests must run in CI with no network and no
volunteer endpoint being hammered, so providers are driven through fake
sessions that return recorded payload shapes. The LIVE tests
(TWIN_LIVE=1) hit the real services and are what proves the adapters
match reality rather than my idea of it — both were run for the Stage 1
report.

What is deliberately tested hardest: the things that would let a wrong
number reach a builder. Geodesic area against a hand-computed figure,
the selection rule refusing the neighbour, and Missing never being
mistakable for a value.
"""
import json
import math
import os
import unittest

from twin import geodesy, licences
from twin.provenance import (CLASS_DERIVED, CLASS_VERIFIED, Missing,
                             Provenance, Sourced)
from twin.providers import base
from twin.providers.nominatim import NominatimProvider
from twin.providers.overpass import OverpassProvider
from twin.providers.registry import Registry
from twin.providers.uk import UKProvider

LIVE = os.environ.get("TWIN_LIVE") == "1"


class FakeResponse:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, payload, status=200):
        self.payload, self.status, self.calls = payload, status, []

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return FakeResponse(self.payload, self.status)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return FakeResponse(self.payload, self.status)


class NoCache:
    """Cache that never hits, so tests exercise the fetch path."""
    def get(self, k):
        return None

    def put(self, *a, **kw):
        return True

    def throttle(self, *a, **kw):
        pass


# ---------------------------------------------------------------- geodesy
class TestGeodesy(unittest.TestCase):
    def test_area_is_geodesic_not_planar(self):
        """The bug this exists to prevent: shoelace on lon/lat
        over-measures east-west by 1/cos(latitude). At Birmingham that
        is 64% too big on a square — an invented extension every time."""
        lat, lon = 52.4856, -1.8476
        # A 20 m x 20 m square, built from true metre offsets.
        f = geodesy.LocalFrame(lat, lon)
        ring = [list(f.to_lonlat(x, y)) for x, y in
                [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)]]
        area = geodesy.geodesic_area(ring)
        self.assertAlmostEqual(area, 400.0, delta=0.5)
        # And prove the naive version really is wrong, so this test is
        # guarding a live hazard rather than restating the implementation.
        naive = 0.0
        for i in range(len(ring) - 1):
            naive += (ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1])
        naive = abs(naive) / 2 * (111320.0 ** 2)
        self.assertGreater(abs(naive - 400.0), 100.0)

    def test_area_at_the_equator_and_the_arctic_agree_in_metres(self):
        """Same physical square, two latitudes: the whole point of doing
        it geodesically is that the answer does not depend on where."""
        for lat in (0.0, 52.0, 71.0):
            f = geodesy.LocalFrame(lat, 10.0)
            ring = [list(f.to_lonlat(x, y)) for x, y in
                    [(0, 0), (30, 0), (30, 30), (0, 30), (0, 0)]]
            self.assertAlmostEqual(geodesy.geodesic_area(ring), 900.0,
                                   delta=2.0, msg=f"at {lat}N")

    def test_holes_are_subtracted(self):
        f = geodesy.LocalFrame(52.0, 0.0)
        outer = [list(f.to_lonlat(x, y)) for x, y in
                 [(0, 0), (40, 0), (40, 40), (0, 40), (0, 0)]]
        hole = [list(f.to_lonlat(x, y)) for x, y in
                [(10, 10), (20, 10), (20, 20), (10, 20), (10, 10)]]
        g = {"type": "Polygon", "coordinates": [outer, hole]}
        self.assertAlmostEqual(geodesy.polygon_area(g), 1600 - 100, delta=2)

    def test_perimeter_of_a_known_rectangle(self):
        f = geodesy.LocalFrame(52.4856, -1.8476)
        ring = [list(f.to_lonlat(x, y)) for x, y in
                [(0, 0), (5.12, 0), (5.12, 9.88), (0, 9.88), (0, 0)]]
        g = {"type": "Polygon", "coordinates": [ring]}
        self.assertAlmostEqual(geodesy.perimeter(g), 2 * (5.12 + 9.88),
                               delta=0.02)

    def test_centroid_is_area_weighted_not_vertex_mean(self):
        """An edge traced with many nodes must not drag the centre."""
        ring = [[0, 0], [10, 0], [10, 1], [10, 2], [10, 3], [10, 4],
                [10, 5], [10, 6], [10, 7], [10, 8], [10, 9], [10, 10],
                [0, 10], [0, 0]]
        c = geodesy.centroid({"type": "Polygon", "coordinates": [ring]})
        self.assertAlmostEqual(c[0], 5.0, delta=0.25)
        vertex_mean = sum(p[0] for p in ring[:-1]) / (len(ring) - 1)
        self.assertGreater(vertex_mean, 7.0)     # the wrong answer

    def test_point_in_polygon_honours_holes(self):
        g = {"type": "Polygon", "coordinates": [
            [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
            [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]]}
        self.assertTrue(geodesy.point_in_polygon(1, 1, g))
        self.assertFalse(geodesy.point_in_polygon(5, 5, g))   # in the hole
        self.assertFalse(geodesy.point_in_polygon(20, 5, g))

    def test_local_frame_round_trips_to_sub_millimetre(self):
        f = geodesy.LocalFrame(52.4856, -1.8476)
        for x, y in [(0, 0), (5.12, 9.88), (-30, 42.5), (250, -180)]:
            lon, lat = f.to_lonlat(x, y)
            bx, by = f.to_m(lon, lat)
            self.assertAlmostEqual(bx, x, delta=1e-6)
            self.assertAlmostEqual(by, y, delta=1e-6)


# ------------------------------------------------------------ provenance
class TestProvenance(unittest.TestCase):
    def test_missing_is_falsy_and_never_looks_like_a_value(self):
        m = Missing("no coverage", asked=("uk-gov-open",))
        self.assertFalse(m)
        self.assertFalse(m.available)
        d = m.as_dict()
        self.assertEqual(d["status"], "DATA NOT AVAILABLE")
        self.assertNotIn("value", d)

    def test_a_value_must_declare_how_it_came_to_exist(self):
        p = Provenance("x", "y")
        with self.assertRaises(ValueError):
            Sourced(1, p, classification="probably")

    def test_derivation_keeps_the_chain_back_to_the_measurement(self):
        lidar = Provenance("uk-gov-open", "EA LIDAR", licence="ogl-3.0",
                           accuracy_m=1.0)
        pitch = lidar.derive("RANSAC plane fit", confidence=0.8)
        self.assertEqual(pitch.derived_from, lidar)
        self.assertEqual(len(pitch.chain()), 2)
        self.assertIn("RANSAC", pitch.chain()[0])
        # The licence must not be lost on the way through a computation.
        self.assertEqual(pitch.licence, "ogl-3.0")

    def test_sourced_serialises_with_its_provenance(self):
        s = Sourced(42, Provenance("p", "d"), CLASS_DERIVED)
        d = s.as_dict()
        self.assertTrue(d["available"])
        self.assertEqual(d["classification"], "derived")
        self.assertIn("chain", d["provenance"])


# -------------------------------------------------------------- licences
class TestLicences(unittest.TestCase):
    def test_esri_imagery_is_refused_for_export_and_commercial_use(self):
        """The Stage 0 finding, pinned: the offline map bakes tiles into
        a file it hands to a customer, and Esri's terms do not grant
        that. The registry must say so rather than shrug."""
        refusals = licences.check("esri-world-imagery", licences.USE_EXPORT,
                                  licences.USE_COMMERCIAL, raises=False)
        self.assertEqual(len(refusals), 2)
        with self.assertRaises(licences.LicenceError):
            licences.check("esri-world-imagery", licences.USE_EXPORT)

    def test_open_government_licence_permits_what_we_do(self):
        self.assertEqual(licences.check("ogl-3.0", licences.USE_EXPORT,
                                        licences.USE_COMMERCIAL,
                                        licences.USE_CACHE, raises=False), [])

    def test_an_unregistered_source_cannot_be_used_at_all(self):
        with self.assertRaises(licences.LicenceError):
            licences.get("some-tiles-i-found")

    def test_attribution_is_deduplicated_and_present(self):
        lines = licences.attributions(["odbl-1.0", "nominatim-policy",
                                       "ogl-3.0"])
        self.assertEqual(len([l for l in lines if "OpenStreetMap" in l]), 1)
        self.assertTrue(any("Open Government" in l for l in lines))


# -------------------------------------------------------------- providers
class TestNominatim(unittest.TestCase):
    PAYLOAD = [{
        "lat": "52.4856", "lon": "-1.8476", "display_name": "B8 3AY, Birmingham",
        "osm_type": "way", "osm_id": 122819341, "addresstype": "building",
        "importance": 0.4, "boundingbox": ["52.4855", "52.4857",
                                           "-1.8477", "-1.8475"],
        "address": {"country_code": "gb", "postcode": "B8 3AY"},
        "geojson": {"type": "Polygon", "coordinates": [[[0, 0]]]}}]

    def _p(self, payload=None, status=200):
        return NominatimProvider(cache=NoCache(),
                                 session=FakeSession(
                                     self.PAYLOAD if payload is None
                                     else payload, status))

    def test_a_hit_carries_provider_dataset_and_osm_id(self):
        r = self._p().geocode("B8 3AY")
        self.assertTrue(r.available)
        self.assertEqual(r.provenance.source_dataset, "openstreetmap")
        self.assertEqual(r.provenance.source_identifier, "way/122819341")
        self.assertEqual(r.provenance.licence, "nominatim-policy")

    def test_accuracy_reflects_what_kind_of_place_matched(self):
        """A building hit and a city hit must not claim the same
        precision — the map zooms on this number."""
        b = self._p().geocode("x").value[0]["accuracy_m"]
        city = dict(self.PAYLOAD[0], addresstype="city",
                    boundingbox=["52.4", "52.6", "-1.95", "-1.75"])
        c = self._p([city]).geocode("x").value[0]["accuracy_m"]
        self.assertLess(b, 10.0)
        self.assertGreater(c, 1000.0)

    def test_no_match_is_missing_with_advice_not_an_empty_list(self):
        r = self._p([]).geocode("qqqzzz")
        self.assertFalse(r)
        self.assertIn("no match", r.reason)
        self.assertTrue(r.detail)

    def test_a_dead_endpoint_becomes_missing_not_an_exception(self):
        r = self._p(status=503).geocode("anything")
        self.assertFalse(r)
        self.assertIn("failed to reach", r.reason)

    def test_an_empty_query_never_leaves_the_process(self):
        p = self._p()
        self.assertFalse(p.geocode("   "))
        self.assertEqual(p.session.calls, [])


class TestOverpass(unittest.TestCase):
    PAYLOAD = {"elements": [{
        "type": "way", "id": 122819341,
        "tags": {"building": "house", "building:levels": "2",
                 "addr:housenumber": "94"},
        "geometry": [{"lat": 52.4855, "lon": -1.8477},
                     {"lat": 52.4855, "lon": -1.8475},
                     {"lat": 52.4857, "lon": -1.8475},
                     {"lat": 52.4857, "lon": -1.8477}]}]}

    def _p(self, payload=None):
        return OverpassProvider(cache=NoCache(),
                                session=FakeSession(payload or self.PAYLOAD))

    def test_a_way_becomes_a_closed_geojson_polygon(self):
        r = self._p().buildings(-1.848, 52.485, -1.847, 52.486)
        self.assertTrue(r.available)
        f = r.value["features"][0]
        ring = f["geometry"]["coordinates"][0]
        self.assertEqual(ring[0], ring[-1], "ring must close")
        self.assertEqual(f["id"], "way/122819341")

    def test_osm_height_tags_travel_and_absent_ones_stay_absent(self):
        f = self._p().buildings(-1.848, 52.485, -1.847, 52.486
                                ).value["features"][0]
        self.assertEqual(f["properties"]["levels"], "2")
        # No height tag in the fixture: it must be None, never a default.
        self.assertIsNone(f["properties"]["height_m"])

    def test_an_unmapped_area_says_so_and_offers_the_alternative(self):
        r = self._p({"elements": []}).buildings(-1.848, 52.485, -1.847, 52.486)
        self.assertFalse(r)
        self.assertIn("no buildings mapped", r.reason)
        self.assertIn("trace the footprint yourself", r.detail)

    def test_a_city_sized_bbox_is_refused_before_it_is_sent(self):
        p = self._p()
        r = p.buildings(-2.0, 52.0, -1.0, 53.0)
        self.assertFalse(r)
        self.assertIn("too large", r.reason)
        self.assertEqual(p.session.calls, [], "must not hit the endpoint")

    def test_a_bbox_off_the_earth_is_refused(self):
        self.assertFalse(self._p().buildings(-200, 0, 200, 10))

    def test_every_mirror_failing_is_missing_not_a_crash(self):
        class Dead:
            def post(self, *a, **kw):
                raise OSError("connection reset")
        p = OverpassProvider(cache=NoCache(), session=Dead())
        r = p.buildings(-1.848, 52.485, -1.847, 52.486)
        self.assertFalse(r)
        self.assertIn("failed to reach", r.reason)


class TestUKProvider(unittest.TestCase):
    def test_it_declines_anything_that_is_not_a_uk_postcode(self):
        p = UKProvider(cache=NoCache(), session=FakeSession({}))
        for q in ("Eiffel Tower", "1600 Pennsylvania Ave", "12345"):
            r = p.geocode(q)
            self.assertFalse(r, q)
            self.assertIn("not a UK postcode", r.reason)
        self.assertEqual(p.session.calls, [])

    def test_a_postcode_centroid_says_it_is_not_a_house(self):
        payload = {"result": {"postcode": "B8 3AY", "latitude": 52.4856,
                              "longitude": -1.8476, "country": "England",
                              "admin_district": "Birmingham"}}
        p = UKProvider(cache=NoCache(), session=FakeSession(payload))
        r = p.geocode("B8 3AY")
        self.assertTrue(r.available)
        hit = r.value[0]
        self.assertEqual(hit["accuracy_m"], 100.0)
        self.assertIn("centroid", hit["note"])
        self.assertIn("select the building", hit["note"])

    def test_a_dead_postcode_is_distinguished_from_a_broken_server(self):
        p = UKProvider(cache=NoCache(), session=FakeSession({}, status=404))
        r = p.geocode("B8 3AY")
        self.assertFalse(r)
        self.assertIn("not a live UK postcode", r.reason)


class TestRegistry(unittest.TestCase):
    def test_with_no_country_hint_the_country_provider_is_still_asked(self):
        """The routing bug found in build: filtering to global providers
        when country is None meant a UK postcode never reached the UK
        adapter — on the commonest query the product has."""
        r = Registry(providers=[UKProvider(cache=NoCache(),
                                           session=FakeSession({})),
                                NominatimProvider(cache=NoCache(),
                                                  session=FakeSession([]))])
        names = [p.name for p in r.for_country(None)]
        self.assertIn("uk-gov-open", names)
        self.assertLess(names.index("uk-gov-open"), names.index("nominatim"))

    def test_when_everyone_declines_the_answer_names_everyone_asked(self):
        r = Registry(providers=[UKProvider(cache=NoCache(),
                                           session=FakeSession({})),
                                NominatimProvider(cache=NoCache(),
                                                  session=FakeSession([]))])
        res = r.geocode("qqqq zzzz")
        self.assertFalse(res)
        self.assertEqual(set(res.asked), {"uk-gov-open", "nominatim"})

    def test_a_provider_that_explodes_does_not_take_the_page_down(self):
        class Bomb(base.Provider):
            name = "bomb"
            countries = ("*",)

            def geocode(self, *a, **kw):
                raise RuntimeError("boom")

        r = Registry(providers=[Bomb(),
                                NominatimProvider(
                                    cache=NoCache(),
                                    session=FakeSession(
                                        TestNominatim.PAYLOAD))])
        res = r.geocode("B8 3AY")
        self.assertTrue(res.available, "the healthy provider must still win")

    def test_the_capability_matrix_covers_every_layer_with_a_reason(self):
        r = Registry(providers=[UKProvider(cache=NoCache()),
                                NominatimProvider(cache=NoCache()),
                                OverpassProvider(cache=NoCache())])
        caps = r.capabilities("GB")["layers"]
        self.assertEqual(set(caps), set(base.LAYERS))
        for layer, c in caps.items():
            self.assertIn(c["level"], (base.CAP_NONE, base.CAP_RESTRICTED,
                                       base.CAP_LIMITED, base.CAP_AVAILABLE))
            self.assertTrue(c["note"], f"{layer} has no explanation")
        # The honest headline claims for the UK.
        self.assertEqual(caps["building"]["level"], base.CAP_AVAILABLE)
        self.assertEqual(caps["elevation"]["level"], base.CAP_AVAILABLE)
        self.assertEqual(caps["utilities"]["level"], base.CAP_RESTRICTED)
        self.assertEqual(caps["parcel"]["level"], base.CAP_RESTRICTED)


# --------------------------------------------------------- property engine
class TestPropertySelection(unittest.TestCase):
    def _fc(self):
        # Two adjacent houses, 10 m apart — the semi problem.
        f = geodesy.LocalFrame(52.4856, -1.8476)

        def sq(x0, y0, w, d, name):
            ring = [list(f.to_lonlat(x, y)) for x, y in
                    [(x0, y0), (x0 + w, y0), (x0 + w, y0 + d),
                     (x0, y0 + d), (x0, y0)]]
            return {"type": "Feature", "id": name,
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {"osm_id": name}}
        return f, {"type": "FeatureCollection",
                   "features": [sq(0, 0, 6, 10, "mine"),
                                sq(6, 0, 6, 10, "neighbour")]}

    def test_selection_takes_the_polygon_that_contains_the_tap(self):
        from twin import property as prop
        f, fc = self._fc()
        prov = Provenance("overpass", "openstreetmap")

        class R:
            def buildings(self, *a, **kw):
                return Sourced(fc, prov, CLASS_VERIFIED)

        # A point clearly inside "mine".
        lon, lat = f.to_lonlat(3, 5)
        got = prop.select_building(lat, lon, R())
        self.assertTrue(got.available)
        self.assertEqual(got.value["id"], "mine")

    def test_a_tap_in_the_garden_selects_NOTHING_not_the_nearest_house(self):
        """The worst failure this product can have is showing somebody
        their neighbour's house. Nearest-match would do exactly that."""
        from twin import property as prop
        f, fc = self._fc()
        prov = Provenance("overpass", "openstreetmap")

        class R:
            def buildings(self, *a, **kw):
                return Sourced(fc, prov, CLASS_VERIFIED)

        lon, lat = f.to_lonlat(3, 25)      # 15 m behind both houses
        got = prop.select_building(lat, lon, R())
        self.assertFalse(got)
        self.assertIn("no mapped building", got.reason)
        self.assertIn("trace the outline", got.detail)

    def test_measurement_matches_the_metres_the_shape_was_built_from(self):
        from twin import property as prop
        f, fc = self._fc()
        m = prop.measure(fc["features"][0])
        self.assertAlmostEqual(m["footprint_area_m2"], 60.0, delta=0.5)
        self.assertAlmostEqual(m["perimeter_m"], 32.0, delta=0.1)
        self.assertEqual(m["vertices"], 4)

    def test_the_search_box_is_grid_snapped_so_taps_share_a_cache_entry(self):
        """Measured: an unsnapped box gave every tap a unique cache key
        and a 51-second live Overpass query. Snapped, the second tap on
        the same street is 0.5 s. The cell must NOT be derived from the
        query point, or no two taps ever share one."""
        from twin import property as prop
        a = prop._box(52.484342, -1.8500538)
        b = prop._box(52.484350, -1.8500600)          # ~1 m away
        self.assertEqual(a, b, "nearby taps must share a cell")
        far = prop._box(52.4860, -1.8476)             # ~200 m away
        self.assertNotEqual(a, far, "distant taps must not share a cell")
        # And the cell must still be big enough to contain a dwelling
        # plus its neighbours, or selection fails at a cell edge.
        f = geodesy.LocalFrame(52.484, -1.850)
        self.assertGreater((a[2] - a[0]) * f.m_lon, 200.0)
        self.assertGreater((a[3] - a[1]) * f.m_lat, 200.0)

    def test_the_grid_is_stable_across_the_whole_world(self):
        from twin import property as prop
        for lat, lon in [(0.0, 0.0), (-33.87, 151.21), (60.17, 24.94),
                         (52.48, -1.85), (-45.0, -70.0)]:
            a = prop._box(lat, lon)
            b = prop._box(lat + 1e-6, lon + 1e-6)
            self.assertEqual(a, b, f"unstable at {lat},{lon}")
            self.assertLess(a[0], lon, f"box must contain the point {lat},{lon}")
            self.assertGreater(a[2], lon)
            self.assertLess(a[1], lat)
            self.assertGreater(a[3], lat)

    def test_elevation_is_deferred_by_default_not_silently_dropped(self):
        """The LIDAR read is slow enough that bundling it made the whole
        endpoint hang. Deferred, it must still be an explicit Missing
        with a reason — not an absent key the UI renders as blank."""
        from twin import property as prop
        prov = Provenance("overpass", "openstreetmap")
        _, fc = self._fc()

        class R:
            def buildings(self, *a, **kw):
                return Sourced(fc, prov, CLASS_VERIFIED)
            def reverse(self, *a, **kw):
                return Missing("no address")
            def parcel(self, *a, **kw):
                return Missing("no parcel")
            def elevation(self, *a, **kw):
                raise AssertionError("must NOT be called by default")
            def capabilities(self, *a, **kw):
                return {"country": None, "layers": {}}

        out = prop.property_at(52.4856, -1.8476, R())
        self.assertFalse(out["elevation"]["available"])
        self.assertIn("fetched separately", out["elevation"]["detail"])

    def test_storeys_absent_from_osm_are_missing_not_two(self):
        from twin import property as prop
        self.assertIsNone(prop._levels_from_tags({"levels": None,
                                                  "height_m": None}))
        self.assertEqual(prop._levels_from_tags({"levels": "2"}),
                         {"levels": 2.0})
        self.assertEqual(prop._levels_from_tags({"height_m": "8.5 m"}),
                         {"height_m": 8.5})


# ------------------------------------------------------------------- api
class TestAPI(unittest.TestCase):
    def setUp(self):
        from twin import api
        api.app.config["TESTING"] = True
        self.c = api.app.test_client()

    def test_health_and_capabilities_are_served(self):
        self.assertTrue(self.c.get("/api/health").get_json()["ok"])
        caps = self.c.get("/api/capabilities?country=GB").get_json()
        self.assertEqual(caps["country"], "GB")
        self.assertIn("building", caps["layers"])

    def test_bad_coordinates_are_refused_with_a_reason(self):
        r = self.c.get("/api/reverse?lat=999&lon=0")
        self.assertEqual(r.status_code, 400)
        self.assertIn("between", r.get_json()["reason"])
        self.assertEqual(self.c.get("/api/property?lat=abc&lon=0").status_code,
                         400)

    def test_an_inverted_bbox_is_refused(self):
        r = self.c.get("/api/buildings?west=1&south=1&east=0&north=0")
        self.assertEqual(r.status_code, 400)

    def test_measure_is_server_side_and_geodesic(self):
        f = geodesy.LocalFrame(52.4856, -1.8476)
        ring = [list(f.to_lonlat(x, y)) for x, y in
                [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]]
        r = self.c.post("/api/measure", json={
            "geometry": {"type": "Polygon", "coordinates": [ring]}})
        self.assertAlmostEqual(r.get_json()["area_m2"], 100.0, delta=0.5)

    def test_measure_rejects_junk(self):
        self.assertEqual(self.c.post("/api/measure", json={}).status_code, 400)

    def test_the_basemap_endpoint_reports_the_licence_refusal(self):
        body = self.c.get("/api/basemap").get_json()
        esri = [s for s in body["sources"]
                if s["licence"] == "esri-world-imagery"][0]
        self.assertFalse(esri["usable_for_this_product"])
        self.assertTrue(esri["refusals"])

    def test_static_paths_cannot_escape_the_web_directory(self):
        """The property under test is that source never leaves, not which
        4xx says so — asserting an exact code made the test fail when the
        refusal got stricter, which is the wrong way round."""
        for path in ("/../api.py", "/..%2fapi.py", "/web/../api.py",
                     "/....//api.py"):
            r = self.c.get(path)
            self.assertGreaterEqual(r.status_code, 400, path)
            self.assertNotIn(b"import", r.data or b"", path)

    def test_a_content_security_policy_forbids_third_party_code(self):
        csp = self.c.get("/api/health").headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("connect-src 'self'", csp)


# ------------------------------------------------- model & commands
class TestModel(unittest.TestCase):
    def _feature(self, w=6.0, d=10.0, rot_deg=20.0, **props):
        """A rectangle of known size, rotated, as a GeoJSON feature."""
        f = geodesy.LocalFrame(52.4856, -1.8476)
        a = math.radians(rot_deg)
        ring = []
        for x, y in [(0, 0), (w, 0), (w, d), (0, d), (0, 0)]:
            ex = x * math.cos(a) - y * math.sin(a)
            ny = x * math.sin(a) + y * math.cos(a)
            ring.append(list(f.to_lonlat(ex, ny)))
        return {"type": "Feature", "id": "way/1",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": dict({"osm_id": "way/1"}, **props)}

    def test_the_fitted_rectangle_recovers_the_true_size_and_angle(self):
        """An axis-aligned bbox on a rotated house is 25% too big; the
        minimum-area rectangle must recover what is actually there."""
        from twin import model
        bld = model.from_footprint(self._feature(6.0, 10.0, 20.0))
        blk = bld.blocks[0]
        self.assertAlmostEqual(blk.width, 6.0, delta=0.05)
        self.assertAlmostEqual(blk.depth, 10.0, delta=0.05)
        self.assertAlmostEqual(blk.area(), 60.0, delta=0.6)

    def test_the_local_frame_round_trips_through_lon_lat(self):
        from twin import model
        bld = model.from_footprint(self._feature())
        for x, y in [(0, 0), (3, 7), (-2.5, 12.0)]:
            lon, lat = bld.to_lonlat(x, y)
            bx, by = bld.from_lonlat(lon, lat)
            self.assertAlmostEqual(bx, x, delta=1e-3)
            self.assertAlmostEqual(by, y, delta=1e-3)

    def test_storeys_come_from_the_osm_tag_when_there_is_one(self):
        from twin import model
        bld = model.from_footprint(self._feature(levels="3"))
        self.assertEqual(bld.blocks[0].storeys, 3)
        self.assertEqual(bld.blocks[0].classification, "verified")

    def test_storeys_are_derived_from_lidar_when_there_is_no_tag(self):
        from twin import model
        bld = model.from_footprint(self._feature(),
                                   lidar={"height_above_ground_m": 5.4})
        self.assertEqual(bld.blocks[0].storeys, 2)
        self.assertEqual(bld.blocks[0].classification, "derived")
        self.assertIn("LIDAR", bld.blocks[0].note)

    def test_with_neither_tag_nor_lidar_the_guess_is_flagged_loudly(self):
        """The one thing this must never do is default quietly to two."""
        from twin import model
        bld = model.from_footprint(self._feature())
        self.assertEqual(bld.blocks[0].classification, "estimated")
        self.assertIn("must be corrected", bld.blocks[0].note)
        self.assertTrue(any("corrected" in n for n in bld.notes))

    def test_a_non_rectangular_building_says_so(self):
        from twin import model
        f = geodesy.LocalFrame(52.4856, -1.8476)
        # An L-plan: the fitted rectangle is much bigger than the truth.
        pts = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 12), (0, 12), (0, 0)]
        ring = [list(f.to_lonlat(x, y)) for x, y in pts]
        feat = {"type": "Feature", "id": "way/2", "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [ring]}}
        bld = model.from_footprint(feat, lidar={"height_above_ground_m": 5.4})
        self.assertTrue(any("not rectangular" in n for n in bld.notes),
                        bld.notes)


class TestCommands(unittest.TestCase):
    def _project(self, storeys=2):
        from twin import commands, model
        f = geodesy.LocalFrame(52.4856, -1.8476)
        ring = [list(f.to_lonlat(x, y)) for x, y in
                [(0, 0), (6, 0), (6, 10), (0, 10), (0, 0)]]
        feat = {"type": "Feature", "id": "way/1",
                "properties": {"levels": str(storeys)},
                "geometry": {"type": "Polygon", "coordinates": [ring]}}
        return commands.Project(model.from_footprint(feat)), commands

    def test_an_extension_adds_exactly_depth_times_wall_length(self):
        pj, C = self._project()
        before = pj.current().footprint()
        pj.apply(C.make("extend", block_id="existing", edge="rear",
                        depth_m=4.0, storeys=1))
        grew = pj.current().footprint() - before
        w = pj.current().block("existing").width
        self.assertAlmostEqual(grew, 4.0 * w, delta=0.02)
        self.assertEqual(len(pj.current().blocks), 2)

    def test_an_extension_lands_on_the_side_it_was_asked_for(self):
        pj, C = self._project()
        base = pj.current().block("existing")
        for edge, test in (("rear", lambda b: b.y >= base.y + base.depth - 1e-6),
                           ("front", lambda b: b.y < base.y),
                           ("left", lambda b: b.x < base.x),
                           ("right", lambda b: b.x >= base.x + base.width - 1e-6)):
            p2, _ = self._project()
            p2.apply(C.make("extend", block_id="existing", edge=edge,
                            depth_m=3.0, storeys=1))
            new = [b for b in p2.current().blocks if b.id != "existing"][0]
            self.assertTrue(test(new), f"{edge}: {new.x},{new.y}")

    def test_impossible_edits_are_refused_and_change_nothing(self):
        pj, C = self._project()
        before = pj.current().as_dict()
        for kw, phrase in (
                (dict(depth_m=-2), "positive depth"),
                (dict(depth_m=4, storeys=9), "at most one storey above"),
                (dict(depth_m=4, width_m=99), "at most"),
                (dict(depth_m=99), "second house")):
            with self.assertRaises(C.CommandError) as cm:
                pj.apply(C.make("extend", block_id="existing", edge="rear",
                                **kw))
            self.assertIn(phrase, str(cm.exception))
        self.assertEqual(pj.current().as_dict(), before,
                         "a refused command must leave the model untouched")

    def test_undo_and_redo_return_the_model_exactly(self):
        pj, C = self._project()
        start = pj.current().measurements()
        pj.apply(C.make("extend", block_id="existing", edge="rear",
                        depth_m=4.0, storeys=1))
        grown = pj.current().measurements()
        pj.undo()
        self.assertEqual(pj.current().measurements(), start)
        pj.redo()
        self.assertEqual(pj.current().measurements(), grown)

    def test_history_replays_rather_than_inverting(self):
        """Three edits, rewind to version 1, and the model must be what
        one command produced — not an inverse-operation approximation."""
        pj, C = self._project()
        pj.apply(C.make("extend", block_id="existing", edge="rear",
                        depth_m=3.0, storeys=1))
        after_one = pj.current().measurements()
        pj.apply(C.make("set_storeys", block_id="existing", storeys=3))
        pj.apply(C.make("set_roof", block_id="existing", kind="hipped",
                        pitch_deg=40))
        pj.restore(1)
        self.assertEqual(pj.current().measurements(), after_one)
        self.assertTrue(pj.history()["can_redo"])

    def test_the_existing_building_cannot_be_deleted(self):
        pj, C = self._project()
        with self.assertRaises(C.CommandError) as cm:
            pj.apply(C.make("remove_block", block_id="existing"))
        self.assertIn("twin of a real house", str(cm.exception))

    def test_moving_a_wall_marks_the_block_as_user_edited(self):
        pj, C = self._project()
        self.assertNotEqual(pj.current().block("existing").classification,
                            "user")
        pj.apply(C.make("move_wall", block_id="existing", edge="rear",
                        by_m=2.0))
        b = pj.current().block("existing")
        self.assertEqual(b.classification, "user")
        self.assertAlmostEqual(b.depth, 12.0, delta=0.01)

    def test_a_wall_cannot_be_dragged_through_itself(self):
        pj, C = self._project()
        with self.assertRaises(C.CommandError) as cm:
            pj.apply(C.make("move_wall", block_id="existing", edge="rear",
                            by_m=-20.0))
        self.assertIn("nothing smaller", str(cm.exception))

    def test_plain_english_becomes_a_validated_command(self):
        pj, C = self._project()
        bld = pj.current()
        cmd = C.parse_instruction("add a 4 m rear extension", bld)
        self.assertEqual(cmd.kind, "extend")
        self.assertEqual(cmd.params["depth_m"], 4.0)
        self.assertEqual(cmd.params["edge"], "rear")
        two = C.parse_instruction("build a two storey side extension of 3 m",
                                  bld)
        self.assertEqual(two.params["storeys"], 2)
        roof = C.parse_instruction("change the roof to a hip roof at 35 degrees",
                                   bld)
        self.assertEqual(roof.params["kind"], "hipped")
        self.assertEqual(roof.params["pitch_deg"], 35.0)

    def test_an_instruction_it_cannot_parse_is_refused_not_guessed(self):
        pj, C = self._project()
        with self.assertRaises(C.CommandError) as cm:
            C.parse_instruction("make it nicer", pj.current())
        self.assertIn("did not understand", str(cm.exception))
        self.assertIn("4 m rear extension", str(cm.exception))

    def test_an_extension_without_a_depth_asks_for_one(self):
        pj, C = self._project()
        with self.assertRaises(C.CommandError) as cm:
            C.parse_instruction("add a rear extension", pj.current())
        self.assertIn("how deep", str(cm.exception))


class TestDesignBridge(unittest.TestCase):
    def _bld(self, storeys=2):
        from twin import model
        f = geodesy.LocalFrame(52.4856, -1.8476)
        ring = [list(f.to_lonlat(x, y)) for x, y in
                [(0, 0), (6, 0), (6, 10), (0, 10), (0, 0)]]
        return model.from_footprint({
            "type": "Feature", "id": "way/1",
            "properties": {"levels": str(storeys)},
            "geometry": {"type": "Polygon", "coordinates": [ring]}})

    def test_the_plan_and_the_3d_read_the_same_blocks(self):
        """The mandatory requirement: one geometry, two views. Their
        areas must agree exactly, not approximately."""
        from twin import commands, design
        bld = self._bld()
        pj = commands.Project(bld)
        pj.apply(commands.make("extend", block_id="existing", edge="rear",
                               depth_m=4.0, storeys=1))
        cur = pj.current()
        plan = design.floor_plan(cur)
        mass = design.massing(cur)
        self.assertEqual(plan["levels"][0]["area_m2"],
                         round(cur.footprint(), 2))
        self.assertEqual(len(mass["solids"]), len(cur.blocks))
        for s in mass["solids"]:
            blk = cur.block(s["id"])
            self.assertEqual(s["ring"], blk.ring())

    def test_upper_floors_only_carry_the_blocks_that_reach_them(self):
        from twin import commands, design
        pj = commands.Project(self._bld(storeys=2))
        pj.apply(commands.make("extend", block_id="existing", edge="rear",
                               depth_m=4.0, storeys=1))
        plan = design.floor_plan(pj.current())
        self.assertEqual(len(plan["levels"]), 2)
        self.assertEqual(len(plan["levels"][0]["blocks"]), 2)
        self.assertEqual(len(plan["levels"][1]["blocks"]), 1,
                         "a single-storey extension has no first floor")

    def test_the_wall_between_two_blocks_is_internal(self):
        from twin import commands, design
        pj = commands.Project(self._bld(storeys=1))
        pj.apply(commands.make("extend", block_id="existing", edge="rear",
                               depth_m=4.0, storeys=1))
        walls = design.floor_plan(pj.current())["levels"][0]["walls"]
        shared = [w for w in walls if not w["external"]]
        self.assertTrue(shared, "the abutting walls must not both be external")

    def test_the_real_engine_runs_and_returns_a_bill(self):
        from twin import commands, design
        pj = commands.Project(self._bld())
        pj.apply(commands.make("extend", block_id="existing", edge="rear",
                               depth_m=4.0, storeys=1))
        a = design.assess(pj.current())
        self.assertTrue(a["available"])
        self.assertIn("compliance", a)
        bricks = [L for L in a["quantities"]["groups"]["masonry"]
                  if "Facing bricks" in L["item"]]
        self.assertTrue(bricks and bricks[0]["quantity"] > 500)
        self.assertGreater(a["totals"]["floor_area_m2"], 0)

    def test_a_massing_refusal_is_labelled_as_such_not_as_illegal(self):
        from twin import commands, design
        a = design.assess(commands.Project(self._bld()).current())
        self.assertEqual(a["compliance"]["stage"], "massing")
        self.assertIn("not about the extension", a["compliance"]["note"])


# --------------------------------------------------------------- imagery
class TestImagery(unittest.TestCase):
    def setUp(self):
        from twin.providers import imagery
        self.img = imagery

    def test_the_unlicensed_esri_endpoint_is_not_among_the_sources(self):
        """The Stage 0 finding must not creep back in through imagery."""
        for s in self.img.SOURCES.values():
            self.assertNotIn("server.arcgisonline.com", s.url or "")

    def test_a_non_commercial_source_is_refused_for_a_paid_product(self):
        s2 = self.img.get("s2cloudless")
        ok, why = s2.usable(commercial=True)
        self.assertFalse(ok)
        self.assertTrue(any("commercial" in w for w in why))
        # ...and allowed when the use genuinely is non-commercial.
        self.assertTrue(s2.usable(commercial=False)[0])

    def test_a_keyed_source_is_unavailable_until_a_key_is_configured(self):
        esri = self.img.get("esri-keyed")
        os.environ.pop("ARCGIS_API_KEY", None)
        ok, why = esri.usable()
        self.assertFalse(ok)
        self.assertIn("ARCGIS_API_KEY", why[0])
        os.environ["ARCGIS_API_KEY"] = "test-key-not-real"
        try:
            self.assertTrue(esri.usable()[0])
            url = self.img.tile_url(esri, 18, 1, 2)
            self.assertIn("test-key-not-real", url)
        finally:
            os.environ.pop("ARCGIS_API_KEY", None)

    def test_the_lidar_render_needs_no_key_and_is_commercially_usable(self):
        hs = self.img.get("lidar-hillshade")
        ok, why = hs.usable(commercial=True)
        self.assertTrue(ok, why)
        self.assertFalse(hs.needs_key)
        self.assertEqual(hs.licence, "ogl-3.0")

    def test_sources_are_ranked_usable_first_then_finest(self):
        os.environ.pop("ARCGIS_API_KEY", None)
        rows = self.img.for_country("GB")
        self.assertTrue(rows[0]["usable"])
        self.assertEqual(rows[0]["key"], "lidar-hillshade")
        firsts = [r["usable"] for r in rows]
        self.assertEqual(firsts, sorted(firsts, reverse=True),
                         "unusable sources must not be offered first")

    def test_resolution_is_stated_so_a_10m_source_cannot_pose_as_aerial(self):
        self.assertGreaterEqual(self.img.get("s2cloudless").resolution_m, 10)
        self.assertIn("not a house", self.img.get("s2cloudless").note)

    def test_hillshade_lights_from_the_north_west(self):
        """Light from below inverts perceived relief and every roof reads
        as a valley — the classic shaded-relief mistake."""
        import numpy as np
        # A ridge running north-south: west face should be lit, east dark.
        g = np.zeros((9, 9))
        for i in range(9):
            g[:, i] = 4.0 - abs(i - 4) * 1.0
        sh = self.img._hillshade(g, 1.0)
        west = sh[4, 2]
        east = sh[4, 6]
        self.assertGreater(west, east,
                           "the north-west-facing slope must be brighter")

    def test_a_render_far_outside_england_is_refused_not_faked(self):
        png, why = self.img.render_lidar_surface(2.29, 48.85, 2.30, 48.86)
        self.assertIsNone(png)
        self.assertTrue(isinstance(why, str) and why)


# --------------------------------------------------------------- pricing
class TestEstimate(unittest.TestCase):
    def setUp(self):
        import sys as _s, os as _o
        b = _o.path.join(_o.path.dirname(_o.path.dirname(
            _o.path.abspath(__file__))), "building")
        if b not in _s.path:
            _s.path.insert(0, b)
        import estimate, model3d as M, quantities as Q
        self.E, self.Q = estimate, Q
        self.model = M.build(
            [M.Room("Room", 0.0, 0.0, 6.0, 10.0, kind="room")],
            storeys=2, storey_height=2.65,
            roof={"pitch_deg": 30.0, "kind": "gabled", "overhang": 0.3,
                  "ridge_along": "y", "max_span_m": 12.0})
        self.bill = Q.bill(self.model)

    def test_the_bill_now_covers_every_standard_package(self):
        """It used to cover four of ten — no foundations, no roof
        timbers, no windows, no insulation, no fit-out — and pricing
        that would have been a trap."""
        cov = self.E.coverage(self.bill)
        self.assertTrue(cov["complete"],
                        [a["package"] for a in cov["absent"]])
        self.assertEqual(cov["priced_packages"], cov["total_packages"])

    def test_nothing_in_the_bill_goes_unpriced_in_silence(self):
        p = self.E.price_bill(self.bill)
        self.assertEqual(p["unpriced"], [],
                         "an unpriced line must be reported, and there "
                         "should be none for the standard bill")

    def test_a_partial_bill_is_labelled_partial_and_widens_the_range(self):
        thin = {"groups": {"masonry": self.bill["groups"]["masonry"]}}
        p = self.E.price_bill(thin, estimate_class="concept")
        self.assertEqual(p["status"], "PARTIAL")
        self.assertIn("PARTIAL PRICE", p["disclaimer"])
        self.assertGreater(len(p["excludes"]), 5)
        full = self.E.price_bill(self.bill, estimate_class="concept")
        self.assertGreater(
            p["totals"]["range_high"] / p["totals"]["gross"],
            full["totals"]["range_high"] / full["totals"]["gross"],
            "a bill missing work must widen the range upward")

    def test_the_estimate_is_a_range_not_a_single_number(self):
        p = self.E.price_bill(self.bill, estimate_class="order_of_magnitude")
        t = p["totals"]
        self.assertLess(t["range_low"], t["gross"])
        self.assertGreater(t["range_high"], t["gross"])
        self.assertIn("ESTIMATE, not a quotation", p["disclaimer"])

    def test_a_looser_estimate_class_gives_a_wider_range(self):
        loose = self.E.price_bill(self.bill,
                                  estimate_class="order_of_magnitude")
        tight = self.E.price_bill(self.bill, estimate_class="tender")
        spread = lambda p: (p["totals"]["range_high"]
                            - p["totals"]["range_low"]) / p["totals"]["gross"]
        self.assertGreater(spread(loose), spread(tight) * 2)

    def test_vat_is_applied_at_the_rate_the_work_actually_attracts(self):
        std = self.E.price_bill(self.bill, vat="standard")
        zero = self.E.price_bill(self.bill, vat="zero")
        self.assertAlmostEqual(std["totals"]["vat"],
                               std["totals"]["net"] * 0.20, delta=1.0)
        self.assertEqual(zero["totals"]["vat"], 0.0)
        self.assertAlmostEqual(zero["totals"]["gross"],
                               zero["totals"]["net"], delta=0.01)
        self.assertIn("708", std["disclaimer"])

    def test_region_moves_the_price_the_way_it_moves_in_life(self):
        lon = self.E.price_bill(self.bill, self.E.RateCard(region="london"))
        ne = self.E.price_bill(self.bill, self.E.RateCard(region="north_east"))
        self.assertGreater(lon["totals"]["gross"], ne["totals"]["gross"])
        ratio = lon["totals"]["gross"] / ne["totals"]["gross"]
        self.assertAlmostEqual(ratio, 1.12 / 0.93, delta=0.02)

    def test_an_unknown_region_is_refused_rather_than_defaulted(self):
        with self.assertRaises(ValueError):
            self.E.RateCard(region="narnia")

    def test_the_estimate_says_how_much_of_itself_is_guessed(self):
        p = self.E.price_bill(self.bill)
        self.assertEqual(p["rate_provenance"]["from_your_own_rates"], 0)
        self.assertIn("indicative", p["rate_provenance"]["confidence"])
        own = self.E.RateCard(materials={"Facing bricks": 0.61})
        p2 = self.E.price_bill(self.bill, own)
        self.assertEqual(p2["rate_provenance"]["from_your_own_rates"], 1)

    def test_calibration_reproduces_the_job_you_gave_it(self):
        """One real job in, and the card prices like your business."""
        card, rep = self.E.calibrate(self.bill, 120.0, known_per_m2=2200.0)
        p = self.E.price_bill(self.bill, card)
        m = self.E.per_m2(p, 120.0)
        self.assertAlmostEqual(m["gross_per_m2"], 2200.0, delta=25.0)
        self.assertGreater(rep["factor"], 1.0)
        self.assertIn("multiplied by", rep["note"])

    def test_calibration_accepts_a_total_as_well_as_a_rate(self):
        card, rep = self.E.calibrate(self.bill, 120.0, known_cost=264000.0)
        p = self.E.price_bill(self.bill, card)
        self.assertAlmostEqual(p["totals"]["gross"], 264000.0, delta=2500.0)

    def test_an_implausible_calibration_is_refused(self):
        with self.assertRaises(ValueError):
            self.E.calibrate(self.bill, 120.0, known_per_m2=50.0)
        with self.assertRaises(ValueError):
            self.E.calibrate(self.bill, 120.0)

    def test_the_per_m2_sanity_check_calls_out_a_low_number(self):
        """The check that stops an incomplete or under-rated estimate
        being quoted: it must say so in words, not just in a number."""
        p = self.E.price_bill(self.bill)
        m = self.E.per_m2(p, 120.0)
        self.assertLess(m["gross_per_m2"], self.E.TYPICAL_GROSS_PER_M2[0])
        self.assertIn("below", m["verdict"])
        self.assertIn("calibrate", m["verdict"])

    def test_labour_is_priced_by_trade_with_hours_shown(self):
        p = self.E.price_bill(self.bill)
        trades = {l["trade"] for l in p["labour"]["lines"]}
        self.assertIn("bricklayer", trades)
        self.assertIn("groundworker", trades)
        self.assertGreater(p["labour"]["hours"], 100)
        for l in p["labour"]["lines"]:
            self.assertGreater(l["rate_per_hour"], 10)

    def test_the_totals_add_up(self):
        p = self.E.price_bill(self.bill, vat="standard")
        t = p["totals"]
        measured = p["materials"]["total"] + p["labour"]["total"]
        self.assertAlmostEqual(t["measured_works"], measured, delta=0.5)
        built = (measured + p["preliminaries"]["total"]
                 + p["overhead_profit"]["total"]
                 + p["contingency"]["total"])
        self.assertAlmostEqual(t["build_total"], built, delta=0.5)
        self.assertAlmostEqual(
            t["net"], built + p["professional_fees"]["total"], delta=0.5)
        self.assertAlmostEqual(t["gross"], t["net"] + t["vat"], delta=0.5)


# ------------------------------------------------------------------ live
@unittest.skipUnless(LIVE, "set TWIN_LIVE=1 to hit real endpoints")
class TestLive(unittest.TestCase):
    """Proves the adapters match the real services, not my idea of them."""

    def setUp(self):
        self.r = Registry()

    def test_a_uk_postcode_resolves_through_the_uk_provider(self):
        res = self.r.geocode("B8 3AY")
        self.assertTrue(res.available)
        self.assertEqual(res.provenance.source_dataset, "postcodes.io")

    def test_a_worldwide_place_resolves_through_nominatim(self):
        res = self.r.geocode("Brandenburg Gate, Berlin")
        self.assertTrue(res.available)
        self.assertAlmostEqual(res.value[0]["lat"], 52.516, delta=0.02)
        self.assertEqual(res.value[0]["country_code"], "DE")

    def test_real_footprints_come_back_with_real_areas(self):
        res = self.r.buildings(-1.8485, 52.4851, -1.8467, 52.4861)
        self.assertTrue(res.available)
        feats = res.value["features"]
        self.assertGreater(len(feats), 3)
        areas = [geodesy.polygon_area(f["geometry"]) for f in feats]
        # Real buildings, so real sizes: nothing zero, nothing a county.
        self.assertTrue(all(2 < a < 20000 for a in areas), sorted(areas)[:3])

    def test_lidar_elevation_samples_the_point_not_a_snapped_grid(self):
        """Found by looking at an impossible number: snapping the QUERY
        point for cache reuse moved the sample up to 14 m and returned a
        building height of MINUS 0.22 m. On a roof must read metres; on
        the road beside it must read about zero."""
        from twin.providers.uk import UKProvider
        p = UKProvider()
        on_roof = p.elevation(52.484342, -1.8500538)
        self.assertTrue(on_roof.available, on_roof)
        h = on_roof.value["height_above_ground_m"]
        self.assertGreater(h, 1.5, "a building must stand above the ground")
        self.assertLess(h, 30.0, "and not be a tower block")
        self.assertLess(on_roof.value["nearest_cell_m"], 2.0,
                        "the sample must be AT the point")
        on_road = p.elevation(52.484790, -1.8500538)
        self.assertTrue(on_road.available)
        self.assertLess(abs(on_road.value["height_above_ground_m"]), 1.0,
                        "open ground must be at ground level")

    def test_lidar_agrees_with_an_independent_measurement_of_the_same_block(self):
        """94 Parkfield Road was measured separately in this project by
        fitting planes to a DSM window: ground 118.88 m AOD, ridge 8.12 m
        above it. A point sample here must land on the same building."""
        from twin.providers.uk import UKProvider
        r = UKProvider().elevation(52.485590875, -1.8474998)
        self.assertTrue(r.available, r)
        self.assertAlmostEqual(r.value["ground_m_aod"], 118.88, delta=0.6)
        self.assertAlmostEqual(r.value["surface_m_aod"], 127.00, delta=0.6)

    def test_the_lidar_surface_renders_a_real_png_of_real_houses(self):
        from twin.providers import imagery
        png, info = imagery.render_lidar_surface(-1.8500, 52.4845,
                                                 -1.8452, 52.4868)
        self.assertIsNotNone(png, info)
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertEqual(info["cell_m"], 1.0)
        # The bounds it covers are its OWN, and must overlap the request.
        w, s, e, n = info["bounds"]
        self.assertLess(w, e)
        self.assertLess(s, n)
        self.assertAlmostEqual(w, -1.8500, delta=0.002)
        # Real terrain has real relief: a flat answer means a dead fetch.
        self.assertGreater(info["max_m_aod"] - info["min_m_aod"], 3.0)

    def test_nonsense_is_missing_worldwide(self):
        self.assertFalse(self.r.geocode("qqqqzzzz nowhere at all 12345"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
