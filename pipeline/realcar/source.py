#!/usr/bin/env python3
"""source.py — find a car on Sketchfab when the catalogue has none.

    python3 pipeline/realcar/source.py "Ford Kuga 2021"      # list what it would take

Search is public. Downloading needs a Sketchfab API token in the environment
variable SKETCHFAB_TOKEN (the environment's settings, never the chat or a
file in the repo).

What it takes:
  - downloadable, a Creative Commons licence (CC BY, BY-SA, CC0; the
    NonCommercial ones too, flagged, while the app is free),
  - the make and model in the title,
  - no toy, game or low-poly cars (title words, or under 40k faces),
  - the year in the title closest to the one asked for,
  - 60k to 1.5M faces preferred (a real model that a phone can still show).

It returns a catalogue-shaped record, so batch.one() builds it the same way
as a catalogue car.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = "https://api.sketchfab.com/v3"
LICENCES = {"by": "CC BY 4.0", "by-sa": "CC BY-SA 4.0", "cc0": "CC0", "by-nc": "CC BY-NC 4.0",
            "by-nc-sa": "CC BY-NC-SA 4.0", "by-nd": "CC BY-ND 4.0", "by-nc-nd": "CC BY-NC-ND 4.0"}
LABEL_SLUG = {"CC Attribution": "by", "CC Attribution-ShareAlike": "by-sa", "CC0 Public Domain": "cc0",
              "CC Attribution-NonCommercial": "by-nc", "CC Attribution-NonCommercial-ShareAlike": "by-nc-sa",
              "CC Attribution-NoDerivs": "by-nd", "CC Attribution-NonCommercial-NoDerivs": "by-nc-nd"}
# NoDerivs licences forbid the changes the machine makes (cutting, rigging)
ALLOWED = {"by", "by-sa", "cc0", "by-nc", "by-nc-sa"}
TOY = re.compile(r"low[\s-]?poly|toy|cartoon|stylized|stylised|lego|chibi|hot ?wheels|matchbox|kart|"
                 r"\bgta\b|forza|need for speed|roblox|minecraft|voxel|game[\s-]?ready|\brc\b|diecast|model kit", re.I)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _get(url, token=None):
    req = urllib.request.Request(url, headers={"Authorization": f"Token {token}"} if token else {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def search(make, model, year=None, count=24):
    q = urllib.parse.urlencode({"type": "models", "q": f"{make} {model}", "downloadable": "true",
                                "count": count, "sort_by": "-relevance"})
    hits = _get(f"{API}/search?{q}").get("results", [])
    mk, md = norm(make), norm(model)
    out = []
    for m in hits:
        name = m.get("name") or ""
        slug = (m.get("license") or {}).get("slug") or LABEL_SLUG.get((m.get("license") or {}).get("label"))
        faces = m.get("faceCount") or 0
        why = []
        if slug not in ALLOWED:
            why.append(f"licence {(m.get('license') or {}).get('label')}")
        if md not in norm(name):
            why.append("model not in title")
        if TOY.search(name) or faces < 40000:
            why.append("toy, game or low-poly")
        years = [int(y) for y in re.findall(r"\b(19[5-9]\d|20[0-3]\d)\b", name)]
        dy = min(abs(year - y) for y in years) if (year and years) else (6 if year else 0)
        score = dy * 2 + (0 if 60000 <= faces <= 1500000 else 3) + (0 if slug in ("by", "by-sa", "cc0") else 1) \
            + (0 if mk in norm(name) else 1)
        out.append({"uid": m["uid"], "name": name, "author": (m.get("user") or {}).get("displayName"),
                    "licence": LICENCES.get(slug, (m.get("license") or {}).get("label")), "slug": slug,
                    "faces": faces, "year_in_title": years[0] if years else None, "score": score, "refused": why})
    ok = sorted([o for o in out if not o["refused"]], key=lambda o: o["score"])
    return ok, [o for o in out if o["refused"]]


def as_item(hit, make, model, year):
    """A catalogue-shaped record for batch.one(): the GLB link is fetched
    with the token at download time."""
    token = os.environ.get("SKETCHFAB_TOKEN")
    if not token:
        raise RuntimeError("downloading from Sketchfab needs SKETCHFAB_TOKEN in the environment")
    d = _get(f"{API}/models/{hit['uid']}/download", token)
    url = (d.get("glb") or {}).get("url")
    if not url:
        raise RuntimeError("Sketchfab offered no GLB for this model")
    y = hit.get("year_in_title") or year
    return {"assetId": f"sf-{norm(make)}-{norm(model)}-{hit['uid'][:8]}", "make": make.lower(), "model": model,
            "modelFamily": model, "desktopGlbUrl": url, "qualityGrade": None, "yearStart": y, "yearEnd": None,
            "sourceReferenceId": hit["uid"], "sourceTitle": hit["name"], "sourceCreator": hit["author"],
            "sourceUrl": f"https://sketchfab.com/3d-models/{hit['uid']}", "licence": hit["licence"],
            "provenance": "sourced on demand"}


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import make  # noqa: E402
    w = make.parse(" ".join(sys.argv[1:]))
    words = w["words"].split()
    ok, refused = search(words[0], " ".join(words[1:]), w.get("year"))
    print(json.dumps({"asked": w, "would_take": ok[:5], "refused": refused[:8]}, indent=1))
