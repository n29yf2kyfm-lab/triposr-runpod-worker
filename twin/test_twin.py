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
import io
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


# ----------------------------------------------------------------- rooms
class TestRooms(unittest.TestCase):
    """Rooms are what turn the regulations gate from a shrug into an
    answer, so these tests are about the gate's view of them as much as
    about the geometry."""

    def _project(self, storeys=2, extend=True):
        from twin import commands, model
        f = geodesy.LocalFrame(52.4856, -1.8476)
        ring = [list(f.to_lonlat(x, y)) for x, y in
                [(0, 0), (6, 0), (6, 10), (0, 10), (0, 0)]]
        bld = model.from_footprint({
            "type": "Feature", "id": "way/1",
            "properties": {"levels": str(storeys)},
            "geometry": {"type": "Polygon", "coordinates": [ring]}})
        pj = commands.Project(bld)
        if extend:
            pj.apply(commands.make("extend", block_id="existing",
                                   edge="rear", depth_m=4.0, storeys=1))
        return pj, commands

    def test_a_laid_out_level_covers_its_block_with_no_gaps(self):
        pj, C = self._project(extend=False)
        pj.apply(C.make("auto_layout", block_id="existing", level=0))
        blk = pj.current().block("existing")
        rooms = pj.current().rooms_on(0)
        self.assertGreaterEqual(len(rooms), 4)
        self.assertAlmostEqual(sum(r.area() for r in rooms),
                               blk.width * blk.depth, places=1)
        for r in rooms:
            self.assertGreaterEqual(r.x, blk.x - 1e-6)
            self.assertLessEqual(r.x + r.width, blk.x + blk.width + 1e-6)

    def test_laying_out_the_rooms_does_the_whole_house_not_one_floor(self):
        """The parser used to pin block and level, which left the upper
        floor and the extension as lumps and produced refusals that were
        the parser's fault, not the design's."""
        pj, C = self._project()
        pj.apply(C.parse_instruction("lay out the rooms", pj.current()))
        cur = pj.current()
        self.assertTrue(cur.rooms_on(0))
        self.assertTrue(cur.rooms_on(1), "the first floor was left a lump")
        blocks = {r.block_id for r in cur.rooms}
        self.assertEqual(len(blocks), len(cur.blocks),
                         "the extension was left a lump")

    def test_an_extension_is_laid_out_as_one_space_not_a_little_house(self):
        """A hall-and-rooms plan inside a 4 m extension makes inner
        rooms, which the gate then refuses — for the layout, not the
        design."""
        pj, C = self._project()
        ext = [b.id for b in pj.current().blocks if b.id != "existing"][0]
        pj.apply(C.make("auto_layout", block_id=ext, level=0))
        rooms = [r for r in pj.current().rooms if r.block_id == ext]
        self.assertEqual(len(rooms), 1)
        self.assertEqual(rooms[0].kind, "kitchen")

    def test_drawn_rooms_reach_the_engine_and_the_block_lump_does_not(self):
        from twin import model
        pj, C = self._project(extend=False)
        pj.apply(C.make("auto_layout", block_id="existing", level=0))
        rooms, _M = model.to_engine_rooms(pj.current())
        names = [r.name for r in rooms if r.base_level == 0]
        self.assertIn("Hall", names)
        self.assertFalse([n for n in names if n.endswith(" L0")],
                         "a phantom whole-block room was laid over the "
                         "real ones")

    def test_a_block_with_nothing_drawn_in_it_still_reaches_the_engine(self):
        from twin import model
        pj, C = self._project()
        pj.apply(C.make("auto_layout", block_id="existing", level=0))
        rooms, _M = model.to_engine_rooms(pj.current())
        ext = [b for b in pj.current().blocks if b.id != "existing"][0]
        self.assertTrue([r for r in rooms if r.name.startswith(ext.name)],
                        "the un-laid-out extension vanished from the model")

    def test_a_room_spanning_two_blocks_does_not_get_a_lump_laid_over_it(self):
        """The knock-through case: one room across the old rear wall.
        The fallback must ask 'is this block covered', not 'does this
        block own a room'."""
        from twin import model
        pj, C = self._project()
        pj.apply(C.parse_instruction("lay out the rooms", pj.current()))
        cur = pj.current()
        kitchen = [r for r in cur.rooms_on(0) if r.kind == "kitchen"]
        self.assertEqual(len(kitchen), 2)
        pj.apply(C.make("merge_rooms", room_id=kitchen[0].id,
                        other_id=kitchen[1].id))
        rooms, _M = model.to_engine_rooms(pj.current())
        lumps = [r for r in rooms if r.name.endswith(" L0")]
        self.assertFalse(lumps, f"phantom rooms over a merged space: "
                                f"{[r.name for r in lumps]}")

    def test_the_verdict_stops_saying_massing_once_rooms_exist(self):
        from twin import design
        pj, C = self._project()
        before = design.assess(pj.current())
        self.assertEqual(before["compliance"]["stage"], "massing")
        pj.apply(C.parse_instruction("lay out the rooms", pj.current()))
        after = design.assess(pj.current())
        self.assertEqual(after["compliance"]["stage"], "design")

    def test_the_knock_through_clears_the_inner_room_refusal(self):
        """The whole reason merge_rooms exists: on site that wall comes
        out, and the verdict has to follow the building."""
        from twin import design
        pj, C = self._project()
        pj.apply(C.parse_instruction("lay out the rooms", pj.current()))
        codes = {f["code"] for f in
                 design.assess(pj.current())["compliance"]["findings"]
                 if f["severity"] == "refuse"}
        self.assertIn("CIRC-INNER2", codes)
        kitchen = [r for r in pj.current().rooms_on(0) if r.kind == "kitchen"]
        pj.apply(C.make("merge_rooms", room_id=kitchen[0].id,
                        other_id=kitchen[1].id))
        after = {f["code"] for f in
                 design.assess(pj.current())["compliance"]["findings"]
                 if f["severity"] == "refuse"}
        self.assertNotIn("CIRC-INNER2", after)

    def test_two_rooms_that_would_leave_an_l_shape_are_not_merged(self):
        pj, C = self._project(extend=False)
        pj.apply(C.make("auto_layout", block_id="existing", level=0))
        cur = pj.current()
        hall = [r for r in cur.rooms_on(0) if r.kind == "circulation"][0]
        kitchen = [r for r in cur.rooms_on(0) if r.kind == "kitchen"][0]
        living = [r for r in cur.rooms_on(0) if r.name == "Living room"][0]
        # hall + kitchen share only part of a wall
        with self.assertRaises(C.CommandError) as cm:
            pj.apply(C.make("merge_rooms", room_id=hall.id,
                            other_id=kitchen.id))
        self.assertIn("L-shaped", str(cm.exception))
        self.assertIsNotNone(pj.current().room(living.id))

    def test_a_dragged_partition_moves_the_room_on_the_other_side_too(self):
        """Move one and leave the other and the plan has a 150 mm void
        in it that measures wrong in every direction."""
        pj, C = self._project(extend=False)
        pj.apply(C.make("auto_layout", block_id="existing", level=0))
        cur = pj.current()
        living = [r for r in cur.rooms_on(0) if r.name == "Living room"][0]
        dining = [r for r in cur.rooms_on(0) if r.name == "Dining room"][0]
        before = living.area() + dining.area()
        pj.apply(C.make("move_partition", room_id=living.id,
                        edge="rear", by_m=0.5))
        cur = pj.current()
        living = cur.room(living.id)
        dining = cur.room(dining.id)
        self.assertAlmostEqual(living.y + living.depth, dining.y, places=3)
        self.assertAlmostEqual(living.area() + dining.area(), before,
                               places=2)

    def test_a_partition_dragged_through_its_neighbour_is_refused(self):
        pj, C = self._project(extend=False)
        pj.apply(C.make("auto_layout", block_id="existing", level=0))
        living = [r for r in pj.current().rooms_on(0)
                  if r.name == "Living room"][0]
        with self.assertRaises(C.CommandError) as cm:
            pj.apply(C.make("move_partition", room_id=living.id,
                            edge="rear", by_m=40.0))
        self.assertIn("too small", str(cm.exception))
        # and nothing moved
        self.assertEqual(pj.current().room(living.id).depth, living.depth)

    def test_an_external_wall_is_not_draggable_as_a_partition(self):
        pj, C = self._project(extend=False)
        pj.apply(C.make("auto_layout", block_id="existing", level=0))
        hall = [r for r in pj.current().rooms_on(0)
                if r.kind == "circulation"][0]
        with self.assertRaises(C.CommandError) as cm:
            pj.apply(C.make("move_partition", room_id=hall.id,
                            edge="left", by_m=1.0))
        self.assertIn("outside of the building", str(cm.exception))

    def test_a_cupboard_sized_room_is_refused_not_drawn(self):
        pj, C = self._project(extend=False)
        with self.assertRaises(C.CommandError) as cm:
            pj.apply(C.make("add_room", block_id="existing",
                            width_m=0.4, depth_m=3.0))
        self.assertIn("cupboard", str(cm.exception))

    def test_a_room_outside_its_block_is_refused(self):
        pj, C = self._project(extend=False)
        blk = pj.current().block("existing")
        with self.assertRaises(C.CommandError):
            pj.apply(C.make("add_room", block_id="existing",
                            x=blk.x, y=blk.y,
                            width_m=blk.width + 5.0, depth_m=3.0))

    def test_an_invented_room_kind_is_refused(self):
        pj, C = self._project(extend=False)
        with self.assertRaises(C.CommandError) as cm:
            pj.apply(C.make("add_room", block_id="existing",
                            room_kind="snug"))
        self.assertIn("circulation", str(cm.exception))

    def test_deleting_a_block_takes_its_rooms_with_it(self):
        pj, C = self._project()
        pj.apply(C.parse_instruction("lay out the rooms", pj.current()))
        ext = [b.id for b in pj.current().blocks if b.id != "existing"][0]
        pj.apply(C.make("remove_block", block_id=ext))
        self.assertFalse([r for r in pj.current().rooms
                          if r.block_id == ext],
                         "orphan rooms floating where the extension was")

    def test_undo_and_redo_of_a_layout_land_on_the_same_geometry(self):
        pj, C = self._project(extend=False)
        pj.apply(C.make("auto_layout", block_id="existing", level=0))
        pj.apply(C.make("add_room", block_id="existing", name="Utility",
                        room_kind="store", width_m=2.0, depth_m=2.0,
                        level=1))
        before = [r.as_dict() for r in pj.current().rooms]
        pj.undo()
        pj.redo()
        self.assertEqual([r.as_dict() for r in pj.current().rooms], before)

    def test_the_plan_ships_the_rooms_and_their_partitions(self):
        from twin import design
        pj, C = self._project(extend=False)
        pj.apply(C.make("auto_layout", block_id="existing", level=0))
        lvl = design.floor_plan(pj.current())["levels"][0]
        self.assertEqual(len(lvl["rooms"]), len(pj.current().rooms_on(0)))
        self.assertTrue(lvl["partitions"], "no internal walls to drag")
        self.assertAlmostEqual(lvl["room_area_m2"], lvl["area_m2"], places=1)
        for r in lvl["rooms"]:
            self.assertIn("ring", r)
            self.assertIn(r["kind"], ("room", "circulation", "kitchen",
                                      "wet", "store"))

    def test_renaming_a_room_does_not_move_it(self):
        pj, C = self._project(extend=False)
        pj.apply(C.make("auto_layout", block_id="existing", level=0))
        room = pj.current().rooms_on(0)[0]
        where = (room.x, room.y, room.width, room.depth)
        pj.apply(C.make("set_room", room_id=room.id, name="Front hall",
                        room_kind="circulation"))
        now = pj.current().room(room.id)
        self.assertEqual(now.name, "Front hall")
        self.assertEqual((now.x, now.y, now.width, now.depth), where)


