"""Building footprints, worldwide, from OpenStreetMap via Overpass.

This is the layer the whole product stands on: without a real footprint
there is no property to select, measure or extend. It returns polygons
in WGS84 with their OSM tags intact, because the tags carry the only
building metadata OSM has — `building:levels`, `height`, `roof:shape` —
and those feed the 3D stage rather than being invented there.

MIRRORS, NOT A HOST. The main overpass-api.de endpoint is unreachable
from some networks (including this project's own container), so the
provider holds an ordered list and fails over. The first mirror that
answers wins and is remembered for the process, which keeps the retry
cost off every subsequent call.

WHAT IT CANNOT TELL YOU. OSM buildings are traced from imagery by
volunteers. Positional accuracy is typically a metre or two against
aerial, worse where the imagery was oblique, and the trace often follows
the ROOF EDGE rather than the wall face — which is why `accuracy_m` is
stated at 3 m and the classification is verified-as-published rather
than surveyed. A building absent from OSM is absent, not zero: that is a
Missing with the reason, and the UI offers the draw-it-yourself path.
"""
from __future__ import annotations

import json
import os

import requests

from .. import cache as cache_mod
from ..provenance import CLASS_VERIFIED, Missing, Provenance
from .base import (CAP_AVAILABLE, CAP_NONE, Capability, Provider, sourced,
                   transport_missing)

MIRRORS = [m for m in os.environ.get(
    "TWIN_OVERPASS",
    "https://overpass.kumi.systems/api/interpreter,"
    "https://overpass.private.coffee/api/interpreter,"
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter,"
    "https://overpass-api.de/api/interpreter").split(",") if m.strip()]
UA = os.environ.get("TWIN_USER_AGENT", "triposr-twin/0.1")
LICENCE = "overpass-policy"
MIN_INTERVAL = float(os.environ.get("TWIN_OVERPASS_INTERVAL", "1.1"))

# OSM tracing accuracy against aerial imagery. Stated, not guessed at
# render time: the map draws a tolerance band from this number.
FOOTPRINT_ACCURACY_M = 3.0

_QUERY = """[out:json][timeout:{timeout}];
(way["building"]({s},{w},{n},{e});
 relation["building"]["type"="multipolygon"]({s},{w},{n},{e}););
out body geom;"""


class OverpassProvider(Provider):
    name = "overpass"
    countries = ("*",)
    capabilities = {
        "building": Capability(
            CAP_AVAILABLE,
            "OpenStreetMap building footprints worldwide. Completeness "
            "varies: near-total in Western Europe, partial elsewhere. "
            "Traced from imagery, so edges follow the roof, not the wall.",
            LICENCE),
        "parcel": Capability(
            CAP_NONE,
            "OSM holds no legal land parcels; those come from a national "
            "cadastre where one is published."),
    }

    def __init__(self, cache=None, session=None):
        self.cache = cache or cache_mod.default()
        self.session = session or requests.Session()
        self._live_mirror = None

    def _post(self, query: str, timeout=45):
        key = cache_mod.Cache.key(self.name, query)
        hit = self.cache.get(key)
        if hit is not None:
            return hit, True
        order = ([self._live_mirror] if self._live_mirror else []) + \
                [m for m in MIRRORS if m != self._live_mirror]
        last = None
        for mirror in order:
            try:
                self.cache.throttle(self.name, MIN_INTERVAL)
                r = self.session.post(mirror, data={"data": query},
                                      headers={"User-Agent": UA},
                                      timeout=timeout)
                r.raise_for_status()
                data = r.json()
                self._live_mirror = mirror
                self.cache.put(key, self.name, LICENCE, data, ttl=14 * 86400)
                return data, False
            except Exception as e:                # try the next mirror
                last = e
        raise RuntimeError(
            f"all {len(order)} Overpass mirrors failed; last: {last}")

    def _prov(self, el, cached: bool):
        return Provenance(
            source_provider=self.name,
            source_dataset="openstreetmap",
            source_identifier=f"{el.get('type')}/{el.get('id')}",
            licence=LICENCE,
            observation_date=None,
            accuracy_m=FOOTPRINT_ACCURACY_M,
            confidence=0.8,
            processing_method="OSM way geometry, as traced"
                              + (" (cached)" if cached else ""),
        )

    @staticmethod
    def _ring(geom):
        ring = [[p["lon"], p["lat"]] for p in geom or []]
        if len(ring) < 4:
            return None
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        return ring

    def buildings(self, west, south, east, north):
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            return Missing("bbox is not on the earth", asked=(self.name,),
                           detail=f"{west},{south},{east},{north}")
        # A wide bbox asks a volunteer server for a city. Refuse rather
        # than issue it: the policy limit is real and the UI has no use
        # for ten thousand footprints at once.
        if (east - west) * (north - south) > 0.0025:      # ~ 0.05 deg square
            return Missing(
                "area too large for a footprint query",
                asked=(self.name,),
                detail="Zoom in: buildings load below about a 3 km box.")
        q = _QUERY.format(s=south, w=west, n=north, e=east, timeout=45)
        try:
            data, cached = self._post(q)
        except Exception as e:
            return transport_missing(self.name, "building", e)
        feats = []
        for el in data.get("elements", []):
            tags = el.get("tags", {}) or {}
            if el.get("type") == "way":
                ring = self._ring(el.get("geometry"))
                if not ring:
                    continue
                geometry = {"type": "Polygon", "coordinates": [ring]}
            elif el.get("type") == "relation":
                outers = [self._ring(m.get("geometry"))
                          for m in el.get("members", [])
                          if m.get("role") == "outer"]
                outers = [r for r in outers if r]
                if not outers:
                    continue
                geometry = {"type": "MultiPolygon",
                            "coordinates": [[r] for r in outers]}
            else:
                continue
            feats.append({
                "type": "Feature",
                "id": f"{el['type']}/{el['id']}",
                "geometry": geometry,
                "properties": {
                    "osm_id": f"{el['type']}/{el['id']}",
                    "building": tags.get("building"),
                    "name": tags.get("name"),
                    "housenumber": tags.get("addr:housenumber"),
                    "street": tags.get("addr:street"),
                    "postcode": tags.get("addr:postcode"),
                    # Height metadata OSM sometimes carries. Passed through
                    # UNCONVERTED where absent — the 3D stage must see a
                    # null and say so, not receive a default storey count.
                    "levels": tags.get("building:levels"),
                    "height_m": tags.get("height"),
                    "roof_shape": tags.get("roof:shape"),
                    "roof_levels": tags.get("roof:levels"),
                    "provenance": self._prov(el, cached).as_dict(),
                },
            })
        if not feats:
            return Missing(
                "no buildings mapped here in OpenStreetMap",
                asked=(self.name,),
                detail="The area may be unmapped rather than empty. You can "
                       "trace the footprint yourself and it will be stored "
                       "as user-created geometry.")
        prov = Provenance(
            source_provider=self.name, source_dataset="openstreetmap",
            source_identifier=f"bbox/{west:.5f},{south:.5f},{east:.5f},{north:.5f}",
            licence=LICENCE, accuracy_m=FOOTPRINT_ACCURACY_M, confidence=0.8,
            processing_method=f"Overpass way+relation query, {len(feats)} "
                              f"features" + (" (cached)" if cached else ""))
        return sourced({"type": "FeatureCollection", "features": feats},
                       prov, CLASS_VERIFIED)
