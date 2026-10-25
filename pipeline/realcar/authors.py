#!/usr/bin/env python3
"""authors.py — where each catalogue model came from, who made it and
under what licence, for the credit a CC BY licence asks for and for using
only what may be used commercially.

    python3 pipeline/realcar/authors.py        # writes authors_table.json (re-run: only what is missing)

Two records of each model's licence are read:
  - the file's own: a model downloaded from Sketchfab carries its source
    page, author, title and licence in its glTF asset.extras, as they were
    when it was downloaded (read from the file's header, a range request);
  - the page's now: the model's public Sketchfab page
    (api.sketchfab.com/v3/models/<id>) gives its author and current licence.
The catalogue's own fields are often empty (591 of the 1,045 approved
models had no source link) and sometimes wrong (NonCommercial models filed
as CC BY). Some authors have changed a model's licence since it was
downloaded; batch.credit_of uses a model commercially only when both
records allow it, and says when they differ. The table is shipped beside
the machine, so a build credits the author with no outside call.
"""
import json
import os
import re
import struct
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch                                               # noqa: E402

TABLE = os.path.join(HERE, "authors_table.json")
UA = {"User-Agent": "ExpertCarCheck-GLB/1.0 (model credits; https://github.com/n29yf2kyfm-lab/triposr-runpod-worker)"}
UID = re.compile(r"sketchfab\.com/3d-models/(?:[\w-]*-)?([0-9a-f]{32})")


def get(url, rng=None, as_json=False):
    h = dict(UA, **({"Range": f"bytes={rng[0]}-{rng[1]}"} if rng else {}))
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
                b = r.read()
            return json.loads(b) if as_json else b
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            time.sleep(3 * (attempt + 1))
        except Exception:
            time.sleep(3 * (attempt + 1))
    return False


def embedded(url):
    """The file's asset.extras (author, license, source, title), from its JSON chunk."""
    head = get(url, (0, 65535))
    if not head or len(head) < 20 or head[:4] != b"glTF":
        return None if head is not False else False
    clen = struct.unpack("<I", head[12:16])[0]
    body = head[20:20 + clen] if 20 + clen <= len(head) else get(url, (20, 20 + clen - 1))
    if not body:
        return None if body is not False else False
    try:
        j = json.loads(body)
    except ValueError:
        return None
    return ((j.get("asset") or {}).get("extras") or {})


def main():
    have = json.load(open(TABLE)) if os.path.exists(TABLE) else {}
    todo = [i for i in batch.catalogue().values() if i.get("publicationStatus") == "approved" and i.get("desktopGlbUrl")
            and "embedded" not in have.get(i["assetId"], {})]
    print(len(todo), "models to look up", flush=True)
    for n, i in enumerate(todo):
        rec = dict(have.get(i["assetId"], {}))
        ex = embedded(i["desktopGlbUrl"])
        if ex is False:
            continue                                   # not reached: tried again next run
        ex = ex or {}
        rec["embedded"] = {k: ex.get(k) for k in ("author", "license", "source", "title") if ex.get(k)}
        src = i.get("sourceUrl") or ex.get("source") or ""
        m = UID.search(src)
        if m and "licence" not in rec:
            d = get(f"https://api.sketchfab.com/v3/models/{m.group(1)}", as_json=True)
            if d is not False:
                u = (d or {}).get("user") or {}
                rec.update(username=u.get("username"), title=(d or {}).get("name"),
                           licence=((d or {}).get("license") or {}).get("label"), gone=d is None)
                rec.setdefault("author", u.get("displayName") or u.get("username"))
            time.sleep(0.3)
        if not rec.get("author") and ex.get("author"):
            rec["author"] = re.sub(r"\s*\(https?://[^)]*\)\s*$", "", ex["author"])
        if i.get("sourceCreator"):
            rec["author"] = i["sourceCreator"]
        rec["source"] = src or None
        have[i["assetId"]] = rec
        if n % 25 == 0:
            json.dump(have, open(TABLE + ".tmp", "w"), indent=0, sort_keys=True)
            os.replace(TABLE + ".tmp", TABLE)
            print(n, i["assetId"], rec.get("author"), "|", rec["embedded"].get("license"), "|", rec.get("licence"), flush=True)
    json.dump(have, open(TABLE + ".tmp", "w"), indent=0, sort_keys=True)
    os.replace(TABLE + ".tmp", TABLE)
    print(len(have), "models in the table", flush=True)


if __name__ == "__main__":
    main()
