#!/usr/bin/env python3
"""glTF glazing probe for the Jeep wave.

CLAUDE.md 2026-08-11: the wave audit sheet CANNOT witness a glazing defect --
render/handler.py forces transmission=1.0 onto any material whose NAME matches
glass/window/screen/..., so an OPAQUE car renders perfect clear glass. The only
free, decisive test is the glTF JSON itself.

Reads the JSON chunk of the staged GLB by HTTP Range (the JSON chunk is always
first in a GLB, right after the 12-byte header), then classifies:

  clear  - a glazing-named material carries alphaMode BLEND/MASK, baseColor
           alpha < 1.0, or KHR_materials_transmission
  faded  - transparent but alpha in [0.05, 0.55] (heavy tint)
  opaque - zero transparent materials in the whole file

Also reports the FLAT-SHELL signature (all untextured materials sharing one
baseColorFactor with minL >= 0.4), which is the documented tyre/glass clay
failure and is immune to render rig traps.
"""
import json, re, struct, sys, urllib.request

SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"
# Superset of the handler's regex. The handler matches only
# (glass|window|windscreen|windshield|screen|vidro|glas|scheibe|fenster);
# a Jeep in this wave named its glazing "Vitre"/"Vitre_ar" (French), which the
# handler does NOT override -- so that sheet showed the GLB's own glazing
# honestly. Naming this out matters: whether the sheet lies depends entirely on
# whether the material name happens to match the handler's list.
GLASSY = re.compile(
    r"glass|window|windscreen|windshield|screen|vidro|glas|scheibe|fenster|"
    r"vetro|cristal|verre|steklo|transparent|glazing|"
    r"vitre|vitrage|pare.?brise|lunette|luneta|ventana|finestrino|okno|cam\b",
    re.I)


def head(url, n):
    rq = urllib.request.Request(url, headers={"Range": f"bytes=0-{n-1}"})
    return urllib.request.urlopen(rq, timeout=180).read()


def gltf_json(url):
    b = head(url, 32)
    if b[:4] != b"glTF":
        raise RuntimeError("not a glb")
    jlen = struct.unpack("<I", b[12:16])[0]
    ctype = b[16:20]
    if ctype != b"JSON":
        raise RuntimeError("first chunk not JSON")
    body = head(url, 20 + jlen)[20:20 + jlen]
    return json.loads(body.decode("utf-8", "replace"))


def probe(uid, stage="staging/jeep"):
    url = f"{SB}/storage/v1/object/public/{BUCKET}/{stage}/{uid}.glb"
    g = gltf_json(url)
    mats = g.get("materials") or []
    trans, glazing, flat_vals, untex = [], [], set(), 0
    for m in mats:
        nm = m.get("name") or ""
        pbr = m.get("pbrMetallicRoughness") or {}
        bcf = pbr.get("baseColorFactor") or [1, 1, 1, 1]
        alpha = bcf[3] if len(bcf) > 3 else 1.0
        mode = m.get("alphaMode", "OPAQUE")
        ext = m.get("extensions") or {}
        tr = (ext.get("KHR_materials_transmission") or {}).get("transmissionFactor", 0)
        is_trans = (mode in ("BLEND", "MASK") and alpha < 1.0) or alpha < 1.0 or tr > 0
        if is_trans:
            trans.append({"name": nm, "alpha": round(alpha, 3), "mode": mode,
                          "transmission": round(tr, 3)})
        if GLASSY.search(nm):
            glazing.append({"name": nm, "alpha": round(alpha, 3), "mode": mode,
                            "transmission": round(tr, 3), "transparent": bool(is_trans)})
        if not pbr.get("baseColorTexture"):
            untex += 1
            flat_vals.add(tuple(round(x, 4) for x in bcf[:3]))

    flat = (untex >= 3 and len(flat_vals) == 1
            and min(list(flat_vals)[0]) >= 0.4
            and not any(m.get("alphaMode", "OPAQUE") != "OPAQUE" for m in mats))

    # -- verdict -----------------------------------------------------------
    # glTF baseColorFactor alpha is OPACITY: 1.0 = fully opaque, 0.4 = quite
    # transparent. CLAUDE.md's Porsche calibration says glazing as heavy as
    # alpha 0.78-0.94 still resolves the interior under backlight, i.e. still
    # reads as glass. So "faded" is only the sliver just below 1.0, and any
    # transparent glazing below 0.94 is clear. An earlier version of this file
    # had the band inverted (faded = 0.05-0.55), which would have failed the
    # Grand Cherokee MK2's perfectly good 0.443 windowglass.
    def eff_alpha(x):
        a = x["alpha"]
        t = x.get("transmission", 0) or 0
        return min(a, 1.0 - t) if t > 0 else a

    # LAMP LENSES ARE NOT GLAZING. Measured on Jeep Gladiator 5165e4ab: its
    # window material is alpha 1.0 OPAQUE while RED_GLASS and ORANGE_GLASS
    # (tail and indicator lenses) are alpha 0.25 with transmission 1.0. Both
    # match a naive /glass/ regex, so the car scored "clear" on lamp lenses
    # alone while its actual windows were opaque. Split them apart and let the
    # WINDOW-specific materials decide whenever any exist.
    LAMPY = re.compile(r"red|orange|amber|yellow|tail|head|lamp|light|blink|"
                       r"turn|indicat|fog|reverse|brake|stop|feux|clignot", re.I)
    WINDOWY = re.compile(r"window|windscreen|windshield|vitre|scheibe|fenster|"
                         r"glazing|pare.?brise|lunette|luneta|ventana|finestrino", re.I)

    windows = [x for x in glazing if WINDOWY.search(x["name"])]
    if not windows:
        windows = [x for x in glazing if not LAMPY.search(x["name"])]
    if windows:
        # Window-specific materials exist: they alone decide the verdict.
        glazing = windows

    trans_glazing = [x for x in glazing if x["transparent"]]
    if trans_glazing:
        lo = min(eff_alpha(x) for x in trans_glazing)
        verdict = "faded" if lo > 0.94 else "clear"
    elif glazing and not trans_glazing:
        # glazing material EXISTS by name and is fully opaque. The render
        # worker would still force transmission=1.0 onto it and manufacture
        # clear glass in the sheet -- this is exactly the Porsche failure.
        verdict = "opaque" if not trans else "ambiguous"
    elif trans:
        # no glazing-named material, but something in the file is transparent.
        # Most likely the glazing under a non-matching name (the clay-shell
        # case shows through in the sheet because no override fires).
        lo = min(eff_alpha(x) for x in trans)
        verdict = "faded" if lo > 0.94 else "clear"
    else:
        verdict = "opaque"

    return {"uid": uid, "verdict": verdict, "n_materials": len(mats),
            "n_transparent": len(trans), "glazing_named": glazing[:6],
            "transparent": trans[:6], "flat_shell": flat,
            "n_textures": len(g.get("images") or [])}


if __name__ == "__main__":
    rows = json.load(open(sys.argv[1]))
    out = []
    for r in rows:
        try:
            p = probe(r["uid"])
        except Exception as e:
            p = {"uid": r["uid"], "verdict": "unknown",
                 "error": f"{type(e).__name__}: {str(e)[:60]}"}
        p["name"] = r["name"]
        out.append(p)
        print(f"{p['verdict']:<8} flat={str(p.get('flat_shell')):<5} "
              f"trans={p.get('n_transparent')}/{p.get('n_materials')} "
              f"{r['name'][:52]}", flush=True)
    json.dump(out, open(sys.argv[2], "w"), indent=1)