# ------------------------------------------------- review regressions
class TestReviewFindings(unittest.TestCase):
    """Each test here reproduces a bug an adversarial review confirmed,
    exactly as reported, and holds the fix in place."""

    def _project(self, w=6, d=10, storeys=2):
        from twin import commands, model
        f = geodesy.LocalFrame(52.4856, -1.8476)
        ring = [list(f.to_lonlat(x, y)) for x, y in
                [(0, 0), (w, 0), (w, d), (0, d), (0, 0)]]
        bld = model.from_footprint({
            "type": "Feature", "id": "way/1",
            "properties": {"levels": str(storeys)},
            "geometry": {"type": "Polygon", "coordinates": [ring]}})
        return commands.Project(bld), commands

    def _merged(self):
        """House + rear extension, laid out, kitchen knocked through."""
        pj, C = self._project()
        pj.apply(C.make("extend", block_id="existing", edge="rear",
                        depth_m=4.0, storeys=1))
        pj.apply(C.parse_instruction("lay out the rooms", pj.current()))
        ks = [r for r in pj.current().rooms_on(0) if r.kind == "kitchen"]
        pj.apply(C.make("merge_rooms", room_id=ks[0].id, other_id=ks[1].id))
        return pj, C

    def test_removing_a_block_under_a_knocked_through_room_is_refused(self):
        """The merged kitchen spans the old wall; deleting the extension
        by anchor id left it hanging 4 m in the open air."""
        pj, C = self._merged()
        ext = [b.id for b in pj.current().blocks if b.id != "existing"][0]
        with self.assertRaises(C.CommandError) as cm:
            pj.apply(C.make("remove_block", block_id=ext))
        self.assertIn("spans the wall", str(cm.exception))
        # And in both merge orders: the refusal is about geometry, so
        # which room was clicked first cannot change the outcome.
        pj2, C2 = self._project()
        pj2.apply(C2.make("extend", block_id="existing", edge="rear",
                          depth_m=4.0, storeys=1))
        pj2.apply(C2.parse_instruction("lay out the rooms", pj2.current()))
        ks = [r for r in pj2.current().rooms_on(0) if r.kind == "kitchen"]
        pj2.apply(C2.make("merge_rooms", room_id=ks[1].id,
                          other_id=ks[0].id))
        ext2 = [b.id for b in pj2.current().blocks if b.id != "existing"][0]
        with self.assertRaises(C2.CommandError):
            pj2.apply(C2.make("remove_block", block_id=ext2))

    def test_a_partition_of_a_merged_room_is_internal_from_both_sides(self):
        """Pairing went by block_id, so the merged room's genuinely
        internal walls were invisible: one side dragged alone into an
        overlap, the other side was refused as 'outside'."""
        pj, C = self._merged()
        cur = pj.current()
        merged = [r for r in cur.rooms_on(0) if r.kind == "kitchen"][0]
        dining = [r for r in cur.rooms_on(0) if r.name == "Dining room"][0]
        hall = [r for r in cur.rooms_on(0) if r.kind == "circulation"][0]
        area_before = sum(r.area() for r in cur.rooms_on(0))
        # Drag the shared wall from the merged room's side: no refusal,
        # and BOTH rooms behind it (hall and dining, which tile that
        # wall between them) move with it.
        pj.apply(C.make("move_partition", room_id=merged.id,
                        edge="front", by_m=-0.3))
        cur = pj.current()
        merged, dining, hall = (cur.room(merged.id), cur.room(dining.id),
                                cur.room(hall.id))
        self.assertAlmostEqual(dining.y + dining.depth, merged.y, places=3)
        self.assertAlmostEqual(hall.y + hall.depth, merged.y, places=3)
        self.assertAlmostEqual(sum(r.area() for r in cur.rooms_on(0)),
                               area_before, places=2)

    def test_overlapping_rooms_cannot_swallow_the_block_fallback(self):
        """Coverage summed per-room, so two stacked rooms in one corner
        counted twice and 62% of the floor plate vanished silently."""
        from twin import model
        pj, C = self._project(storeys=1)
        pj.apply(C.make("add_room", block_id="existing", name="A",
                        width_m=5.0, depth_m=4.5))
        # A deliberate overlap, forced past the command validation the
        # way a bug or an old saved model would arrive.
        bld = pj.current()
        bld.rooms.append(model.Room(
            id="rm-forced", block_id="existing", level=0, name="B",
            kind="room", x=bld.rooms[0].x, y=bld.rooms[0].y,
            width=5.0, depth=4.5))
        rooms, _M = model.to_engine_rooms(bld)
        self.assertTrue([r for r in rooms if r.name.endswith(" L0")],
                        "the mostly-bare block lost its fallback lump")

    def test_adding_a_room_on_top_of_another_is_refused(self):
        pj, C = self._project(storeys=1)
        pj.apply(C.make("add_room", block_id="existing", name="A",
                        width_m=4.0, depth_m=4.0))
        with self.assertRaises(C.CommandError) as cm:
            pj.apply(C.make("add_room", block_id="existing", name="B",
                            width_m=3.0, depth_m=3.0))
        self.assertIn("overlap", str(cm.exception))

    def test_an_edited_house_still_gets_its_extension_laid_out_as_one(self):
        """The extension test keyed off classification, which MoveWall
        rewrites on the first survey correction — after which a 4 m
        extension was minced into a little house of inner rooms."""
        pj, C = self._project()
        pj.apply(C.make("move_wall", block_id="existing", edge="rear",
                        by_m=0.5))
        pj.apply(C.make("extend", block_id="existing", edge="rear",
                        depth_m=4.0, storeys=1))
        pj.apply(C.parse_instruction("lay out the rooms", pj.current()))
        ext = [b for b in pj.current().blocks if b.id != "existing"][0]
        ext_rooms = [r for r in pj.current().rooms
                     if r.block_id == ext.id]
        self.assertEqual(len(ext_rooms), 1,
                         [r.name for r in ext_rooms])

    def test_auto_layout_never_mints_a_room_the_editor_would_refuse(self):
        """min/max in the wrong order produced a zero-depth bathroom and
        a 0.7 m kitchen — sizes AddRoom itself refuses as cupboards."""
        from twin import model
        for w, d in ((2.5, 3.0), (3.0, 3.2), (5.0, 4.6), (2.4, 4.5),
                     (6.0, 5.0), (4.0, 14.9)):
            pj, C = self._project(w=w, d=d, storeys=2)
            pj.apply(C.parse_instruction("lay out the rooms", pj.current()))
            for r in pj.current().rooms:
                self.assertGreaterEqual(
                    r.width, model.MIN_ROOM_M - 1e-9,
                    f"{w}x{d}: {r.name} is {r.width} wide")
                self.assertGreaterEqual(
                    r.depth, model.MIN_ROOM_M - 1e-9,
                    f"{w}x{d}: {r.name} is {r.depth} deep")

    def test_layout_bands_tile_exactly_at_awkward_depths(self):
        """Rounding depths separately left 1 mm gaps at band joints, so
        the partition pairing missed its neighbour and a drag sailed
        half a metre into the kitchen."""
        pj, C = self._project(w=5, d=5.675, storeys=1)
        pj.apply(C.make("auto_layout", block_id="existing", level=0))
        cur = pj.current()
        dining = [r for r in cur.rooms_on(0) if r.name == "Dining room"][0]
        kitchen = [r for r in cur.rooms_on(0) if r.kind == "kitchen"][0]
        self.assertAlmostEqual(dining.y + dining.depth, kitchen.y,
                               places=9)
        area_before = sum(r.area() for r in cur.rooms_on(0))
        pj.apply(C.make("move_partition", room_id=kitchen.id, edge="front",
                        by_m=-0.5))
        cur = pj.current()
        self.assertAlmostEqual(cur.room(dining.id).y
                               + cur.room(dining.id).depth,
                               cur.room(kitchen.id).y, places=9)
        self.assertAlmostEqual(sum(r.area() for r in cur.rooms_on(0)),
                               area_before, places=2,
                               msg="the drag opened a void or an overlap")

    def test_a_wall_wider_than_the_room_dragging_it_is_refused(self):
        """The neighbour moves bodily, so a kitchen wider than the dining
        room dragging it swung its far end past the hall and opened a
        500 mm void — the very fault the pairing exists to prevent, one
        room further along."""
        pj, C = self._project(w=5, d=5.675, storeys=1)
        pj.apply(C.make("auto_layout", block_id="existing", level=0))
        cur = pj.current()
        dining = [r for r in cur.rooms_on(0) if r.name == "Dining room"][0]
        before = [(r.id, r.x, r.y, r.width, r.depth)
                  for r in cur.rooms_on(0)]
        with self.assertRaises(C.CommandError) as cm:
            pj.apply(C.make("move_partition", room_id=dining.id,
                            edge="rear", by_m=0.5))
        self.assertIn("runs past the end of that wall", str(cm.exception))
        self.assertIn("Kitchen", str(cm.exception))
        self.assertEqual([(r.id, r.x, r.y, r.width, r.depth)
                          for r in pj.current().rooms_on(0)], before,
                         "a refused drag left the model changed")

    def test_moving_a_wall_carries_the_rooms_on_it(self):
        """MoveWall resized only the block, leaving the kitchen 2 m
        outside a shrunk house — while the refusal text elsewhere
        promised 'the rooms follow'."""
        from twin import model
        pj, C = self._project()
        pj.apply(C.make("auto_layout", block_id="existing", level=0))
        kitchen = [r for r in pj.current().rooms_on(0)
                   if r.kind == "kitchen"][0]
        depth_before = kitchen.depth
        pj.apply(C.make("move_wall", block_id="existing", edge="rear",
                        by_m=1.0))
        cur = pj.current()
        kitchen = cur.room(kitchen.id)
        blk = cur.block("existing")
        self.assertAlmostEqual(kitchen.depth, depth_before + 1.0, places=3)
        self.assertAlmostEqual(kitchen.y + kitchen.depth,
                               blk.y + blk.depth, places=3)
        for r in cur.rooms_on(0):
            self.assertTrue(model.room_inside_building(cur, r),
                            f"{r.name} was left outside the building")

    def test_pulling_a_wall_through_a_room_is_refused(self):
        pj, C = self._project()
        pj.apply(C.make("auto_layout", block_id="existing", level=0))
        with self.assertRaises(C.CommandError) as cm:
            pj.apply(C.make("move_wall", block_id="existing", edge="rear",
                            by_m=-4.0))
        self.assertIn("too small", str(cm.exception))

    def test_room_edges_on_the_envelope_are_not_partitions(self):
        """They were, and the picker preferred them, so after a layout
        every envelope drag became a refused move_partition."""
        from twin import design
        pj, C = self._project()
        pj.apply(C.make("extend", block_id="existing", edge="rear",
                        depth_m=4.0, storeys=1))
        pj.apply(C.parse_instruction("lay out the rooms", pj.current()))
        L = design.floor_plan(pj.current())["levels"][0]
        ext_walls = [w for w in L["walls"] if w["external"]]

        def on_external(pts):
            for t in (0.0, 0.5, 1.0):
                px = pts[0][0] + (pts[1][0] - pts[0][0]) * t
                py = pts[0][1] + (pts[1][1] - pts[0][1]) * t
                if not any(
                        min((px - (ax + (bx - ax) * u)) ** 2 +
                            (py - (ay + (by - ay) * u)) ** 2
                            for u in (0, 0.25, 0.5, 0.75, 1)) < 1e-4
                        for (ax, ay), (bx, by) in
                        (w["points"] for w in ext_walls)):
                    return False
            return True

        for part in L["partitions"]:
            self.assertFalse(
                on_external(part["points"]),
                f"partition {part['id']} lies on the outside wall")
        # The block-to-block joint stays: that wall really is internal.
        joint = [p for p in L["partitions"]
                 if abs(p["points"][0][1] - 10.0) < 1e-6
                 and abs(p["points"][1][1] - 10.0) < 1e-6]
        self.assertTrue(joint, "the knock-through wall lost its partition")

    def test_malformed_command_bodies_get_a_422_not_a_500(self):
        """The endpoint's docstring promises refusals carry a reason;
        eight malformed bodies were verified to 500 with a stack."""
        from twin import api as A, commands as C
        pj, _ = self._project()
        A._projects[pj.id] = pj
        client = A.app.test_client()
        for body in (
                {"kind": "set_storeys", "block_id": "existing"},
                {"kind": "move_wall", "block_id": "existing", "by_m": 1},
                {"kind": "move_wall", "block_id": "existing",
                 "edge": "rear", "by_m": None},
                {"kind": "set_roof"},
                {"kind": "merge_rooms"},
                {"kind": "remove_block"},
                {"kind": "extend", "block_id": "existing",
                 "edge": "rear", "depth_m": [4]},
                {"text": 123}):
            r = client.post(f"/api/project/{pj.id}/command", json=body)
            self.assertEqual(r.status_code, 422, body)
            self.assertIn("reason", r.get_json(), body)

    def test_project_responses_are_never_cached(self):
        """A cached sheets.pdf is a superseded drawing set re-shown
        after an edit with nothing on it saying so."""
        from twin import api as A
        pj, _ = self._project()
        A._projects[pj.id] = pj
        client = A.app.test_client()
        r = client.get(f"/api/project/{pj.id}")
        self.assertEqual(r.headers.get("Cache-Control"), "no-store")

    def test_the_lean_to_slopes_the_way_the_model_says_it_does(self):
        """sheets.roof_z guessed orientation from the longer plan side;
        a 2.5 x 4 m rear extension sloped across its width on paper and
        across its depth in 3D — two answers from one model."""
        import math as m
        from twin import sheets
        pj, C = self._project()
        pj.apply(C.make("extend", block_id="existing", edge="rear",
                        depth_m=4.0, width_m=2.5, storeys=1))
        ext = [b for b in pj.current().blocks if b.id != "existing"][0]
        top = (ext.base_level + ext.storeys) * ext.storey_height
        rise = ext.depth * m.tan(m.radians(ext.roof["pitch_deg"]))
        mid_x = ext.x + ext.width / 2
        self.assertAlmostEqual(sheets.roof_z(ext, mid_x, ext.y),
                               top + rise, places=6,
                               msg="high edge is not at the house wall")
        self.assertAlmostEqual(sheets.roof_z(ext, mid_x,
                                             ext.y + ext.depth),
                               top, places=6,
                               msg="low edge is not at the rear")
        # And the schedule's ridge height agrees with the drawing.
        self.assertAlmostEqual(pj.current().ridge_m(),
                               max(pj.current().ridge_m(), top + rise),
                               places=6)

    def test_a_tall_block_behind_a_hipped_roof_shows_above_the_eaves(self):
        """Occlusion used a full-width rectangle to the front block's
        highest point, so a 6 m tower behind a hipped roof was declared
        invisible while demonstrably breaking the skyline."""
        from twin import commands, model, sheets
        f = geodesy.LocalFrame(52.4856, -1.8476)
        ring = [list(f.to_lonlat(x, y)) for x, y in
                [(0, 0), (10, 0), (10, 5), (0, 5), (0, 0)]]
        bld = model.from_footprint({
            "type": "Feature", "id": "way/9", "properties": {"levels": "2"},
            "geometry": {"type": "Polygon", "coordinates": [ring]}})
        bld.blocks[0].roof = {"kind": "hipped", "pitch_deg": 30.0,
                              "ridge_along": "x"}
        bld.blocks.append(model.Block(
            id="tower", name="Rear tower", x=0.0, y=5.0,
            width=10.0, depth=3.0, storeys=2, storey_height=3.0,
            classification="user", roof={"kind": "flat"}))
        sh = sheets.elevation_sheet(bld, "front")
        texts = " ".join(i["s"] for i in sh.items if i["op"] == "text")
        self.assertNotIn("Rear tower", texts,
                         "the visible tower was reported hidden")
        user_ink = sheets.CLASS_INK["user"]
        drawn = [i for i in sh.items if i["op"] in ("line", "poly")
                 and tuple(i["ink"]) == user_ink]
        self.assertTrue(drawn, "the tower is not drawn at all")

    def test_a_window_behind_the_extension_is_not_on_the_elevation(self):
        pj, C = self._project()
        pj.apply(C.make("extend", block_id="existing", edge="rear",
                        depth_m=3.0, storeys=1))
        pj.apply(C.make("add_opening", block_id="existing", edge="rear",
                        kind="window", along_m=2.0, width_m=1.2,
                        height_m=1.1, sill_m=0.9))
        from twin import sheets
        sh = sheets.elevation_sheet(pj.current(), "rear")
        window_ink = (0.1, 0.35, 0.7)
        drawn = [i for i in sh.items if i["op"] == "poly"
                 and tuple(i["ink"]) == window_ink]
        self.assertFalse(drawn, "a hidden window is drawn floating "
                                "inside the extension")

    def test_dimension_ticks_cross_the_line_they_terminate(self):
        """The tick arithmetic rotated the wrong way and drew collinear
        whiskers ON the dimension line — no terminators anywhere."""
        from twin import sheets
        out = sheets.dim_line((0, 0), (4, 0), 7.0,
                              lambda u, z: (u, z), side=-1)
        ticks = [i for i in out if i["op"] == "line"
                 and abs(i["w"] - 0.35) < 1e-9]
        self.assertEqual(len(ticks), 2)
        for t in ticks:
            dx = abs(t["b"][0] - t["a"][0])
            dy = abs(t["b"][1] - t["a"][1])
            self.assertGreater(dy, 0.5,
                               "tick has no component across the line")
            self.assertAlmostEqual(dx, dy, places=6)  # 45 degrees

    def test_a_hip_cut_off_centre_bends_where_the_hip_does(self):
        """Break points came from the silhouette, which only matches the
        cut when the cut bisects the block."""
        import math as m
        from twin import sheets

        class Blk:
            x, y, width, depth = 0.0, 0.0, 8.0, 4.0
            base_level, storeys, storey_height = 0, 1, 2.65
            roof = {"kind": "hipped", "pitch_deg": 45.0}
        us = sheets._section_us(Blk, "x", 1.0)   # cut 1 m from the eave
        self.assertIn(1.0, us)
        self.assertIn(7.0, us)
        z = sheets._profile_z(Blk, 1.0, "x", 1.0)
        self.assertAlmostEqual(z, 2.65 + 1.0 * m.tan(m.radians(45)),
                               places=6)

    def test_a_bifold_is_scheduled_as_a_door_family_not_a_window(self):
        pj, C = self._project()
        pj.apply(C.make("add_opening", block_id="existing", edge="rear",
                        kind="bifold", along_m=1.0, width_m=3.0,
                        height_m=2.1, sill_m=0.0))
        from twin import sheets
        sh = sheets.schedule_sheet(pj.current())
        texts = [i["s"] for i in sh.items if i["op"] == "text"]
        self.assertTrue(any(t.startswith("B0") for t in texts),
                        "bifold not referenced as B..")
        self.assertFalse(any(t.startswith("W0") for t in texts))


