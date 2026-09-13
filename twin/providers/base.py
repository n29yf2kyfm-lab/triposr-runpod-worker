"""The adapter every country plugs into, and the honesty matrix.

WHY AN INTERFACE AT ALL. The UI must not know which country it is in.
"Show me the parcel" is the same question in Birmingham and in Bavaria;
what differs is who answers it, under what terms, and whether anyone
answers it at all. Every difference lives behind this interface, and the
UI reads a CAPABILITY MATRIX rather than discovering the truth by
getting an empty polygon back.

THE MATRIX IS THE PRODUCT'S HONESTY. A platform that claims worldwide
coverage and then silently shows nothing in France is worse than one
that says, on screen, "parcels: not published nationally in this
country". Capability is declared per country per layer, with a reason,
and `Missing` carries that reason to the user.

Providers return Sourced or Missing. Nothing else. A provider that
raises on a network blip is a provider that takes the whole page down,
so transport failures become Missing with the detail attached.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Optional

from ..provenance import Missing, Sourced


# Capability levels, worst to best. LIMITED is the interesting one: it
# means "some of this country, or some of the attributes, or behind a
# paywall we have not bought" — a real state that the binary
# available/unavailable pair cannot express without lying one way.
CAP_NONE = "NOT AVAILABLE"
CAP_RESTRICTED = "RESTRICTED"      # exists but terms forbid our use
CAP_LIMITED = "LIMITED"
CAP_AVAILABLE = "AVAILABLE"

LAYERS = (
    "address", "parcel", "building", "elevation", "imagery",
    "street_imagery", "planning", "utilities", "floorplans",
)


@dataclass(frozen=True)
class Capability:
    level: str
    note: str = ""
    licence: Optional[str] = None

    def as_dict(self) -> dict:
        return {"level": self.level, "note": self.note,
                "licence": self.licence}


class Provider(abc.ABC):
    """One source of truth for one or more countries.

    Subclasses implement only what they actually serve; everything else
    inherits the Missing default, which names this provider in `asked`
    so a user can see who was tried.
    """

    name: str = "unnamed"
    countries: tuple = ()            # ISO 3166-1 alpha-2, or ("*",) global
    capabilities: dict = {}          # layer -> Capability

    def capability(self, layer: str) -> Capability:
        return self.capabilities.get(
            layer, Capability(CAP_NONE, f"{self.name} does not serve {layer}"))

    def serves(self, country: Optional[str]) -> bool:
        if "*" in self.countries:
            return True
        return bool(country) and country.upper() in self.countries

    # -- the interface. Each returns Sourced | Missing. ------------------
    def _no(self, layer: str) -> Missing:
        cap = self.capability(layer)
        return Missing(reason=cap.note or f"{layer} not served",
                       asked=(self.name,))

    def geocode(self, query: str, *, country=None, limit=5):
        """Free text (postcode, address, place) -> candidate locations."""
        return self._no("address")

    def reverse(self, lat: float, lon: float):
        """Coordinates -> the address there."""
        return self._no("address")

    def buildings(self, west, south, east, north):
        """Building footprints intersecting a bbox, as GeoJSON features."""
        return self._no("building")

    def parcel(self, lat: float, lon: float):
        """The legal plot boundary containing a point."""
        return self._no("parcel")

    def elevation(self, lat: float, lon: float):
        """Ground height, and surface height where a DSM exists."""
        return self._no("elevation")

    def planning(self, lat: float, lon: float):
        """Designations and constraints that bite on this point."""
        return self._no("planning")

    def utilities(self, west, south, east, north):
        """Buried services, where a network operator publishes them."""
        return self._no("utilities")


class ProviderError(RuntimeError):
    """Transport or protocol failure. Never escapes a provider method —
    it is caught and converted to Missing, because one dead endpoint must
    not take out a page that has six other layers to draw."""


def transport_missing(name: str, layer: str, exc: Exception) -> Missing:
    return Missing(
        reason=f"{layer} lookup failed to reach {name}",
        asked=(name,),
        detail=f"{type(exc).__name__}: {str(exc)[:200]}")


def sourced(value, prov, classification="verified") -> Sourced:
    return Sourced(value=value, provenance=prov, classification=classification)
