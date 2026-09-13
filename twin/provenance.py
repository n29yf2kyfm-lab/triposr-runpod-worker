"""Where every fact came from — the spine of the whole platform.

THE RULE THIS FILE EXISTS TO ENFORCE: nothing describing the real world
travels through this system naked. A building footprint, an address, a
height, a pipe run — each arrives wrapped in the record of where it came
from, when it was observed, how accurate it is, and what was done to it
on the way. A number without that record is indistinguishable from a
number somebody made up, and this platform is for people who are going
to dig foundations against these numbers.

So `Sourced` is not decoration. It is the type. Provider methods return
Sourced or they return Missing; there is no third option that quietly
hands back a bare value, because a bare value is exactly how an estimate
turns into a survey somewhere three layers downstream.

MISSING IS A FIRST-CLASS ANSWER. `Missing` carries the reason and the
providers that were asked. The UI renders it as DATA NOT AVAILABLE. It
is never rendered as zero, as an empty polygon, or as a plausible guess.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


# How a value came to exist, in increasing distance from a measurement.
# The UI colours geometry by this and never blurs the boundary: a
# surveyed wall and a guessed wall must not look alike on screen.
CLASS_VERIFIED = "verified"      # measured by an authoritative survey
CLASS_DERIVED = "derived"        # computed from verified data (LIDAR fit)
CLASS_ESTIMATED = "estimated"    # inferred by rule; plausible, not measured
CLASS_USER = "user"              # drawn or stated by a person using the app

CLASSES = (CLASS_VERIFIED, CLASS_DERIVED, CLASS_ESTIMATED, CLASS_USER)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Provenance:
    """The mandatory record. Every field earns its place.

    source_provider   who served it            "nominatim"
    source_dataset    which dataset            "openstreetmap"
    source_identifier the id IN that dataset   "way/122819341"
    licence           the terms it arrives under, by key into licences.py
    retrieval_date    when WE fetched it
    observation_date  when the WORLD was measured — usually different, and
                      the one that matters when a house was extended in
                      between. Unknown is honest; guessing is not.
    accuracy_m        positional accuracy where the source states one
    confidence        0..1, our own reading of how much to trust it
    processing_method what we did to it ("as published", "RANSAC plane fit")
    derived_from      provenance of the input, when this is computed
    """
    source_provider: str
    source_dataset: str
    source_identifier: Optional[str] = None
    licence: str = "unknown"
    retrieval_date: str = field(default_factory=_now)
    observation_date: Optional[str] = None
    accuracy_m: Optional[float] = None
    confidence: Optional[float] = None
    processing_method: str = "as published"
    derived_from: Optional["Provenance"] = None

    def derive(self, method: str, *, confidence: Optional[float] = None,
               accuracy_m: Optional[float] = None,
               provider: Optional[str] = None) -> "Provenance":
        """Provenance for something COMPUTED from this. Keeps the chain.

        A roof pitch fitted to LIDAR is not the LIDAR: it is derived from
        it, by a named method, and a reader must be able to walk back to
        the tile it came off.
        """
        return Provenance(
            source_provider=provider or self.source_provider,
            source_dataset=self.source_dataset,
            source_identifier=self.source_identifier,
            licence=self.licence,
            observation_date=self.observation_date,
            accuracy_m=accuracy_m if accuracy_m is not None else self.accuracy_m,
            confidence=confidence if confidence is not None else self.confidence,
            processing_method=method,
            derived_from=self,
        )

    def chain(self) -> list:
        out, node = [], self
        while node is not None:
            out.append(f"{node.source_provider}:{node.source_dataset}"
                       f"({node.processing_method})")
            node = node.derived_from
        return out

    def as_dict(self) -> dict:
        d = asdict(self)
        d["chain"] = self.chain()
        return d


@dataclass(frozen=True)
class Sourced:
    """A value that knows where it came from, and how far to trust it."""
    value: Any
    provenance: Provenance
    classification: str = CLASS_VERIFIED

    def __post_init__(self):
        if self.classification not in CLASSES:
            raise ValueError(
                f"classification {self.classification!r} is not one of "
                f"{CLASSES} — an unlabelled value is how an estimate ends "
                f"up on a drawing as a survey")

    @property
    def available(self) -> bool:
        return True

    def as_dict(self) -> dict:
        v = self.value
        if hasattr(v, "as_dict"):
            v = v.as_dict()
        return {"available": True, "value": v,
                "classification": self.classification,
                "provenance": self.provenance.as_dict()}


@dataclass(frozen=True)
class Missing:
    """DATA NOT AVAILABLE, with the reason and who was asked.

    Deliberately NOT falsy-by-accident-only: code that does `if result:`
    on a Missing gets False, so the common mistake fails safe. But the
    reason travels, because "we could not reach the server" and "this
    country does not publish it" are different answers to the user and
    only one of them is worth retrying.
    """
    reason: str
    asked: tuple = ()
    detail: Optional[str] = None

    def __bool__(self) -> bool:
        return False

    @property
    def available(self) -> bool:
        return False

    def as_dict(self) -> dict:
        return {"available": False, "status": "DATA NOT AVAILABLE",
                "reason": self.reason, "asked": list(self.asked),
                "detail": self.detail}


def dump(obj) -> str:
    """JSON for anything in this module, for the API layer."""
    if hasattr(obj, "as_dict"):
        obj = obj.as_dict()
    return json.dumps(obj, default=str)
