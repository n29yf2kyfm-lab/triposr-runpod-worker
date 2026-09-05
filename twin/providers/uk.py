"""United Kingdom: the country this platform can currently go deepest on.

Three real, free, government-published sources, all Open Government
Licence, all keyless except the EPC register:

  postcodes.io     postcode -> coordinates, ONS/OS Open data behind it
  EA National      1 m LIDAR digital surface and terrain models over
  LIDAR Programme  ~99% of England — the layer that lets a roof be
                   MEASURED rather than assumed
  EPC register     the RdSAP survey lodged against a dwelling: floor
                   areas, storey heights, party wall length, wall
                   construction (API key required, free on registration)

WHAT MAKES THE UK SPECIAL IS THE LIDAR. Almost nowhere else publishes a
national 1 m surface model for free. It is why a UK property can carry
verified ridge height and a derived roof pitch, and why the capability
matrix for other countries reads LIMITED on elevation until an
equivalent national dataset is wired in.

The heavy lifting already exists in the building/ package (roof.py's
WCS client, osgb.py's grid maths, roof_geometry.py's plane fitting).
This adapter's job is to present it behind the common interface with
provenance attached, not to reimplement it.
"""
from __future__ import annotations

import math
import os
import sys

import requests

from .. import cache as cache_mod
from ..provenance import (CLASS_DERIVED, CLASS_VERIFIED, Missing, Provenance)
from .base import (CAP_AVAILABLE, CAP_LIMITED, CAP_NONE, CAP_RESTRICTED,
                   Capability, Provider, sourced, transport_missing)

_BUILDING = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "building")
if _BUILDING not in sys.path:
    sys.path.insert(0, _BUILDING)

POSTCODES_IO = "https://api.postcodes.io"
OGL = "ogl-3.0"