# ------------------------------------------------ the model sits on the house
class TestFootprintFit(unittest.TestCase):
    """The fitted rectangle must land ON the building it was fitted to.

    Every test in this suite passed while the model was rotated 90
    degrees and slid 12 m off the real house, because they all checked
    SIZES — area, GIA, heights — and w*d is unchanged by a rotation.
    Nothing checked POSITION. These do.
    """

    @staticmethod
    def _feature(cx_lon, cy_lat, w, d, bearing_deg):
        """A rectangular footprint of known size at a known angle."""
        f = geodesy.LocalFrame(cy_lat, cx_lon)
        b = math.radians(bearing_deg)
        ring = []
        for u, v in ((-w / 2, -d / 2), (w / 2, -d / 2),
                     (w / 2, d / 2), (-w / 2, d / 2), (-w / 2, -d / 2)):
            # +y of the rectangle points along `bearing_deg`
            e = u * math.cos(b) + v * math.sin(b)
            n = -u * math.sin(b) + v * math.cos(b)
            ring.append(list(f.to_lonlat(e, n)))
        return {"type": "Feature", "id": "way/test",
                "properties": {"levels": "2"},
                "geometry": {"type": "Polygon", "coordinates": [ring]}}

    def _fit_error(self, bearing_deg, w=8.0, d=13.0):
        from twin import model
        bld = model.from_footprint(
            self._feature(-1.8476, 52.4856, w, d, bearing_deg))
        blk = bld.blocks[0]
        xs = [p[0] for p in bld.traced_ring]
        ys = [p[1] for p in bld.traced_ring]
        # The real outline should fill the fitted rectangle exactly.
        return max(abs(min(xs) - blk.x), abs(min(ys) - blk.y),
                   abs(max(xs) - (blk.x + blk.width)),
                   abs(max(ys) - (blk.y + blk.depth)))

    def test_the_rectangle_lands_on_the_footprint_at_every_angle(self):
        for bearing in (0, 17, 20.4, 45, 90, 133, 180, 271, 359):
            with self.subTest(bearing=bearing):
                self.assertLess(
                    self._fit_error(bearing), 0.05,
                    f"at {bearing} deg the fitted rectangle is off the "
                    f"building it was fitted to")

    def test_the_recorded_bearing_is_the_bearing_of_the_depth_axis(self):
        """+y is depth. Taking the width axis instead turned every model
        90 degrees, which silently wrongs the north arrow, the Part O
        facade orientations and the shadow study."""
        from twin import model
        for want in (0.0, 20.4, 75.0, 200.0):
            bld = model.from_footprint(
                self._feature(-1.8476, 52.4856, 8.0, 13.0, want))
            got = bld.bearing_deg % 180.0        # a rectangle is 180-symmetric
            self.assertAlmostEqual(
                got, want % 180.0, delta=0.6,
                msg=f"recorded {bld.bearing_deg:.1f} for a building at {want}")

    def test_the_model_geolocates_back_onto_the_real_polygon(self):
        """Convert the block's own corners to lon/lat: they must overlap
        the footprint we started from, not sit beside it."""
        from twin import model
        feat = self._feature(-1.8476, 52.4856, 9.0, 14.0, 20.4)
        bld = model.from_footprint(feat)
        real = feat["geometry"]["coordinates"][0]
        blk = [bld.to_lonlat(x, y) for x, y in bld.blocks[0].ring()]
        for i, name in ((0, "lon"), (1, "lat")):
            r0, r1 = min(p[i] for p in real), max(p[i] for p in real)
            b0, b1 = min(p[i] for p in blk), max(p[i] for p in blk)
            overlap = min(r1, b1) - max(r0, b0)
            self.assertGreater(
                overlap, (r1 - r0) * 0.9,
                f"the block barely overlaps the real footprint in {name}")


