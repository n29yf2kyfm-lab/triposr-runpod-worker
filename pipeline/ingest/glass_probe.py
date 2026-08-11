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


# Materials that MUST be opaque on a finished car: body paint and rubber. Kept
# narrow and anchored so it cannot swallow glazing or lamp lenses -- "paint"
# never appears in a window material's name, and \b stops "tire" matching inside
# "entire". See the GLOBAL-ALPHA SHELL note in probe().
# NOTE ON THE BOUNDARIES. \b will NOT do here: underscore is a word character,
# so \btyre\b does not match "EXT_Tyre" and \brubber\b does not match
# "EXT_Rubber" -- both are real material names in the live catalogue, and the
# miss let mercedes-benz-cls-mw1-v1 score as a flat clay shell when a backlight
# render shows it has plainly black tyres. _SEP treats underscore, digits and
# case changes as separators while still refusing to match inside a longer word,
# so "entire" and "paintwork" stay excluded.
_L = r"(?<![a-z0-9])"     # left edge: not preceded by a letter or digit
_R = r"(?![a-z0-9])"      # right edge: not followed by a letter or digit
BODYISH = re.compile(
    rf"carpaint|car_paint|bodypaint|body_paint|karosserie|"
    rf"{_L}paint{_R}|{_L}black{_R}|{_L}tire{_R}|{_L}tyre{_R}|{_L}rubber{_R}", re.I)


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