class UKProvider(Provider):
    name = "uk-gov-open"
    countries = ("GB", "UK")
    capabilities = {
        "address": Capability(
            CAP_LIMITED,
            "postcodes.io resolves a POSTCODE to its centroid (typically "
            "a few dozen addresses). Individual addresses need OS "
            "AddressBase, which is licensed, not open.", OGL),
        "elevation": Capability(
            CAP_AVAILABLE,
            "Environment Agency National LIDAR Programme: 1 m DSM and DTM "
            "over ~99% of England, +/-15 cm vertical. Wales and Scotland "
            "have separate national programmes not yet wired in.", OGL),
        "parcel": Capability(
            CAP_RESTRICTED,
            "HM Land Registry holds the title plans, but INSPIRE polygons "
            "were withdrawn and the current product is licensed per-use. "
            "Not open data."),
        "planning": Capability(
            CAP_LIMITED,
            "Listed buildings, conservation areas and flood zones publish "
            "openly; local plan policies and live applications vary by "
            "council and mostly have no API.", OGL),
        "utilities": Capability(
            CAP_RESTRICTED,
            "UK utility records are obtained through statutory enquiry "
            "(LSBUD / individual DNOs and water companies), not a public "
            "feed. Buried services must come from those searches or from "
            "an on-site scan."),
        "floorplans": Capability(
            CAP_LIMITED,
            "The EPC register publishes surveyed floor AREAS and storey "
            "heights per dwelling, which constrain a plan but do not give "
            "internal wall positions. No national floor-plan dataset "
            "exists.", OGL),
        "building": Capability(
            CAP_LIMITED,
            "OS Open data has building outlines; the richer OS MasterMap "
            "is licensed. OSM via the Overpass provider is used instead."),
    }

    def __init__(self, cache=None, session=None):
        self.cache = cache or cache_mod.default()
        self.session = session or requests.Session()

    # -- postcode geocoding ---------------------------------------------
    def geocode(self, query: str, *, country=None, limit=5):
        pc = (query or "").strip().upper().replace(" ", "")
        # Only claim the query if it looks like a UK postcode; anything
        # else belongs to the worldwide geocoder, and half-answering it
        # here would shadow a better match.
        if not (5 <= len(pc) <= 7 and pc[0].isalpha() and pc[-1].isalpha()
                and any(c.isdigit() for c in pc)):
            return Missing(
                "not a UK postcode", asked=(self.name,),
                detail="This provider resolves postcodes only.")
        key = cache_mod.Cache.key(self.name, "pc", pc)
        hit = self.cache.get(key)
        try:
            if hit is None:
                r = self.session.get(f"{POSTCODES_IO}/postcodes/{pc}",
                                     timeout=15)
                if r.status_code == 404:
                    return Missing(
                        f"{query!r} is not a live UK postcode",
                        asked=(self.name,),
                        detail="Terminated postcodes and typos both land "
                               "here; check it on the Royal Mail finder.")
                r.raise_for_status()
                hit = r.json()
                self.cache.put(key, self.name, OGL, hit, ttl=90 * 86400)
        except Exception as e:
            return transport_missing(self.name, "address", e)
        res = hit.get("result") or {}
        prov = Provenance(
            source_provider=self.name, source_dataset="postcodes.io",
            source_identifier=res.get("postcode"), licence=OGL,
            accuracy_m=100.0, confidence=0.9,
            processing_method="postcode unit centroid (ONS/OS Open data)")
        return sourced([{
            "label": ", ".join(x for x in (res.get("postcode"),
                                           res.get("admin_district"),
                                           res.get("country")) if x),
            "lat": res.get("latitude"), "lon": res.get("longitude"),
            "type": "postcode", "country_code": "GB",
            "postcode": res.get("postcode"), "geometry": None,
            # A postcode centroid is NOT a house. Said in the payload so
            # the UI cannot present it as one.
            "accuracy_m": 100.0,
            "note": "postcode unit centroid — covers roughly 15 addresses; "
                    "select the building to identify the property",
            "provenance": prov.as_dict(),
        }], prov, CLASS_VERIFIED)

    # -- the layer that makes UK properties measurable -------------------
    def elevation(self, lat: float, lon: float):
        try:
            import osgb
            import roof as roofmod
        except Exception as e:
            return Missing("elevation engine unavailable",
                           asked=(self.name,), detail=str(e))
        try:
            e, n = osgb.latlon_to_easting_northing(lat, lon)
        except Exception as ex:
            return Missing("point is not on the British National Grid",
                           asked=(self.name,), detail=str(ex))
        # CACHE THE RASTER, SAMPLE AT THE TRUE POINT. Snapping the QUERY
        # point to a 20 m grid shared cache entries and moved the sample
        # up to 14 m — off a 7 m-wide roof and onto the road, which came
        # back as a height above ground of MINUS 0.22 m. A negative
        # building height is the kind of impossible number that only
        # shows up if you look, so the box is snapped (for reuse) and the
        # sampling stays on the real coordinates.
        eq, nq = round(e / 50.0) * 50, round(n / 50.0) * 50
        key = cache_mod.Cache.key(self.name, "elevgrid", eq, nq)
        hit = self.cache.get(key)
        if hit is None:
            try:
                # fetch_surface(bbox, wcs_url) returning [(E, N, z)] — the
                # real signature in roof.py. An earlier draft called a
                # `fetch_lidar(bbox, product=...)` that does not exist,
                # and because the provider converts every exception into
                # Missing, the AttributeError surfaced only as "no
                # provider returned elevation" on screen. Missing must
                # never be a hiding place for a programming error, so the
                # detail now carries the exception type through.
                bbox = osgb.bbox_around(eq, nq, radius_m=60.0)
                dsm = roofmod.fetch_surface(bbox, roofmod.EA_WCS)
                dtm = roofmod.fetch_surface(bbox, roofmod.EA_DTM_WCS)
            except Exception as ex:
                return transport_missing(self.name, "elevation", ex)
            if not dsm or not dtm:
                return Missing(
                    "no LIDAR coverage at this point",
                    asked=(self.name,),
                    detail="The National LIDAR Programme covers ~99% of "
                           "England; Wales and Scotland are separate "
                           "programmes not yet connected.")
            hit = {"dsm": [[round(p[0], 1), round(p[1], 1), round(p[2], 2)]
                           for p in dsm],
                   "dtm": [[round(p[0], 1), round(p[1], 1), round(p[2], 2)]
                           for p in dtm]}
            self.cache.put(key, self.name, OGL, hit, ttl=365 * 86400)

        import statistics

        def _sample(points, k=5):
            near = sorted(points, key=lambda p: (p[0] - e) ** 2
                          + (p[1] - n) ** 2)[:k]
            if not near:
                return None, None
            return (statistics.median(p[2] for p in near),
                    math.sqrt(min((p[0] - e) ** 2 + (p[1] - n) ** 2
                                  for p in near)))

        surface, d_surf = _sample(hit["dsm"])
        # Bare earth under the building: the DTM immediately around the
        # point, not the median of the whole box, which would include a
        # sloping street and bias the height on any gradient.
        ground, _ = _sample(hit["dtm"], k=9)
        if surface is None or ground is None:
            return Missing("LIDAR returned no cells near this point",
                           asked=(self.name,))
        if d_surf is not None and d_surf > 5.0:
            return Missing(
                "nearest LIDAR cell is too far from the point to be it",
                asked=(self.name,),
                detail=f"closest sample {d_surf:.1f} m away")
        prov = Provenance(
            source_provider=self.name,
            source_dataset="EA National LIDAR Programme composite 1m",
            source_identifier=f"EN {e:.0f},{n:.0f}",
            licence=OGL, accuracy_m=1.0, confidence=0.9,
            processing_method="median of the 5 nearest DSM cells and 9 "
                              "nearest DTM cells to the point, +/-15 cm "
                              "stated vertical RMSE")
        value = {
            "ground_m_aod": round(ground, 2),
            "surface_m_aod": round(surface, 2),
            "height_above_ground_m": round(surface - ground, 2),
            "nearest_cell_m": round(d_surf, 2) if d_surf is not None else None,
        }
        return sourced(value, prov, CLASS_DERIVED)
