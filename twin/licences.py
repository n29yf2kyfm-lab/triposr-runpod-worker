"""What each dataset actually permits — checked before it is used.

THE BRIEF SAYS: "Do not add a source simply because it is technically
accessible." This module is how that is enforced rather than promised.
Every provider declares a licence key; `check()` refuses at REGISTRATION
time if the terms do not permit the use the platform puts it to.

The distinction that catches people out is REDISTRIBUTION versus DISPLAY.
Esri's World Imagery renders inside their SDKs under their terms; taking
the tiles, baking them into a file and handing that file to a client is
a different act, and it is the act this project's offline map performs.
That is recorded here as a real restriction, not smoothed over — see
`redistribute` on the esri entry, which is False.

None of this is legal advice, and the summaries are deliberately short
pointers to the actual terms rather than a substitute for reading them.
The `url` on every entry is the operative document.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Licence:
    key: str
    name: str
    url: str
    commercial: bool          # may be used in a commercial product
    attribution: Optional[str]  # required attribution string, if any
    share_alike: bool         # derived DATABASES must be shared alike
    redistribute: bool        # may we hand the raw data on to a client
    cache: bool               # may we store it rather than re-fetch
    notes: str = ""


LICENCES = {
    "odbl-1.0": Licence(
        key="odbl-1.0", name="Open Database License 1.0",
        url="https://opendatacommons.org/licenses/odbl/1-0/",
        commercial=True, attribution="© OpenStreetMap contributors",
        share_alike=True, redistribute=True, cache=True,
        notes="OSM data. Share-alike bites on a DERIVED DATABASE, not on "
              "a produced work such as a drawing. Storing footprints in "
              "our own database and publishing them is a derived "
              "database: attribution plus ODbL terms travel with it."),
    "ogl-3.0": Licence(
        key="ogl-3.0", name="Open Government Licence v3.0",
        url="https://www.nationalarchives.gov.uk/doc/"
            "open-government-licence/version/3/",
        commercial=True,
        attribution="Contains public sector information licensed under "
                    "the Open Government Licence v3.0",
        share_alike=False, redistribute=True, cache=True,
        notes="EA LIDAR, EPC register, Land Registry price paid, "
              "postcodes.io underlying ONS/OS Open data."),
    "esri-world-imagery": Licence(
        key="esri-world-imagery", name="Esri World Imagery (ArcGIS Online)",
        url="https://www.arcgis.com/home/item.html"
            "?id=10df2279f9684e4a9f6a7f08febac2a9",
        commercial=False, attribution="Esri, Maxar, Earthstar Geographics",
        share_alike=False, redistribute=False, cache=False,
        notes="RESTRICTED. Free tiles are for use in Esri's own mapping "
              "products; bulk download, offline caching and handing tiles "
              "on inside an exported file are not granted. This platform "
              "must not ship it to a customer — see the STAGE 0 finding. "
              "Kept in the registry precisely so the check can refuse it."),
    "osm-tile-policy": Licence(
        key="osm-tile-policy", name="OSM Foundation tile usage policy",
        url="https://operations.osmfoundation.org/policies/tiles/",
        commercial=False, attribution="© OpenStreetMap contributors",
        share_alike=False, redistribute=False, cache=False,
        notes="The standard osm.org raster tiles are a volunteer service, "
              "not a CDN for products. Heavy or commercial use requires "
              "your own tile server (the data itself is ODbL and free to "
              "render yourself, which is the compliant route)."),
    # Public-domain and keyed commercial terms — added when the imagery
    # layer needed real sources rather than a borrowed tile endpoint.
    "us-public-domain": Licence(
        key="us-public-domain", name="US Government work (public domain)",
        url="https://www.usgs.gov/information-policies-and-instructions/"
            "copyrights-and-credits",
        commercial=True, attribution="USGS The National Map",
        share_alike=False, redistribute=True, cache=True,
        notes="Works of the US federal government carry no copyright. "
              "USGS asks for credit as a courtesy; we give it."),
    "cc-by-nc-sa-4.0": Licence(
        key="cc-by-nc-sa-4.0", name="Creative Commons BY-NC-SA 4.0",
        url="https://creativecommons.org/licenses/by-nc-sa/4.0/",
        commercial=False,
        attribution="Sentinel-2 cloudless by EOX IT Services GmbH",
        share_alike=True, redistribute=True, cache=True,
        notes="NON-COMMERCIAL. Fine to look at while developing; refused "
              "for a paid product, which is why the check gates it."),
    "esri-keyed": Licence(
        key="esri-keyed", name="Esri ArcGIS Location Platform (keyed)",
        url="https://www.esri.com/en-us/legal/terms/full-master-agreement",
        commercial=True, attribution="Esri, Maxar, Earthstar Geographics",
        share_alike=False, redistribute=False, cache=False,
        notes="THE LICENSED DOOR to the same World Imagery the free tile "
              "endpoint serves without granting rights. A free ArcGIS "
              "Location Platform account issues a key that permits "
              "commercial display. Caching and re-export are still not "
              "granted, so tiles are streamed, never baked into an "
              "exported file."),
    "mapbox-keyed": Licence(
        key="mapbox-keyed", name="Mapbox Terms of Service (keyed)",
        url="https://www.mapbox.com/legal/tos",
        commercial=True, attribution="© Mapbox © Maxar",
        share_alike=False, redistribute=False, cache=False,
        notes="Commercial display permitted under an account; offline "
              "caching and redistribution are not."),
    "maptiler-keyed": Licence(
        key="maptiler-keyed", name="MapTiler Terms (keyed)",
        url="https://www.maptiler.com/terms/",
        commercial=True, attribution="© MapTiler © Planet",
        share_alike=False, redistribute=False, cache=False,
        notes="Commercial display permitted under an account."),
    "os-keyed": Licence(
        key="os-keyed", name="OS Data Hub (keyed)",
        url="https://osdatahub.os.uk/legal/apiTermsConditions",
        commercial=True,
        attribution="© Crown copyright and database rights Ordnance Survey",
        share_alike=False, redistribute=False, cache=False,
        notes="OS OpenData tier is free; Premium is paid. Attribution is "
              "mandatory and specified by OS."),
    "nominatim-policy": Licence(
        key="nominatim-policy", name="Nominatim usage policy (OSM data ODbL)",
        url="https://operations.osmfoundation.org/policies/nominatim/",
        commercial=False, attribution="© OpenStreetMap contributors",
        share_alike=True, redistribute=True, cache=True,
        notes="DATA is ODbL and free. The public ENDPOINT is capped at "
              "1 req/s, needs a real User-Agent, and forbids heavy use — "
              "production must self-host Nominatim or buy a geocoder. "
              "Results may be cached; that is explicitly encouraged."),
    "overpass-policy": Licence(
        key="overpass-policy", name="Overpass API instance policy (data ODbL)",
        url="https://dev.overpass-api.de/",
        commercial=False, attribution="© OpenStreetMap contributors",
        share_alike=True, redistribute=True, cache=True,
        notes="Same shape as Nominatim: ODbL data, volunteer endpoint. "
              "Fine for development and light use; production needs a "
              "self-hosted instance or a planet extract."),
}


# What this platform does with data, which is what the terms are checked
# against. Naming the USE is the point: the same dataset can be fine to
# look at and forbidden to ship.
USE_RENDER = "render"              # draw it on screen, live, from source
USE_CACHE = "cache"                # keep a copy server-side
USE_EXPORT = "export"              # bake it into a file the user keeps
USE_COMMERCIAL = "commercial"      # use it in a paid product


class LicenceError(RuntimeError):
    pass


def get(key: str) -> Licence:
    try:
        return LICENCES[key]
    except KeyError:
        raise LicenceError(
            f"licence {key!r} is not in the registry. Every data source "
            f"must declare terms before it can be used — add it to "
            f"licences.py with the operative URL, or do not use it.")


def check(key: str, *uses: str, raises: bool = True):
    """Does this licence permit these uses? Returns list of refusals."""
    lic = get(key)
    bad = []
    for use in uses:
        ok = {USE_RENDER: True,                       # looking is always ok
              USE_CACHE: lic.cache,
              USE_EXPORT: lic.redistribute,
              USE_COMMERCIAL: lic.commercial}.get(use)
        if ok is None:
            raise LicenceError(f"unknown use {use!r}")
        if not ok:
            bad.append(f"{lic.name} does not permit {use}: {lic.notes}")
    if bad and raises:
        raise LicenceError("; ".join(bad))
    return bad


def attributions(keys) -> list:
    """Deduplicated attribution lines for everything on screen.

    The UI must show these. Attribution is a licence CONDITION, not a
    courtesy, and an unattributed basemap is a breach that happens to
    render correctly.
    """
    out = []
    for k in keys:
        a = LICENCES[k].attribution if k in LICENCES else None
        if a and a not in out:
            out.append(a)
    return out