def probe(uid, stage="staging/jeep", url=None):
    """Probe a staged uid, or any GLB by passing `url` directly.

    The url form exists so a retro audit of the LIVE catalogue can reuse
    these exact rules. A retro check that reimplements them drifts from
    the wave check, and then the two disagree about the same car.
    """
    if url is None:
        url = f"{SB}/storage/v1/object/public/{BUCKET}/{stage}/{uid}.glb"
    g = gltf_json(url)
    mats = g.get("materials") or []
    trans, glazing, flat_vals, untex, body_trans = [], [], set(), 0, []
    for m in mats:
        nm = m.get("name") or ""
        pbr = m.get("pbrMetallicRoughness") or {}
        mode = m.get("alphaMode", "OPAQUE")
        ext = m.get("extensions") or {}
        # SPECULAR-GLOSSINESS materials keep their colour in the EXTENSION, not
        # in pbrMetallicRoughness. Found 2026-08-11 re-validating this probe
        # against PORSCHE_GLASS.json: 2019-porsche-911-gt3-rs is ground-truth
        # CLEAR and scored "opaque" because every one of its materials is
        # KHR_materials_pbrSpecularGlossiness, so pbrMetallicRoughness is absent
        # and baseColorFactor fell back to the [1,1,1,1] default -- the probe
        # read an opacity the file never stated. That is the worst possible
        # failure direction here: under the owner's ruling "opaque" is an
        # outright FAIL, so this was about to cull a good car on a default
        # value. specGloss is legacy but common in older and JDM-market uploads,
        # which is exactly what a Mazda sweep is full of.
        sg = ext.get("KHR_materials_pbrSpecularGlossiness") or {}
        bcf = pbr.get("baseColorFactor") or sg.get("diffuseFactor") or [1, 1, 1, 1]
        alpha = bcf[3] if len(bcf) > 3 else 1.0
        tr = (ext.get("KHR_materials_transmission") or {}).get("transmissionFactor", 0)
        # TEXTURE-DRIVEN ALPHA, added 2026-08-11 after validating this probe
        # against PORSCHE_GLASS.json (107 cars, ground truth confirmed by
        # magenta-backlight renders). It scored 103/107, and THREE of the four
        # misses were the same mechanism: glazing authored as alphaMode=BLEND
        # with baseColorFactor alpha=1.0, the transparency living in the
        # baseColorTexture's alpha channel rather than the factor. The 1987
        # Porsche 959 ('Glass', BLEND, alpha=1.0, 20 textures) and
        # 2019-porsche-911-gt3-rs (BLEND, alpha=1.0, 109 textures) are both
        # genuinely transparent and this probe called them OPAQUE -- which
        # under the owner's ruling is an outright FAIL, i.e. the probe was
        # about to cull good cars. BLEND/MASK is a deliberate authoring choice;
        # a material set to it WITH a texture is asserting per-texel alpha.
        # Recorded separately so these can be eyeballed rather than trusted
        # blind: the factor cannot tell us HOW transparent the texture is.
        textured = bool(pbr.get("baseColorTexture") or sg.get("diffuseTexture"))
        tex_alpha = mode in ("BLEND", "MASK") and textured
        is_trans = (mode in ("BLEND", "MASK") and alpha < 1.0) or alpha < 1.0 or tr > 0 \
            or tex_alpha
        via = "texture-alpha" if (tex_alpha and alpha >= 1.0 and tr <= 0) else "factor"
        if is_trans:
            trans.append({"name": nm, "alpha": round(alpha, 3), "mode": mode,
                          "transmission": round(tr, 3), "via": via})
        if GLASSY.search(nm):
            glazing.append({"name": nm, "alpha": round(alpha, 3), "mode": mode,
                            "transmission": round(tr, 3), "transparent": bool(is_trans),
                            "via": via if is_trans else None})
        # GLOBAL-ALPHA SHELL -- found on the Volvo wave 2026-08-11, and NOT the
        # same thing as the flat shell above. "Volvo XC60" (1,134,258 faces)
        # carries 18 materials of which EVERY ONE is alphaMode=BLEND: carpaint
        # alpha 0.25, tire 0.25, chrome 0.25, rim 0.25, brakedisk 0.25. The
        # baseColorFactors are individually CORRECT (carpaint 0.796 light, tire
        # 0.106 dark rubber), so the flat-shell test cannot see it -- it requires
        # one shared colour AND no non-OPAQUE alphaMode, and this file fails both
        # halves. Only the alpha is broken, uniformly.
        #
        # It matters because the car renders 75% see-through: the audit sheet
        # shows a ghost with the floor visible through the doors, and the shipped
        # GLB is what the viewer hands the customer where posterUrl is null.
        #
        # It matters MORE because the glazing verdict below would call this car
        # "clear" and pass it: windowglass IS transparent (alpha 0.7), which is
        # true and entirely beside the point. Body paint and rubber must be
        # opaque, so they are tested separately here.
        # GLAZING IS NOT BODYWORK, even when it is called "black". Fixed
        # 2026-08-11 on the Toyota/Peugeot retro-audit. BODYISH matches the word
        # "black" (correctly -- flat shells really do name a body material
        # "black"), but PRIVACY GLASS is named that way too, and it is SUPPOSED
        # to be transparent. Every one of the five ALPHA-SHELL flags raised
        # against the LIVE catalogue was this false positive and not one was a
        # real defect:
        #   toyota-bz4x-v1                'black_glass'                 a=0.25
        #   toyota-camry-2007-tw1-v1      'Camry07-windows-black'       a=0.80
        #   peugeot-2008-2020-w5-v1       '..._e-2008_glass_black'      a=0.40
        #   peugeot-2008-2020-pw1-v1      '..._e-2008_glass_black'      a=0.40
        # Reporting those would have been the 39-car wrongful cull again, on a
        # name rather than on a pixel. Same class as the lamp-lens and
        # windscreen-icon guards below: a name-based classifier promoting the
        # wrong material to sole witness.
        # The genuine signature is untouched -- a real global-alpha shell names
        # 'carpaint' and 'tire' (Volvo XC60, and six Toyota Avensis/Land Cruiser
        # in this wave, all at the documented alpha 0.25), and neither is GLASSY.
        if BODYISH.search(nm) and is_trans and not GLASSY.search(nm):
            body_trans.append({"name": nm, "alpha": round(alpha, 3), "mode": mode})
        if not textured:
            untex += 1
            flat_vals.add(tuple(round(x, 4) for x in bcf[:3]))

    # A flat shell is a car whose material COLOURS are gone, names surviving.
    # The untextured test alone is not enough and over-reported badly: measured
    # by backlight render, lexus-lx570-2015-lxw1-v1 (15 textures) and
    # mercedes-benz-cls-mw1-v1 (19 textures) both render with plainly BLACK
    # TYRES and are real cars, yet both scored flat because their handful of
    # untextured materials happened to share white. Quarantining on that alone
    # would have repeated the 39-car wrongful cull.
    #
    # CLAUDE.md already states the missing condition: "Check the textures are
    # only number plates before calling it ... one where a texture feeds the
    # tyre or glass is not [flat]." So a car whose RUBBER or GLAZING is textured
    # still has that material's real appearance and cannot be a flat shell.
    body_or_glass_textured = any(
        (BODYISH.search(m.get("name") or "") or GLASSY.search(m.get("name") or ""))
        and ((m.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
             or ((m.get("extensions") or {})
                 .get("KHR_materials_pbrSpecularGlossiness") or {}).get("diffuseTexture"))
        for m in mats)
    flat = (untex >= 3 and len(flat_vals) == 1
            and min(list(flat_vals)[0]) >= 0.4
            and not body_or_glass_textured
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
                       r"turn|indicat|fog|reverse|brake|stop|feux|clignot|"
                       # swiatlo/swiatla = Polish for light. Added 2026-08-11 on
                       # the Honda wave: "Honda CR-V MK2 Pre-Facelift" is a
                       # Polish-authored model whose ONLY transparent materials
                       # are lamp__car (0.19) and swiatla_tyl_szkl (rear light
                       # glass, 0.5). "lamp" was caught, "swiatla" was not, so a
                       # car with no glazing surface at all still scored "clear".
                       r"swiatl|swiatla|swiatlo", re.I)
    WINDOWY = re.compile(r"window|windscreen|windshield|vitre|scheibe|fenster|"
                         r"glazing|pare.?brise|lunette|luneta|ventana|finestrino", re.I)
    # INTERIOR TRIM IS NOT GLAZING EITHER, and it beats the LAMPY guard because
    # it can contain a genuine window word. Measured 2026-08-11 on
    # 2019-porsche-911-gt3-rs: its only WINDOWY material is
    # "Airconditioningbuttonwindscreenventilationicons1Mtl" -- the dashboard
    # icon sheet for the windscreen demister button. Being WINDOWY it was
    # promoted to sole decider of the whole car's glazing verdict, and it is
    # opaque, so a ground-truth-CLEAR car scored "opaque" (an outright FAIL).
    # Same class of error as the lamp lenses, one level further in.
    # Deliberately NARROW. "interior" is NOT here: a material named
    # "interior_glass" is real glazing seen from inside, and excluding it would
    # repeat the very mistake this guard fixes one level down.
    TRIMMY = re.compile(r"icon|button|instrument|gauge|cluster|dial|dash|"
                        r"aircondition|ventilation|speedo|"
                        # An INFOTAINMENT SCREEN is not glazing. Measured
                        # 2026-08-11 on the live catalogue: honda-civic-v1's
                        # ONLY glazing-named material is
                        # "M_2023_Honda_Civic_Type_R_Touchscreen" -- GLASSY
                        # matches it on "screen", from windscreen -- so a
                        # centre-console display was promoted to sole decider of
                        # the whole car's glazing and, being opaque, scored the
                        # car "opaque", which is an outright FAIL. Exactly the
                        # Porsche dashboard-icon bug in a different guise.
                        r"touch|infotainment|navigation|multimedia|monitor|"
                        r"display|headunit|head.?unit|"
                        # mirror: the Jaguar wave's "glassSideMirror" is a
                        # MIRROR and must not be allowed to outvote real glazing.
                        r"mirror|rearview|rear.?view|wing.?mirror", re.I)

    glazing = [x for x in glazing if not TRIMMY.search(x["name"])] or glazing
    windows = [x for x in glazing if WINDOWY.search(x["name"])]
    non_lampy = [x for x in glazing if not LAMPY.search(x["name"])]
    windows = windows + [x for x in non_lampy if x not in windows]
    if windows:
        glazing = windows
    else:
        # EVERY glazing-named material is a lamp lens, so the file names no
        # glazing at all and the lamps must not be allowed to vote. Porsche
        # 911 Turbo (996) 28dbd433 has exactly one glassy name --
        # 'headlightglass', opaque -- alongside a transparent 'windoFS' that
        # matches no glass pattern; the lamp dragged it to "ambiguous" when the
        # ground truth is clear. Clearing the list falls through to the
        # transparent-material branch below, which reads windoFS correctly.
        glazing = []

    # THE FACTOR IS THE ONLY THING THAT CAN BE BANDED. Fixed 2026-08-11 on the
    # Honda retro-audit after re-validating against PORSCHE_GLASS.json: the probe
    # scored 103/107, and THREE of the four misses were ground-truth-CLEAR cars
    # banded "faded" (a cull) purely because their transparency lives in a
    # TEXTURE alpha channel. Those materials carry factor alpha = 1.0 by
    # definition -- that is the whole reason texture alpha was added as a signal
    # -- so eff_alpha returns 1.0, which is above the 0.94 faded threshold, and
    # every texture-alpha car banded faded. The texture-alpha extension was
    # meant to rescue the 1987 Porsche 959 and the GT3 RS from "opaque"; it
    # moved them to "faded" instead, and both are culls, so it half-worked and
    # the file recorded it as fixed. Split the two signals apart:
    #   - factor-transparent glazing states its opacity -> band it
    #   - texture-alpha-only glazing asserts per-texel alpha of UNKNOWN
    #     magnitude -> it is transparent, it is NOT bandable, and the only way
    #     to measure it is glass_texture_alpha.py against the image itself.
    # Banding a value the file never states is the same failure the specGloss
    # fix above was written for.
    factor_trans = [x for x in trans if x["via"] == "factor"]
    trans_glazing = [x for x in glazing if x["transparent"]]
    factor_glazing = [x for x in trans_glazing if x["via"] == "factor"]
    if factor_glazing:
        lo = min(eff_alpha(x) for x in factor_glazing)
        verdict = "faded" if lo > 0.94 else "clear"
    elif trans_glazing:
        # glazing is transparent, but only through its texture's alpha channel.
        verdict = "clear"
    elif glazing:
        # glazing material EXISTS by name and is fully opaque. The render
        # worker would still force transmission=1.0 onto it and manufacture
        # clear glass in the sheet -- this is exactly the Porsche failure.
        #
        # Only a FACTOR-transparent material elsewhere in the file can soften
        # this to "ambiguous". A decal, logo, stitch or grid sheet with an alpha
        # channel is not evidence that the car has glass somewhere: measured on
        # 06f8003040f4 ('Porsche 911 Carrera rigged'), whose glazing is
        # literally named "Window_Glass_not_transparent" and whose only
        # transparent materials are Grid/Logo/Stich/Interior_Detail decals. It
        # is ground-truth OPAQUE and the decals were dragging it to ambiguous.
        verdict = "opaque" if not factor_trans else "ambiguous"
    elif [x for x in factor_trans if not LAMPY.search(x["name"])]:
        # no glazing-named material, but something in the file is genuinely
        # transparent by factor. Most likely the glazing under a non-matching
        # name (the clay-shell case shows through in the sheet because no
        # override fires).
        #
        # LAMP LENSES ARE EXCLUDED HERE TOO. The guard above only stops lamps
        # deciding when a glazing NAME exists; this branch had no guard at all,
        # so a file that names no glazing and carries transparent lamps scored
        # "clear" off the lamps alone. Measured 2026-08-11 on the Honda wave:
        # "Honda CR-V MK2 Pre-Facelift" (25 materials, none glazing-named) is a
        # white clay whose windows render in body colour, and its only
        # transparent materials are lamp__car/lamp__car1/lamp__car2 at 0.19 and
        # swiatla_tyl_szkl (Polish for rear light glass) at 0.5. The probe
        # called it "clear" and would have passed an opaque-glazed car.
        lit = [x for x in factor_trans if not LAMPY.search(x["name"])]
        lo = min(eff_alpha(x) for x in lit)
        verdict = "faded" if lo > 0.94 else "clear"
    elif trans:
        # Nothing glazing-named, nothing factor-transparent, but the file DOES
        # carry texture-alpha transparency under names the pattern misses.
        # Measured 2026-08-11 on the Mercedes retro-audit, re-validating against
        # PORSCHE_GLASS.json: 'Porsche 911 GT3 RS (semester 2)' (5fd62615) names
        # no glazing at all and its only transparent materials are UV6_TX and
        # UV4_TX, BLEND with 27 textures and factor alpha 1.0. It is ground-truth
        # CLEAR -- a magenta-backlight render passes light through the glazing --
        # and the plain "opaque" fall-through below scored it OPAQUE, which is an
        # outright FAIL under the owner's ruling. That is the same failure the
        # specGloss and texture-alpha fixes above were both written for: banding
        # an opacity the file never states.
        #
        # It cannot be called "clear" either -- the magnitude of a texture's
        # alpha is unmeasurable from the JSON chunk, and the material is not
        # named as glazing, so we do not even know it IS the glazing. Absence of
        # evidence is "ambiguous", which CLAUDE.md requires be routed to the eye
        # and NEVER treated as a fail. glass_texture_alpha.py resolves it.
        verdict = "ambiguous"
    else:
        # Nothing glazing-named and nothing transparent anywhere in the file.
        # Still only "opaque" with certainty=inferred, which the caller must
        # route to the eye rather than fail -- see the certainty note below.
        verdict = "opaque"

    # An "opaque" verdict reached with NO glazing-named material in the file is
    # INFERRED, not proven: the glTF simply never says which material is the
    # windows. Porsche 5fd62615 (9 materials, 27 textures, nothing named glassy,
    # nothing transparent) is genuinely clear under a magenta backlight, so this
    # class cannot be failed on the probe alone -- it needs the eye or a
    # backlight render. Surfaced as a field so the reviewer can see which
    # opaques are evidence and which are absence of evidence.
    certainty = "proven" if glazing else "inferred"
    return {"uid": uid, "verdict": verdict, "certainty": certainty,
            "n_materials": len(mats),
            "n_transparent": len(trans), "glazing_named": glazing[:6],
            "transparent": trans[:6], "flat_shell": flat,
            "alpha_shell": bool(body_trans), "body_transparent": body_trans[:6],
            "n_textures": len(g.get("images") or [])}


if __name__ == "__main__":
    # usage: glass_probe.py <rows.json> <out.json> [staging-prefix]
    # The stage defaults to the Jeep wave this was first written for; every
    # later wave MUST pass its own, or every probe 404s against the wrong
    # bucket path and the whole marque comes back "unknown".
    import concurrent.futures as cf
    rows = json.load(open(sys.argv[1]))
    stage = sys.argv[3] if len(sys.argv) > 3 else "staging/jeep"

    def one(r):
        try:
            p = probe(r["uid"], stage=stage)
        except Exception as e:
            p = {"uid": r["uid"], "verdict": "unknown",
                 "error": f"{type(e).__name__}: {str(e)[:60]}"}
        p["name"] = r["name"]
        return p

    with cf.ThreadPoolExecutor(8) as ex:
        out = list(ex.map(one, rows))
    for p in out:
        print(f"{p['verdict']:<9} {str(p.get('certainty')):<8} "
              f"flat={str(p.get('flat_shell')):<5} "
              f"trans={p.get('n_transparent')}/{p.get('n_materials')} "
              f"{p['name'][:52]}", flush=True)
    json.dump(out, open(sys.argv[2], "w"), indent=1)
