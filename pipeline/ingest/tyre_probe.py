#!/usr/bin/env python3
"""glTF tyre probe -- decide "do the tyres read as black rubber?" without pixels.

Why this cannot be done from the audit sheet
--------------------------------------------
CLAUDE.md is emphatic and it was paid for twice:

  * 39 live cars (12 Fiat + 27 by an agent) were quarantined on SHEET evidence
    and ALL 39 were restored. Nothing was wrong with them.
  * The white-tyre render artefact is PROVEN, not argued: on the Mazda wave,
    cars #28/#29/#30 carry a BYTE-IDENTICAL tyre texture and an `EXT_Rubber`
    material at ~0.015, and on the same rig in the same run #29 rendered BLACK
    while #28 and #30 rendered WHITE. Same data, opposite outcome.
  * The 1x thumbnail read was wrong THREE times in one wave.

So the sheet is a CANDIDATE FINDER ONLY. CLAUDE.md's "cheapest decisive order
for a tyre verdict" is:

  1. the tyre material's baseColorFactor in the shipped glTF   <- this module
  2. if it is textured, EXTRACT the texture and take its mean  <- this module
  3. 5x crop of the tread face in front34/rear34 vs a control  <- the eye
  4. a red control render                                      <- GPU

Steps 1 and 2 are free-ish and immune to every rig trap, so they run first.

What this module actually decides
---------------------------------
It answers one narrow question: is the material bound to the tyre DARK? It
reports:

  black    - factor luminance <= 0.20, or a texture whose mean sRGB <= 90
  pale     - factor luminance >= 0.40 with no texture to rescue it. This is the
             real FLAT-SHELL / body-painted-rubber failure.
  mid      - between the two. Needs the eye; a mid-grey tyre reads pure white
             under this rig's one-sided key at thumbnail scale.
  no-tyre  - no material name matches. NOT a verdict: plenty of good cars name
             the tyre something else, or bind rubber to a body material. This
             must be routed to the eye, never failed.

MEASURED: THIS IS NOT A GATE. DO NOT MAKE IT ONE.
--------------------------------------------------
Validated 2026-08-11 against `retro_tyre_audit.json` -- 131 live cars whose tyre
verdicts were settled by RED control re-renders, live posters and 5x crops, i.e.
the strongest ground truth this project has. Scored against the shipped
`desktopGlbUrl` of each:

    ground truth "tyre-fail"  (8 cars) -> probe said pale on   0    RECALL 0/8
    ground truth "ok"       (108 cars) -> probe said pale on  13    FALSE ALARMS

Zero recall. Not "low" -- zero. Five of the eight real failures carry a
genuinely dark tyre material (`tire` at baseColor 0.106, `rubber` at 0.012,
`tire` at 0.008) and this probe correctly reads them as black; the other three
name no tyre material at all. That is not a bug to be fixed by a better regex or
a better threshold. It is CLAUDE.md's finding reproduced from the other side:

    "Passing and failing cars in this wave carry identical tyre materials and
     identical wheel prims, so a glTF probe cannot separate them."

The real Mercedes/Toyota failure is a PER-CORNER render artefact -- the same car
renders one white tyre and one black one from a byte-identical material -- so it
lives in the wheel meshes and the rig, not in the material table. No amount of
reading the glTF will see it. It takes 5x on the tread face in front34/rear34
against a same-batch known-good control, or a RED control render.

The 13 false alarms are untextured tyre materials sitting at 0.588, 0.8 or 1.0
-- the same values CLAUDE.md lists for the flat shell -- on cars whose tyres are
fine. A bright tyre factor ALONE is not the flat shell; the flat shell requires
every untextured material to share one value, which `glass_probe.flat_shell`
already tests and which IS validated.

So: use this to RECORD evidence and to reason about a candidate, never to decide
one. A "black" reading is genuinely useful in one narrow direction -- it rules
out the body-paint-over-rubber and flat-shell mechanisms for that car. It does
NOT clear the car of the per-corner white-tyre defect. Say which one you mean.

The other honest limit: this reads the material NAMED like a tyre, not the
material BOUND TO THE TYRE RING GEOMETRY. Those are usually the same and
occasionally are not.
"""
import io, json, re, struct, sys, urllib.request

SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"

# Anchored so it cannot swallow the body. "\btire\b" stops it matching inside
# "entire"; rim/wheel/hub are deliberately EXCLUDED -- a bright alloy rim is
# correct and is not the defect. Only the rubber is being judged here.
TYREY = re.compile(r"\btyre\b|\btire\b|\brubber\b|tyre_|tire_|_tyre|_tire|"
                   r"reifen|pneu|neumatico|gomma|llanta_goma|"
                   r"tires|tyres|tirewall|sidewall|tread", re.I)
# A whitewall is authentic period detail on the pre-war and Ponton-era cars this
# marque is full of (CLAUDE.md: Fiat Abarth 695 kept for exactly this). A
# material named for it must not be read as a pale-tyre failure.
WHITEWALLY = re.compile(r"whitewall|white_wall|weisswand", re.I)


def head(url, n):
    rq = urllib.request.Request(url, headers={"Range": f"bytes=0-{n-1}"})
    return urllib.request.urlopen(rq, timeout=180).read()


def gltf_json(url):
    b = head(url, 32)
    if b[:4] != b"glTF":
        raise RuntimeError("not a glb")
    jlen = struct.unpack("<I", b[12:16])[0]
    if b[16:20] != b"JSON":
        raise RuntimeError("first chunk not JSON")
    return json.loads(head(url, 20 + jlen)[20:20 + jlen].decode("utf-8", "replace"))


