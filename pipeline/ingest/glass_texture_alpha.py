#!/usr/bin/env python3
"""Resolve glass_probe's one genuinely ambiguous class: TEXTURE-DRIVEN ALPHA.

Why this exists
---------------
`glass_probe` decides transparency from the glTF material's *factors* --
`alphaMode`, `baseColorFactor[3]`, `KHR_materials_transmission`. That is
decisive for most files and free, because it only needs the JSON chunk.

It cannot measure one common authoring style: `alphaMode=BLEND` with
`baseColorFactor` alpha left at 1.0 and the real transparency living in the
baseColorTexture's ALPHA CHANNEL. The probe correctly flags those as
transparent (a material set to BLEND *with* a texture is asserting per-texel
alpha) but has to band them "faded", because a factor of 1.0 is all it can see.
Its own comment says so: "the factor cannot tell us HOW transparent the texture
is."

That ambiguity matters, and the audit sheet usually cannot break the tie:
render/handler.py force-overrides `transmission=1.0` onto any material whose
NAME matches glass/window/..., so for a material called `windows_glass` the
sheet's clear glazing is manufactured by the worker and is not evidence.
(Where the glazing carries a non-matching name -- `Index_0_2` on the Mazda CX-5
below -- no override fires and the sheet IS honest. Whether the sheet lies
depends entirely on the material's name.)

This module pulls the texture out of the GLB's binary chunk and measures the
alpha channel directly. Measured on the Mazda wave 2026-08-11:

  Mazda 6 / Atenza Sport  'windows_glass'  128x128  LA
      alpha mean 64.5/255 (opacity 0.25), 100% of texels below 230 -> CLEAR
  Mazda CX-5 2020 (KF)    'Index_0_2'      1024x1024 RGBA
      alpha mean 91.7/255 (opacity 0.36), 100% of texels below 230 -> CLEAR

Both had been banded "faded" by the factor test; both are properly transparent
glazing, and both are core UK fleet cars that a factor-only reading would have
put at risk.

The other outcome this catches is a material that DECLARES BLEND but ships a
texture with no alpha channel at all -- transparency asserted and not delivered.

Usage:
    glass_texture_alpha.py <uid> <material-name> [staging-prefix]
"""
import io, json, struct, sys, urllib.request

SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"

# Above this the texel is effectively opaque. 230/255 = 0.90, which sits just
# under CLAUDE.md's Porsche calibration: glazing as heavy as alpha 0.78-0.94
# still resolves the interior and far-side openings under a backlight.
OPAQUE_TEXEL = 230


def load_glb(uid, stage):
    url = f"{SB}/storage/v1/object/public/{BUCKET}/{stage}/{uid}.glb"
    return urllib.request.urlopen(url, timeout=900).read()


def chunks(b):
    """Return (gltf_json, binary_chunk). The JSON chunk is always first."""
    if b[:4] != b"glTF":
        raise RuntimeError("not a glb")
    jlen = struct.unpack("<I", b[12:16])[0]
    g = json.loads(b[20:20 + jlen].decode("utf-8", "replace"))
    off, binary = 20 + jlen, None
    while off < len(b):
        clen = struct.unpack("<I", b[off:off + 4])[0]
        if b[off + 4:off + 8] == b"BIN\x00":
            binary = b[off + 8:off + 8 + clen]
            break
        off += 8 + clen
    return g, binary


def alpha_stats(uid, material_name, stage="staging/mazda"):
    """Measure the alpha channel of one material's baseColorTexture."""
    from PIL import Image
    g, binary = chunks(load_glb(uid, stage))
    for m in g.get("materials", []):
        if m.get("name") != material_name:
            continue
        pbr = m.get("pbrMetallicRoughness") or {}
        sg = (m.get("extensions") or {}).get(
            "KHR_materials_pbrSpecularGlossiness") or {}
        tex = pbr.get("baseColorTexture") or sg.get("diffuseTexture")
        if not tex:
            return {"material": material_name, "verdict": "no-texture",
                    "factor": pbr.get("baseColorFactor")
                    or sg.get("diffuseFactor")}
        img = g["images"][g["textures"][tex["index"]]["source"]]
        bv = g["bufferViews"][img["bufferView"]]
        o = bv.get("byteOffset", 0)
        im = Image.open(io.BytesIO(binary[o:o + bv["byteLength"]]))
        # PALETTE PNGs CARRY THEIR ALPHA IN tRNS, NOT IN THE MODE STRING.
        # Found 2026-08-11 on the O-Z live audit. Pillow reports mode "P" for a
        # paletted PNG even when a tRNS chunk gives per-palette-entry alpha, so
        # the mode test below scored them "declared-not-delivered" -- i.e. BLEND
        # asserted and no transparency delivered, which reads as OPAQUE and is a
        # cull. Five live cars hit it, and every one is genuinely transparent
        # once tRNS is honoured:
        #   toyota-c-hr-2022-tw1-v1        'Index_0_3'  1024x1024 P  opacity 0.226
        #   toyota-highlander-2020-tw1-v1  'Index_0_2'  1024x1024 P  opacity 0.270
        #   toyota-mirai-tw1-v1            'Index_0_3'  1024x1024 P  opacity 0.270
        #   volkswagen-golf-gti-2021-vw2-v1'Index_0_3'  1024x1024 P  opacity 0.173
        #   subaru-impreza-22b-sti-...     'mat06'      64x64     P  opacity 0.188
        # Their RGBA-encoded siblings (toyota-c-hr-v1, toyota-highlander-v1) read
        # 0.226/0.270 -- the SAME numbers -- so this is one source re-encoded to a
        # palette, not a different authoring choice. im.convert("RGBA") expands
        # tRNS correctly; the only thing needed is to stop rejecting the mode.
        # Same failure class as the KHR_texture_basisu KeyError already recorded
        # in CLAUDE.md: a measurement that FAILED must never score as "opaque".
        if im.mode == "P" and "transparency" in im.info:
            pass
        elif im.mode not in ("RGBA", "LA", "PA"):
            # BLEND was declared and no alpha shipped: nothing is transparent.
            return {"material": material_name, "verdict": "declared-not-delivered",
                    "size": im.size, "mode": im.mode}
        a = im.convert("RGBA").getchannel("A").resize((64, 64))
        px = list(a.getdata())
        n = len(px)
        mean = sum(px) / n
        see_through = sum(1 for p in px if p < OPAQUE_TEXEL) / n
        return {"material": material_name, "size": im.size, "mode": im.mode,
                "alpha_mean_255": round(mean, 1),
                "opacity": round(mean / 255, 3),
                "alpha_min": min(px), "alpha_max": max(px),
                "frac_see_through": round(see_through, 2),
                "verdict": "clear" if see_through >= 0.5 else "opaque"}
    raise KeyError(f"material {material_name!r} not in {uid}")


if __name__ == "__main__":
    uid = sys.argv[1]
    name = sys.argv[2]
    stage = sys.argv[3] if len(sys.argv) > 3 else "staging/mazda"
    print(json.dumps(alpha_stats(uid, name, stage), indent=1))
