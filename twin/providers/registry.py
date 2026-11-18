"""Routing: ask the right providers, in the right order, and say who failed.

The UI asks the registry, never a provider. That is what keeps the front
end country-agnostic: `registry.geocode("B8 3AY")` and
`registry.geocode("1600 Pennsylvania Ave")` are the same call, and which
adapter answers is an implementation detail the user never sees.

ORDER MATTERS AND IS DELIBERATE. Country-specific providers are asked
first because they are usually more authoritative in their own patch
(postcodes.io knows a UK postcode better than a worldwide gazetteer),
and the global provider is the fallback that makes coverage universal.
When every provider declines, the Missing that comes back lists all of
them — "asked: uk-gov-open, nominatim" — so a user can tell an unmapped
place from a broken server.
"""
from __future__ import annotations

from ..provenance import Missing
from .base import CAP_AVAILABLE, CAP_LIMITED, CAP_NONE, LAYERS, Capability
from .nominatim import NominatimProvider
from .overpass import OverpassProvider
from .uk import UKProvider


class Registry:
    def __init__(self, providers=None):
        self.providers = providers if providers is not None else [
            UKProvider(),          # country-specific first
            NominatimProvider(),   # worldwide address fallback
            OverpassProvider(),    # worldwide footprints
        ]

    def for_country(self, country=None):
        """Country providers first, then global ones. Stable order.

        WITH NO COUNTRY HINT, ASK EVERYONE. A user typing "B8 3AY" into
        a blank search box has not told us they are in Britain — that is
        the answer, not the question. Filtering to global providers when
        country is None meant the UK adapter never saw a UK postcode and
        the authoritative source was skipped on the commonest query the
        product has. Providers decline what they cannot serve, so asking
        a country provider outside its patch costs one cheap refusal.
        """
        if not country:
            specific = [p for p in self.providers if "*" not in p.countries]
        else:
            specific = [p for p in self.providers
                        if "*" not in p.countries and p.serves(country)]
        globals_ = [p for p in self.providers if "*" in p.countries]
        return specific + globals_

    def _try(self, method: str, _route_country, *args, **kw):
        # _route_country picks the provider ORDER and is not passed on;
        # a provider that also takes a `country` filter gets it through
        # **kw. Naming them the same collided on every geocode call.
        asked, details = [], []
        for p in self.for_country(_route_country):
            fn = getattr(p, method, None)
            if fn is None:
                continue
            asked.append(p.name)
            try:
                res = fn(*args, **kw)
            except Exception as e:      # a provider must never take the page down
                details.append(f"{p.name}: {type(e).__name__}: {e}")
                continue
            if res:
                return res
            if getattr(res, "detail", None):
                details.append(f"{p.name}: {res.detail}")
        return Missing(
            reason=f"no provider returned {method} for this location",
            asked=tuple(asked),
            detail=" | ".join(details) if details else None)

    # -- the public surface the API layer calls --------------------------
    def geocode(self, query: str, country=None, limit=5):
        return self._try("geocode", country, query,
                         country=country, limit=limit)

    def reverse(self, lat, lon, country=None):
        return self._try("reverse", country, lat, lon)

    def buildings(self, west, south, east, north, country=None):
        return self._try("buildings", country, west, south, east, north)

    def parcel(self, lat, lon, country=None):
        return self._try("parcel", country, lat, lon)

    def elevation(self, lat, lon, country=None):
        return self._try("elevation", country, lat, lon)

    def planning(self, lat, lon, country=None):
        return self._try("planning", country, lat, lon)

    def utilities(self, west, south, east, north, country=None):
        return self._try("utilities", country, west, south, east, north)

    # -- the honesty matrix ---------------------------------------------
    def capabilities(self, country=None) -> dict:
        """Best capability per layer for a country, with who provides it.

        "Best" means the highest level any available provider offers,
        and the note travels with it. A layer nobody serves comes back
        NOT AVAILABLE with the reason from whichever provider explained
        itself, which is what the UI puts on screen instead of an empty
        panel.
        """
        rank = {CAP_NONE: 0, "RESTRICTED": 1, CAP_LIMITED: 2, CAP_AVAILABLE: 3}
        out = {}
        for layer in LAYERS:
            best, who = Capability(CAP_NONE, "no provider serves this layer "
                                             "in this country"), None
            for p in self.for_country(country):
                cap = p.capability(layer)
                if rank.get(cap.level, 0) > rank.get(best.level, 0):
                    best, who = cap, p.name
            out[layer] = dict(best.as_dict(), provider=who)
        return {"country": (country or "").upper() or None, "layers": out}


_default = None


def default() -> Registry:
    global _default
    if _default is None:
        _default = Registry()
    return _default
