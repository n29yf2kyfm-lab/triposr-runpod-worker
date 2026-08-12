"""
Supabase access — fetch coding definitions & DTCs, and (critically) write the
audit log for every coding change.

SAFETY: the engine reads the *value to write* from the definition row here, never
from the AI. And every write is recorded with its previous bytes so it can be
reverted.
"""
from __future__ import annotations

import os
from typing import Optional

from supabase import Client, create_client


def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


class Store:
    def __init__(self, client: Optional[Client] = None):
        self.db = client or get_client()

    # --- profiles ----------------------------------------------------------
    def platform_and_ecu(self, platform_id: str, ecu_key: str) -> tuple[dict, dict]:
        platform = (self.db.table("platform").select("*")
                    .eq("id", platform_id).single().execute().data)
        ecu = (self.db.table("ecu").select("*")
               .eq("platform_id", platform_id).eq("key", ecu_key).single().execute().data)
        return platform, ecu

    # --- coding definitions (the moat) ------------------------------------
    def definition(self, ecu_id: str, feature_key: str) -> dict:
        return (self.db.table("coding_definition").select("*")
                .eq("ecu_id", ecu_id).eq("feature_key", feature_key)
                .single().execute().data)

    def definitions_for_ecu(self, ecu_id: str) -> list[dict]:
        return (self.db.table("coding_definition").select("*")
                .eq("ecu_id", ecu_id).execute().data)

    # --- DTC decode --------------------------------------------------------
    def decode_dtc(self, code: str, make: str | None = None) -> dict | None:
        q = self.db.table("dtc_library").select("*").eq("code", code)
        if make:
            q = q.eq("make", make)
        rows = q.execute().data
        return rows[0] if rows else None

    # --- audit (SAFETY) ----------------------------------------------------
    def record_change(self, *, vehicle_id, user_id, ecu_id, definition_id, vin,
                      previous: bytes, new: bytes, chosen_option: str,
                      result: str = "applied", note: str = "") -> dict:
        return (self.db.table("coding_audit").insert({
            "vehicle_id": vehicle_id, "user_id": user_id, "ecu_id": ecu_id,
            "definition_id": definition_id, "vin": vin,
            "previous_value": previous.hex(), "new_value": new.hex(),
            "chosen_option": chosen_option, "result": result, "note": note,
        }).execute().data[0])