# ------------------------------------------------------- ground imagery
class TestGround(unittest.TestCase):
    """Imagery draped under the 3D model. The maths that places it is
    the part that can be wrong silently, so that is what is tested."""

    def _project(self):
        from twin import commands, model
        f = geodesy.LocalFrame(52.4856, -1.8476)
        ring = [list(f.to_lonlat(x, y)) for x, y in
                [(0, 0), (6, 0), (6, 10), (0, 10), (0, 0)]]
        bld = model.from_footprint({
            "type": "Feature", "id": "way/1", "properties": {"levels": "2"},
            "geometry": {"type": "Polygon", "coordinates": [ring]}})
        bld.bearing_deg = 20.4          # a real terrace is never square to north
        return commands.Project(bld)

    def test_the_zoom_matches_the_detail_asked_for(self):
        from twin.providers import imagery
        # A 60 m box at 1024 px wants roughly 6 cm per pixel: z21.
        z = imagery.zoom_for(-1.8480, 52.4850, -1.8471, 52.4856, 1024, 22)
        self.assertGreaterEqual(z, 19)
        self.assertLessEqual(z, 22)

    def test_a_source_cannot_be_asked_beyond_the_zoom_it_publishes(self):
        """Past its max, a tile server returns grey 'no data' images that
        read as a rendering fault rather than a missing licence."""
        from twin.providers import imagery
        self.assertEqual(
            imagery.zoom_for(-1.848, 52.485, -1.8479, 52.4851, 4096, 17), 17)

    def test_a_keyed_source_is_refused_before_a_single_tile_is_fetched(self):
        from twin.providers import imagery
        png, reason = imagery.mosaic("mapbox-satellite", -1.848, 52.485,
                                     -1.847, 52.486)
        self.assertIsNone(png)
        self.assertIn("MAPBOX_TOKEN", reason)

    def test_an_unknown_source_is_named_not_swallowed(self):
        from twin.providers import imagery
        png, reason = imagery.mosaic("not-a-source", -1.848, 52.485,
                                     -1.847, 52.486)
        self.assertIsNone(png)
        self.assertIn("not-a-source", reason)

    def test_the_ground_comes_back_in_the_buildings_own_frame(self):
        """The corners must be ROTATED with the building. Handing the
        browser a lon/lat box would drape imagery square to north under
        a house that stands at 20 degrees to it."""
        from twin import api as A
        from twin.providers import imagery
        pj = self._project()
        A._projects[pj.id] = pj
        fake = (b"\x89PNG\r\n\x1a\n" + b"\0" * 32,
                {"bounds": [-1.8485, 52.4850, -1.8467, 52.4862],
                 "cell_m": 1.0, "licence": "ogl-3.0",
                 "attribution": "Environment Agency", "source": "lidar"})
        real = imagery.render_lidar_surface
        real_get = type(A._cache).get
        imagery.render_lidar_surface = lambda *a, **k: fake
        # Force a cache miss, and PUT IT BACK — patching a class and
        # walking away leaves every later test running against a cache
        # that always misses, which is how a suite starts lying.
        type(A._cache).get = lambda self, k: None
        try:
            r = A.app.test_client().get(f"/api/project/{pj.id}/ground")
        finally:
            imagery.render_lidar_surface = real
            type(A._cache).get = real_get
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertTrue(d["available"], d)
        self.assertEqual(len(d["corners_m"]), 4)
        # Rotated: no edge of the quad is axis-aligned in the local frame.
        xs = [c[0] for c in d["corners_m"]]
        ys = [c[1] for c in d["corners_m"]]
        self.assertGreater(max(xs) - min(xs), 1.0)
        self.assertGreater(max(ys) - min(ys), 1.0)
        for i in range(4):
            a, b = d["corners_m"][i], d["corners_m"][(i + 1) % 4]
            self.assertGreater(abs(a[0] - b[0]), 1e-3,
                               "an edge is square to the local frame, so "
                               "the bearing was not applied")
        self.assertIn("Environment Agency", d["attribution"])

    def test_the_ground_says_what_it_needs_when_there_is_none(self):
        from twin import api as A
        from twin.providers import imagery
        pj = self._project()
        A._projects[pj.id] = pj
        real = imagery.render_lidar_surface
        imagery.render_lidar_surface = lambda *a, **k: (None, "no coverage")
        try:
            r = A.app.test_client().get(
                f"/api/project/{pj.id}/ground?source=lidar-hillshade")
        finally:
            imagery.render_lidar_surface = real
        d = r.get_json()
        self.assertFalse(d["available"])
        self.assertEqual(d["status"], "DATA NOT AVAILABLE")
        self.assertIn("no coverage", d["reason"])
        self.assertIn("key of", d["note"])


