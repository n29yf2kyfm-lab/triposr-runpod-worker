#!/usr/bin/env python3
"""authors.py — the authors of the catalogue's Sketchfab models, for the
credit a CC BY licence asks for.

    python3 pipeline/realcar/authors.py        # writes authors_table.json (re-run: only what is missing)

The catalogue records many models without their author's name. Each
model's public Sketchfab page (api.sketchfab.com/v3/models/<id>) gives it,
with the model's title and licence as the author published them. The
table is shipped beside the machine, so a build credits the author with
no outside call; batch.credit_of reads it.
"""
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch                                               # noqa: E402

TABLE = os.path.join(HERE, "authors_table.json")
UA = {"User-Agent": "ExpertCarCheck-GLB/1.0 (model credits; https://github.com/n29yf2kyfm-lab/triposr-runpod-worker)"}


def page(uid):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"https://api.sketchfab.com/v3/models/{uid}", headers=UA),
                                        timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(3 * (attempt + 1))
        except Exception:
            time.sleep(3 * (attempt + 1))
    return False


def main():
    have = json.load(open(TABLE)) if os.path.exists(TABLE) else {}
    todo = [i for i in batch.catalogue().values() if not i.get("sourceCreator") and i["assetId"] not in have
            and re.search(r"sketchfab\.com/3d-models/(?:[\w-]*-)?([0-9a-f]{32})", i.get("sourceUrl") or "")]
    print(len(todo), "models without an author", flush=True)
    for n, i in enumerate(todo):
        uid = re.search(r"([0-9a-f]{32})", i["sourceUrl"]).group(1)
        d = page(uid)
        if d is False:
            continue                                   # not reached: tried again next run
        u = (d or {}).get("user") or {}
        have[i["assetId"]] = {"author": u.get("displayName") or u.get("username"), "username": u.get("username"),
                              "title": (d or {}).get("name"), "licence": ((d or {}).get("license") or {}).get("label"),
                              "gone": d is None}
        if n % 25 == 0:
            json.dump(have, open(TABLE + ".tmp", "w"), indent=0, sort_keys=True)
            os.replace(TABLE + ".tmp", TABLE)
            print(n, i["assetId"], have[i["assetId"]]["author"], flush=True)
        time.sleep(0.4)
    json.dump(have, open(TABLE + ".tmp", "w"), indent=0, sort_keys=True)
    os.replace(TABLE + ".tmp", TABLE)
    print(len(have), "authors in the table", flush=True)


if __name__ == "__main__":
    main()
