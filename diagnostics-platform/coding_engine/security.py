"""
Security plug-in interfaces.

This repo ships NO manufacturer key algorithms and NO SFD unlock. Those are
proprietary and/or licensed. What we provide are the *interfaces* your licensed
data/software slots into, so the engine can call them without ever embedding a
secret it isn't entitled to.

See SAFETY.md — do not attempt to defeat these gates; supply legitimate credentials.
"""
from __future__ import annotations

import abc
from typing import Protocol


class SecurityProvider(Protocol):
    """Seed->key for UDS SecurityAccess (0x27)."""
    def compute_key(self, *, ecu_key: str, level: int, seed: bytes, vin: str) -> bytes:
        ...


class SfdTokenProvider(Protocol):
    """
    VW Group SFD (2020+). OBDeleven can auto-unlock ONLY because it is officially
    licensed by VW; your implementation must call *your* licensed token service.
    """
    def request_token(self, *, vin: str, ecu_key: str, action: str) -> bytes:
        ...


# --- example scaffolding (NOT a real algorithm) -----------------------------

class ExternalToolSecurityProvider(abc.ABC):
    """
    Base for wrapping an external licensed tool/library you own. Implement
    `compute_key` by delegating to that tool (e.g. a vendor DLL/SO, a licensed
    web service, or your own reverse-engineered algorithm for cars you're
    authorised to service).
    """
    @abc.abstractmethod
    def compute_key(self, *, ecu_key: str, level: int, seed: bytes, vin: str) -> bytes:
        raise NotImplementedError(
            "Plug in your licensed seed->key here. This repo intentionally ships none."
        )


class DeniedSecurityProvider:
    """Default: refuse. Fails safe if nothing is configured."""
    def compute_key(self, *, ecu_key: str, level: int, seed: bytes, vin: str) -> bytes:
        raise PermissionError(
            f"No security provider configured for {ecu_key} (level {level}). "
            f"Coding blocked by design. Configure a licensed SecurityProvider."
        )