# ---------------------------------------------------------- drawing sheets
class TestSheets(unittest.TestCase):
    """A drawing is a document with a scale you can put a rule against.

    These tests MEASURE the sheets rather than eyeballing them: the
    primitives are millimetres of paper, so "is this really 1:100" is
    arithmetic, not an opinion.
    """

    def _bld(self, storeys=2, extend=True, rooms=True):
        from twin import commands, model, provenance
        f = geodesy.LocalFrame(52.4856, -1.8476)
        ring = [list(f.to_lonlat(x, y)) for x, y in
                [(0, 0), (6, 0), (6, 10), (0, 10), (0, 0)]]
        prov = provenance.Provenance(
            source_provider="overpass", source_dataset="openstreetmap",
            source_identifier="way/121198175", licence="odbl-1.0",
            observation_date="2025-11-02").as_dict()
        bld = model.from_footprint({
            "type": "Feature", "id": "way/1",
            "properties": {"levels": str(storeys), "provenance": prov},
            "geometry": {"type": "Polygon", "coordinates": [ring]}})
        bld.address = "94 Parkfield Road, Birmingham B8 3AY"
        pj = commands.Project(bld)
        if extend:
            pj.apply(commands.make("extend", block_id="existing",
                                   edge="rear", depth_m=4.0, storeys=1))
        if rooms:
            pj.apply(commands.make("auto_layout"))
        return pj.current()

    @staticmethod
    def _texts(sh):
        return [i["s"] for i in sh.items if i["op"] == "text"]

    @staticmethod
    def _geometry(sh, bld):
        """The polys drawn in a block's classification ink — the
        building itself, not the frame, the title block or the rooms."""
        from twin import sheets
        inks = {sheets.CLASS_INK[b.classification] for b in bld.blocks}
        return [i for i in sh.items
                if i["op"] == "poly" and tuple(i["ink"]) in inks]

    def test_a_metre_on_the_model_is_ten_millimetres_at_1_100(self):
        """The whole claim of the module, measured off the primitives."""
        from twin import sheets
        bld = self._bld()
        sh = sheets.plan_sheet(bld, 0, scale=100)
        self.assertEqual(sh.scale, 100)
        blk = bld.block("existing")
        # The block outline is drawn in its classification's ink; its
        # width on paper must be the real width divided by the scale.
        widths = [max(p[0] for p in i["pts"]) - min(p[0] for p in i["pts"])
                  for i in self._geometry(sh, bld)]
        self.assertTrue(
            any(abs(w - blk.width * 1000.0 / 100.0) < 0.01 for w in widths),
            f"no 6 m wall came out 60 mm long: {sorted(widths)}")

    def test_the_same_building_at_1_50_is_exactly_twice_the_size(self):
        from twin import sheets
        bld = self._bld(storeys=1, extend=False)

        def span(scale):
            sh = sheets.plan_sheet(bld, 0, paper="A2", scale=scale)
            xs = [p[0] for i in self._geometry(sh, bld) for p in i["pts"]]
            return max(xs) - min(xs)
        self.assertAlmostEqual(span(50), span(100) * 2, delta=0.05)

    def test_the_scale_bar_is_the_length_it_says_it_is(self):
        """The only check a person has on a printer set to 'fit to page'."""
        from twin import sheets
        sh = sheets.Sheet(paper="A3")
        mm = sh.scale_bar(20.0, 20.0, 100, metres=5.0)
        self.assertAlmostEqual(mm, 50.0, places=6)
        xs = [p[0] for i in sh.items if i["op"] == "poly" for p in i["pts"]]
        self.assertAlmostEqual(max(xs) - min(xs), 50.0, places=6)

    def test_a_non_standard_scale_is_refused_not_quietly_used(self):
        from twin import sheets
        with self.assertRaises(sheets.SheetError) as cm:
            sheets.pick_scale(6, 10, 300, 250, prefer=87)
        self.assertIn("standard scale", str(cm.exception))

    def test_a_requested_scale_that_does_not_fit_is_refused(self):
        """Falling back silently is how one set ends up at two scales."""
        from twin import sheets
        self.assertIsNone(sheets.pick_scale(30, 30, 300, 250, prefer=50))

    def test_every_sheet_in_a_set_is_at_the_same_scale(self):
        from twin import sheets
        built = sheets.sheet_set(self._bld(), paper="A3")
        scales = {s.scale for s in built["sheets"] if s.scale}
        self.assertEqual(len(scales), 1, f"mixed scales in one set: {scales}")

    def test_a_building_too_big_for_the_paper_is_refused_not_shrunk(self):
        from twin import sheets, model, geodesy as g
        f = g.LocalFrame(52.4856, -1.8476)
        ring = [list(f.to_lonlat(x, y)) for x, y in
                [(0, 0), (200, 0), (200, 300), (0, 300), (0, 0)]]
        big = model.from_footprint({
            "type": "Feature", "id": "way/2", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [ring]}})
        with self.assertRaises(sheets.SheetError) as cm:
            sheets.plan_sheet(big, 0, paper="A4")
        self.assertIn("will not fit", str(cm.exception))

    def test_a_missing_address_prints_as_missing_not_as_blank(self):
        from twin import sheets
        bld = self._bld()
        bld.address = None
        sh = sheets.plan_sheet(bld, 0)
        self.assertIn(sheets.NOT_AVAILABLE, self._texts(sh))

    def test_the_sheet_carries_the_attribution_the_licence_requires(self):
        """An ODbL footprint on a sheet issued to a council is exactly
        the redistribution the licence attaches a condition to."""
        from twin import sheets
        sh = sheets.plan_sheet(self._bld(), 0)
        credit = " ".join(self._texts(sh))
        self.assertIn("OpenStreetMap", credit)
        self.assertIn("way/121198175", credit)

    def test_an_unknown_licence_is_flagged_not_credited_by_guesswork(self):
        from twin import sheets
        bld = self._bld()
        bld.source = dict(bld.source, licence="something-made-up")
        credit = " ".join(self._texts(sheets.plan_sheet(bld, 0)))
        self.assertIn("IS NOT IN THE REGISTRY", credit)
        self.assertNotIn("OpenStreetMap", credit)

    def test_a_model_with_no_provenance_says_so_rather_than_inventing_one(self):
        from twin import sheets
        bld = self._bld()
        bld.source = None
        sh = sheets.plan_sheet(bld, 0)
        self.assertIn("Geometry source not recorded",
                      " ".join(self._texts(sh)))

    def test_every_sheet_says_it_is_preliminary_until_told_otherwise(self):
        from twin import sheets
        for sh in sheets.sheet_set(self._bld())["sheets"]:
            self.assertIn("PRELIMINARY — NOT FOR CONSTRUCTION",
                          " ".join(self._texts(sh)), sh.title)

    def test_dimensions_are_figured_in_millimetres(self):
        from twin import sheets
        sh = sheets.plan_sheet(self._bld(), 0, scale=100)
        t = self._texts(sh)
        self.assertIn("14000", t, "the 14 m overall depth is not figured")
        self.assertIn("6000", t)
        self.assertNotIn("14,000", t,
                         "a separator reads as a decimal point on a "
                         "photocopy")

    def test_the_section_is_cut_across_the_span_not_along_it(self):
        from twin import sheets
        cut = sheets.section_line(self._bld())
        # The house is 6 wide and 10 deep, so the span is x: the cut must
        # run across x, at a constant y.
        self.assertEqual(cut["axis"], "x")
        self.assertTrue(0 < cut["at"] < 10)

    def test_a_second_section_is_cut_when_the_first_misses_the_new_work(self):
        """A set whose only section does not cut the extension is a set
        that has not been checked."""
        from twin import sheets
        cuts = sheets.section_lines(self._bld())
        self.assertEqual(len(cuts), 2)
        self.assertEqual([c["label"] for c in cuts], ["A-A", "B-B"])
        crossed = sheets._crossed(self._bld(), cuts[1]["axis"],
                                  cuts[1]["at"])
        self.assertEqual(len(crossed), 2,
                         "B-B still does not pick up the extension")

    def test_one_section_only_when_one_cut_catches_everything(self):
        from twin import sheets
        self.assertEqual(len(sheets.section_lines(self._bld(extend=False))), 1)

    def test_the_section_reports_real_storey_and_ridge_heights(self):
        from twin import sheets
        bld = self._bld()
        sh = sheets.section_sheet(bld)
        t = self._texts(sh)
        self.assertIn("+2650", t)
        self.assertIn("+5300", t)
        self.assertIn(f"+{round(bld.ridge_m() * 1000):.0f}", t,
                      f"ridge is {bld.ridge_m():.3f} m; markers were {t}")

    def test_the_roof_height_is_computed_not_assumed(self):
        from twin import sheets
        bld = self._bld()
        b = bld.block("existing")
        top = (b.base_level + b.storeys) * b.storey_height
        # A 30 degree gable on a 6 m span peaks at 3 m of run.
        mid = sheets.roof_z(b, b.x + b.width / 2, b.y + b.depth / 2)
        eave = sheets.roof_z(b, b.x, b.y + b.depth / 2)
        self.assertAlmostEqual(eave, top, places=6)
        self.assertAlmostEqual(mid, top + 3.0 * math.tan(math.radians(30)),
                               places=6)

    def test_a_rear_extension_is_not_drawn_on_the_front_elevation(self):
        """It stands behind the house. Drawing it on the front says a
        mass exists in front of the building that does not."""
        from twin import sheets
        sh = sheets.elevation_sheet(self._bld(), "front")
        user_ink = sheets.CLASS_INK["user"]
        drawn = [i for i in sh.items
                 if i["op"] in ("line", "poly")
                 and tuple(i["ink"]) == user_ink]
        self.assertFalse(drawn, "the rear extension is on the front elevation")
        self.assertIn("Not visible on this elevation",
                      " ".join(self._texts(sh)))

    def test_the_rear_elevation_shows_the_extension_and_clips_the_house(self):
        from twin import sheets
        bld = self._bld()
        sh = sheets.elevation_sheet(bld, "rear")
        user_ink = sheets.CLASS_INK["user"]
        self.assertTrue([i for i in sh.items
                         if i["op"] in ("line", "poly")
                         and tuple(i["ink"]) == user_ink],
                        "the extension is missing from the rear elevation")
        # Nothing of the house may be drawn below the extension's roof:
        # its walls are behind that.
        ext = [b for b in bld.blocks if b.id != "existing"][0]
        hides_to = max(sheets.roof_z(ext, ext.x + ext.width / 2, v)
                       for v in (ext.y, ext.y + ext.depth))
        floor = min(p[1] for i in sh.items if i["op"] == "poly"
                    for p in i["pts"])
        house_ink = sheets.CLASS_INK[bld.block("existing").classification]
        lowest = min((min(i["a"][1], i["b"][1]) if i["op"] == "line"
                      else min(p[1] for p in i["pts"]))
                     for i in sh.items if i["op"] in ("line", "poly")
                     and tuple(i["ink"]) == house_ink)
        # in paper mm above the drawing's own ground line
        self.assertGreater(lowest - floor, hides_to * 1000.0 / sh.scale * 0.8,
                           "the house is drawn through the extension")

    def test_the_schedules_count_what_is_actually_in_the_model(self):
        from twin import sheets
        bld = self._bld()
        sh = sheets.schedule_sheet(bld)
        t = " ".join(self._texts(sh))
        for r in bld.rooms_on(0):
            self.assertIn(r.name, t)
        self.assertIn(f"{sum(r.area() for r in bld.rooms):.2f}", t,
                      "the room schedule does not total")

    def test_an_empty_schedule_says_so_instead_of_printing_nothing(self):
        from twin import sheets
        sh = sheets.schedule_sheet(self._bld(rooms=False))
        t = " ".join(self._texts(sh))
        self.assertIn("no rooms drawn", t)
        self.assertIn("no windows or doors placed yet", t)

    def test_the_set_covers_plans_sections_elevations_and_schedules(self):
        from twin import sheets
        m = sheets.sheet_set(self._bld())["manifest"]
        kinds = {n["number"][:2] for n in m}
        self.assertEqual(kinds, {"PL", "SE", "EL", "SC"})
        self.assertEqual(len([n for n in m if n["number"].startswith("EL")]),
                         4, "an elevation is missing")

    def test_the_pdf_is_a_real_pdf_with_one_page_per_sheet(self):
        from twin import sheets
        built = sheets.sheet_set(self._bld())
        pdf = sheets.render_pdf(built["sheets"])
        self.assertTrue(pdf.startswith(b"%PDF-1."))
        self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"/Type /Pages", pdf)
        self.assertIn(("/Count %d" % len(built["sheets"])).encode(), pdf)
        self.assertIn(b"startxref", pdf)

    def test_the_page_is_the_paper_size_it_claims(self):
        from twin import sheets
        pdf = sheets.render_pdf([sheets.plan_sheet(self._bld(), 0,
                                                   paper="A3")])
        # A3 landscape: 420 x 297 mm in points, to two decimals.
        self.assertIn(b"/MediaBox [0 0 1190.551 841.890]", pdf)

    def test_an_em_dash_survives_the_encoding(self):
        """It came out as "?" until WinAnsi's high bytes were mapped, and
        a title block reading "Floor plan ? level 0" is not issuable."""
        from twin import sheets
        pdf = sheets.render_pdf([sheets.plan_sheet(self._bld(), 0)],
                                compress=False)
        self.assertIn(rb"\227", pdf)
        self.assertNotIn(b"Floor plan ? level", pdf)

    def test_text_width_is_measured_against_the_font_not_the_cap_height(self):
        from twin import sheets
        # 3.5 mm capitals in Helvetica: ten zeros are about 26 mm, not 17.5.
        w = sheets.text_width("0000000000", sheets.TEXT_L)
        self.assertGreater(w, 22.0)
        self.assertLess(w, 28.0)

    def test_nothing_is_drawn_outside_the_paper(self):
        from twin import sheets
        for sh in sheets.sheet_set(self._bld())["sheets"]:
            pts = [p for i in sh.items if i["op"] == "poly" for p in i["pts"]]
            pts += [i["a"] for i in sh.items if i["op"] == "line"]
            pts += [i["b"] for i in sh.items if i["op"] == "line"]
            for x, y in pts:
                self.assertTrue(-1.0 <= x <= sh.w + 1.0
                                and -1.0 <= y <= sh.h + 1.0,
                                f"{sh.title}: ({x}, {y}) is off {sh.paper}")

    def test_a_drawing_set_reports_what_it_could_not_draw(self):
        from twin import sheets
        out = sheets.drawing_set(self._bld())
        self.assertEqual(out["problems"], [])
        self.assertTrue(out["pdf"])
        self.assertEqual(len(out["manifest"]),
                         len(sheets.sheet_set(self._bld())["sheets"]))


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