def _lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def texture_mean(url, g, tex_index):
    """Mean sRGB of a texture, pulled out of the GLB's binary chunk.

    Ranged so a 200MB GLB is not downloaded to read a 512x512 tyre map: the
    image's bufferView gives an exact byte window into the BIN chunk.
    """
    from PIL import Image
    t = g["textures"][tex_index]
    # A texture's image is normally t["source"], but a compressed-texture
    # extension moves it: KHR_texture_basisu and EXT_texture_webp both put the
    # image index inside t["extensions"][<ext>]["source"] and may omit "source"
    # entirely. Measured on toyota-gr86-v1 and toyota-corolla-v1, which raised
    # KeyError: 'source' and so had NO texture reading at all -- and because an
    # unreadable texture used to score as fully opaque, both were called "pale",
    # i.e. a tyre failure, on two cars whose tyres are fine.
    src = t.get("source")
    if src is None:
        for ext in (t.get("extensions") or {}).values():
            if isinstance(ext, dict) and "source" in ext:
                src = ext["source"]
                break
    if src is None:
        return None
    img = g["images"][src]
    if "bufferView" not in img:
        return None
    bv = g["bufferViews"][img["bufferView"]]
    # locate the BIN chunk header: it follows the JSON chunk
    b = head(url, 32)
    jlen = struct.unpack("<I", b[12:16])[0]
    bin_data_start = 20 + jlen + 8          # 8 = BIN chunk length+type header
    o = bin_data_start + bv.get("byteOffset", 0)
    raw = head(url, o + bv["byteLength"])[o:o + bv["byteLength"]]
    im = Image.open(io.BytesIO(raw)).convert("RGB").resize((48, 48))
    px = list(im.getdata())
    n = len(px)
    return round(sum(_lum(p) for p in px) / n, 1)


def probe(uid, stage="staging/mercedes", url=None, want_texture=True):
    if url is None:
        url = f"{SB}/storage/v1/object/public/{BUCKET}/{stage}/{uid}.glb"
    g = gltf_json(url)
    mats = g.get("materials") or []
    found = []
    for m in mats:
        nm = m.get("name") or ""
        if not TYREY.search(nm) or WHITEWALLY.search(nm):
            continue
        pbr = m.get("pbrMetallicRoughness") or {}
        sg = (m.get("extensions") or {}).get(
            "KHR_materials_pbrSpecularGlossiness") or {}
        bcf = pbr.get("baseColorFactor") or sg.get("diffuseFactor") or [1, 1, 1, 1]
        tex = pbr.get("baseColorTexture") or sg.get("diffuseTexture")
        rec = {"name": nm, "factor": [round(x, 3) for x in bcf[:3]],
               "lum": round(_lum(bcf), 3), "textured": bool(tex)}
        if tex and want_texture:
            try:
                rec["tex_mean_srgb"] = texture_mean(url, g, tex["index"])
            except Exception as e:
                rec["tex_error"] = f"{type(e).__name__}: {str(e)[:40]}"
        found.append(rec)

    if not found:
        return {"uid": uid, "tyre": "no-tyre", "materials": [],
                "note": "no tyre-named material; route to the eye, do not fail"}

    # A car may carry several tyre materials. The DARKEST is the one that
    # matters: if any tyre-named material is proper black rubber the car is not
    # a flat shell, and a second pale one is usually sidewall lettering or a
    # spare. Recorded in full so the reviewer can see the spread.
    #
    # A TEXTURED material whose texture could not be read scores UNKNOWN, never
    # "pale". The factor on a textured material is a multiplier and is [1,1,1]
    # on almost every one of them -- measured across the whole live catalogue --
    # so treating an unreadable texture as opaque white manufactures a tyre
    # failure out of a missing measurement. That is the "a metric that
    # confidently says all-clear is worse than no metric" trap, pointing the
    # other way.
    def score(r):
        t = r.get("tex_mean_srgb")
        if t is not None:
            return min(r["lum"], t / 255.0)
        if r["textured"]:
            return None                      # unmeasured, not bright
        return r["lum"]

    scored = [(score(r), r) for r in found]
    known = [(s, r) for s, r in scored if s is not None]
    if not known:
        return {"uid": uid, "tyre": "unknown", "score": None,
                "materials": found,
                "note": "tyre material is textured and the texture could not be "
                        "read; the factor is a multiplier and proves nothing"}
    s, _ = min(known, key=lambda x: x[0])
    tyre = "black" if s <= 0.20 else ("pale" if s >= 0.40 else "mid")
    return {"uid": uid, "tyre": tyre, "score": round(s, 3),
            "materials": found}


if __name__ == "__main__":
    import concurrent.futures as cf
    rows = json.load(open(sys.argv[1]))
    stage = sys.argv[3] if len(sys.argv) > 3 else "staging/mercedes"

    def one(r):
        try:
            p = probe(r["uid"], stage=stage)
        except Exception as e:
            p = {"uid": r["uid"], "tyre": "unknown",
                 "error": f"{type(e).__name__}: {str(e)[:60]}"}
        p["name"] = r["name"]
        return p

    with cf.ThreadPoolExecutor(8) as ex:
        out = list(ex.map(one, rows))
    for p in out:
        print(f"{p['tyre']:<8} {str(p.get('score')):<7} {p['name'][:52]}", flush=True)
    json.dump(out, open(sys.argv[2], "w"), indent=1)