class TestImpression(unittest.TestCase):
    """The picture is the one output nobody reads the caption on.

    So these tests are about the caption and the refusals, not about
    whether the brick looks nice. A generated image that loses its
    disclaimer becomes a photograph of a house that does not exist.
    """

    def setUp(self):
        from twin.providers import visual
        self.v = visual
        self._key = os.environ.pop("GEMINI_API_KEY", None)

    def tearDown(self):
        if self._key is not None:
            os.environ["GEMINI_API_KEY"] = self._key
        else:
            os.environ.pop("GEMINI_API_KEY", None)

    def test_with_no_key_it_says_which_key_and_does_not_pretend(self):
        ok, why = self.v.usable()
        self.assertFalse(ok)
        self.assertIn("GEMINI_API_KEY", why)

    def test_it_refuses_rather_than_returning_a_stand_in_image(self):
        with self.assertRaises(self.v.NotAvailable):
            self.v.impression(b"\x89PNG fake", {})

    def test_an_empty_render_is_refused_before_any_call_is_made(self):
        os.environ["GEMINI_API_KEY"] = "test-key-not-used"
        with self.assertRaises(self.v.NotAvailable) as cm:
            self.v.impression(b"", {"width_m": 8.0})
        self.assertIn("massing render", str(cm.exception))

    def test_the_licence_is_registered_and_permits_the_use(self):
        # An unregistered licence key raises; that is the whole point of
        # the registry, and a provider that skipped it would be the one
        # source in the app whose terms were never stated.
        lic = licences.get("google-gemini-api")
        self.assertTrue(lic.commercial)
        self.assertEqual([], licences.check("google-gemini-api",
                                            licences.USE_RENDER,
                                            licences.USE_COMMERCIAL,
                                            raises=False))

    def test_the_prompt_carries_the_measured_numbers_as_constraints(self):
        text = self.v.brief({"width_m": 9.91, "depth_m": 13.37, "storeys": 2,
                             "eaves_m": 5.3, "ridge_m": 8.16,
                             "roof_kind": "gabled", "place": "Birmingham"})
        self.assertIn("9.91", text)
        self.assertIn("13.37", text)
        self.assertIn("2 storeys", text)
        self.assertIn("8.16", text)
        self.assertIn("gabled", text)
        # and it must forbid the model redrawing the volume
        self.assertIn("Do NOT add", text)

    def test_a_zero_quota_is_reported_as_billing_not_as_try_again(self):
        """`limit: 0` will never clear by waiting, and telling a user to
        retry a permanent refusal wastes their afternoon."""
        class E:
            code = 429
            def read(self):
                return json.dumps({"error": {"message":
                    "Quota exceeded ... limit: 0, model: x"}}).encode()
        why = self.v._http_reason("gemini-3-pro-image", E())
        self.assertIn("billing", why.lower())
        self.assertNotIn("try again", why.lower())

    def test_the_disclaimer_is_burned_into_the_pixels(self):
        """Not into the HTML beside them. The pixels are what gets
        screenshotted into a message to a client."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        buf = io.BytesIO()
        Image.new("RGB", (200, 120), (90, 110, 130)).save(buf, format="PNG")
        out = self.v.stamp(buf.getvalue())
        grew = Image.open(io.BytesIO(out))
        self.assertEqual(200, grew.size[0])
        self.assertGreater(grew.size[1], 120)
        # the band is really drawn on, not just empty space
        band = grew.crop((0, 120, 200, grew.size[1]))
        self.assertGreater(len(band.getcolors(maxcolors=100000) or []), 1)

    def test_the_disclaimer_fits_the_width_instead_of_running_off_it(self):
        """Half a disclaimer is worse than none: the half that survives
        a crop reads 'ARTIST'S IMPRESSION - generated, not a photo...'."""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            self.skipTest("Pillow not installed")
        for width in (200, 420, 640, 1400):
            buf = io.BytesIO()
            Image.new("RGB", (width, 300), (90, 110, 130)).save(buf, "PNG")
            out = Image.open(io.BytesIO(self.v.stamp(buf.getvalue())))
            band = out.crop((0, 300, width, out.size[1]))
            # find the rightmost column carrying caption ink
            px = band.load()
            last = 0
            for x in range(width):
                for y in range(band.size[1]):
                    if px[x, y] != (14, 14, 16):
                        last = x
                        break
            self.assertLess(last, width - 2,
                            f"caption reaches the edge at width {width}")

    def test_the_place_is_taken_from_the_address_not_invented(self):
        from twin import api as api_mod
        place = api_mod._place_from(
            "90, Streetly Lane, Sutton Coldfield, Four Oaks, Birmingham, "
            "West Midlands, England, B74 4TB, United Kingdom")
        self.assertIn("England", place)
        self.assertNotIn("United Kingdom", place)
        self.assertNotIn("90", place)

    def test_an_env_file_never_overwrites_a_real_environment_secret(self):
        from twin import api as api_mod
        import tempfile
        os.environ["TWIN_TEST_TOKEN"] = "from-the-container"
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".env",
                                             delete=False) as fh:
                fh.write("# a comment\nTWIN_TEST_TOKEN=from-the-file\n"
                         "TWIN_TEST_NEW=fresh\nnot a pair\n")
                path = fh.name
            api_mod._load_env(path)
            self.assertEqual("from-the-container",
                             os.environ["TWIN_TEST_TOKEN"])
            self.assertEqual("fresh", os.environ["TWIN_TEST_NEW"])
        finally:
            os.environ.pop("TWIN_TEST_TOKEN", None)
            os.environ.pop("TWIN_TEST_NEW", None)
            os.unlink(path)

    def test_a_missing_env_file_is_not_an_error(self):
        from twin import api as api_mod
        self.assertEqual(0, api_mod._load_env("/no/such/file/at/all"))

    # -- what the review found -------------------------------------------

    def test_quoted_env_values_lose_their_quotes(self):
        """KEY="abc" is the usual .env spelling; a key sent with the
        quotes attached is refused upstream with no hint why."""
        from twin import api as api_mod
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".env",
                                         delete=False) as fh:
            fh.write('TWIN_TEST_Q1="abc"\nTWIN_TEST_Q2=\'xyz\'\n'
                     'TWIN_TEST_Q3="unterminated\n')
            path = fh.name
        try:
            api_mod._load_env(path)
            self.assertEqual("abc", os.environ["TWIN_TEST_Q1"])
            self.assertEqual("xyz", os.environ["TWIN_TEST_Q2"])
            self.assertEqual('"unterminated', os.environ["TWIN_TEST_Q3"])
        finally:
            for k in ("TWIN_TEST_Q1", "TWIN_TEST_Q2", "TWIN_TEST_Q3"):
                os.environ.pop(k, None)
            os.unlink(path)

    def test_the_place_is_the_town_not_the_postcode(self):
        from twin import api as api_mod
        place = api_mod._place_from(
            "90, Streetly Lane, Sutton Coldfield, Four Oaks, Birmingham, "
            "West Midlands, England, B74 4TB, United Kingdom")
        self.assertEqual("Birmingham, West Midlands, England", place)
        self.assertEqual("England", api_mod._place_from(""))
        self.assertEqual("England", api_mod._place_from("12"))

    def test_a_non_string_render_is_a_refusal_not_a_500(self):
        from twin import api as api_mod
        c = api_mod.app.test_client()
        r = c.post("/api/project", json={"lat": 52.589059, "lon": -1.857172})
        if not r.get_json().get("available"):
            self.skipTest("no building data offline")
        pid = r.get_json()["project_id"]
        for bad in (5, None, ["x"], {"a": 1}):
            r = c.post(f"/api/project/{pid}/impression",
                       json={"massing_png": bad})
            self.assertEqual(200, r.status_code, bad)
            self.assertFalse(r.get_json()["available"])
            self.assertIn("massing render", r.get_json()["reason"])

    def test_an_oversize_render_is_refused_before_it_is_decoded(self):
        from twin import api as api_mod
        c = api_mod.app.test_client()
        r = c.post("/api/project", json={"lat": 52.589059, "lon": -1.857172})
        if not r.get_json().get("available"):
            self.skipTest("no building data offline")
        pid = r.get_json()["project_id"]
        called = []
        orig = api_mod.base64.b64decode
        api_mod.base64.b64decode = lambda *a, **k: called.append(1) or orig(*a, **k)
        try:
            r = c.post(f"/api/project/{pid}/impression",
                       json={"massing_png": "A" * (17 * 1024 * 1024)})
        finally:
            api_mod.base64.b64decode = orig
        self.assertEqual("REFUSED", r.get_json()["status"])
        self.assertEqual([], called, "decoded the payload it refused")

    def test_a_dead_upstream_is_a_502_not_an_empty_answer(self):
        """api._out keys the 502 on the phrase 'failed to reach'. A dead
        Gemini used to say 'could not reach' and came back 200, so
        monitoring could not tell a dead provider from an empty field."""
        from twin import api as api_mod
        import urllib.error
        def boom(*a, **k):
            raise urllib.error.URLError("name resolution failed")
        orig = self.v.urllib.request.urlopen
        self.v.urllib.request.urlopen = boom
        os.environ["GEMINI_API_KEY"] = "test"
        try:
            with self.assertRaises(self.v.NotAvailable) as cm:
                self.v.impression(b"png", {})
        finally:
            self.v.urllib.request.urlopen = orig
        self.assertIn("failed to reach", str(cm.exception))
        r = api_mod._out({"available": False, "reason": str(cm.exception)})
        self.assertEqual(502, r.status_code)

    def test_a_non_json_reply_falls_through_to_the_next_model(self):
        """A proxy's HTML error page on model one must not abort the
        chain as a 400 'bad request' blamed on our own client."""
        seen = []
        def post(model, *a, **k):
            seen.append(model)
            if len(seen) == 1:
                raise self.v.NotAvailable(f"{model}: the reply was not JSON")
            raise self.v.NotAvailable(f"{model}: no")
        orig = self.v._post
        self.v._post = post
        os.environ["GEMINI_API_KEY"] = "test"
        try:
            with self.assertRaises(self.v.NotAvailable):
                self.v.impression(b"png", {})
        finally:
            self.v._post = orig
        self.assertEqual(list(self.v.MODELS), seen)

    def test_the_chain_stops_when_the_time_budget_is_spent(self):
        """Three models at 300 s each was a fifteen-minute ceiling on a
        button that promised a minute."""
        clock = [0.0]
        orig_mono, orig_post = self.v.time.monotonic, self.v._post
        seen = []
        def post(model, *a, timeout=None, **k):
            seen.append((model, timeout))
            clock[0] += self.v.BUDGET_S          # this one hung
            raise self.v.NotAvailable(f"{model}: timed out")
        self.v.time.monotonic = lambda: clock[0]
        self.v._post = post
        os.environ["GEMINI_API_KEY"] = "test"
        try:
            with self.assertRaises(self.v.NotAvailable) as cm:
                self.v.impression(b"png", {})
        finally:
            self.v.time.monotonic, self.v._post = orig_mono, orig_post
        self.assertEqual(1, len(seen), "kept calling after the budget")
        self.assertLessEqual(seen[0][1], self.v.TIMEOUT_S)
        self.assertIn("not tried", str(cm.exception))
        self.assertLessEqual(3 * self.v.TIMEOUT_S, 300)

    def test_stamp_refuses_bytes_that_are_not_an_image(self):
        with self.assertRaises(self.v.NotAvailable):
            self.v.stamp(b"this is not a png")


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
