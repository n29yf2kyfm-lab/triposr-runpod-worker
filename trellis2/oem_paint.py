"""OEM paint stage for GENERATED models.

Artist/catalog models get recoloured by material name (see the blender
pipeline on the lovable-connection branch); generated TRELLIS.2 models bake
everything into ONE unnamed material, so this works in texture space instead:
find the body-paint pixels in the baked baseColor texture (dominant chroma
cluster), remap them to the target OEM colour preserving per-pixel shading,
and set finish-appropriate metallic/roughness over the same mask.

Input (handler): oem_paint: {"hex": "#0E2A1B", "finish": "Metallic"}
             or  oem_paint: {"name": "Mythos Black Metallic"}  (name lookup)
"""
import json
import os
import struct
import sys
from io import BytesIO

import numpy as np
from PIL import Image

# name -> hex for common paints; the full 280-paint DB (oem_paints.json)
# carries name/family/finish and joins with the app's OEM colour feature —
# enrich hexes there over time.
NAMED_HEX = {
    "mythos black metallic": "#0B0B0D", "brilliant black": "#050505",
    "glacier white metallic": "#E9EBEA", "ibis white": "#F2F3F1",
    "nardo grey": "#B3B8B8", "daytona grey pearl": "#454A4F",
    "manhattan grey metallic": "#5B6166", "florett silver metallic": "#C4C8CB",
    "navarra blue metallic": "#1F3D6E", "district green metallic": "#1E3B2C",
    "tango red metallic": "#8E1B21", "chronos grey metallic": "#6E7377",
    "phytonic blue metallic": "#1E3A5C", "carbon black metallic": "#111318",
    "alpine white": "#F4F5F3", "black sapphire metallic": "#101216",
    "mineral grey metallic": "#63676B", "portimao blue metallic": "#1F4E8C",
    "deep black pearl": "#0A0B0D", "pure white": "#F2F3F1",
    "dolphin grey metallic": "#7C8085", "atlantic blue metallic": "#1D3A63",
    "lapiz blue metallic": "#1955A5", "grasmere green": "#9AA792",
    "fuji white": "#F1F2EF", "santorini black metallic": "#0C0D0F",
    "byron blue metallic": "#22405F", "eiger grey": "#8B9094",
}

FINISH_PBR = {  # metallic factor, roughness multiplier over paint mask
    "metallic": (0.85, 0.55),
    "pearl": (0.65, 0.50),
    "solid": (0.10, 0.80),
    "matte": (0.15, 1.60),
}


def _tex_source(tex):
    """glTF texture source; WebP textures store it under EXT_texture_webp."""
    if "source" in tex:
        return tex["source"]
    for ext in (tex.get("extensions") or {}).values():
        if isinstance(ext, dict) and "source" in ext:
            return ext["source"]
    raise KeyError("texture has no source")


def _resolve(spec):
    if not isinstance(spec, dict):
        return None
    hexv = spec.get("hex")
    finish = (spec.get("finish") or "").lower()
    name = (spec.get("name") or "").lower().strip()
    if not hexv and name:
        hexv = NAMED_HEX.get(name)
        if not finish:
            for k in FINISH_PBR:
                if k in name:
                    finish = k
    if not hexv:
        return None
    hexv = hexv.lstrip("#")
    rgb = np.array([int(hexv[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float64)
    return rgb, (finish if finish in FINISH_PBR else "metallic")


def apply_oem_paint(glb_path, spec):
    """Repaint the body-paint region of a generated GLB. Returns dict report
    or None if not applied."""
    resolved = _resolve(spec)
    if not resolved:
        return None
    target_rgb, finish = resolved
    try:
        data = open(glb_path, "rb").read()
        if data[:4] != b"glTF":
            return None
        jlen, jtype = struct.unpack("<II", data[12:20])
        j = json.loads(data[20:20 + jlen])
        rest = data[20 + jlen:]
        blen = struct.unpack("<I", rest[0:4])[0]
        bin_data = bytearray(rest[8:8 + blen])

        mat = j["materials"][0]
        pbr = mat.get("pbrMetallicRoughness", {})
        bc_img_i = _tex_source(j["textures"][pbr["baseColorTexture"]["index"]])
        bv = j["bufferViews"][j["images"][bc_img_i]["bufferView"]]
        off, ln = bv.get("byteOffset", 0), bv["byteLength"]
        im = Image.open(BytesIO(bytes(bin_data[off:off + ln]))).convert("RGBA")
        arr = np.asarray(im).astype(np.float64)
        rgb, alpha = arr[..., :3], arr[..., 3:]

        # --- paint mask: dominant chroma cluster among opaque, non-dark,
        # non-neutral pixels (excludes tyres/trim/glass/lights/chrome) ---
        mx, mn = rgb.max(-1), rgb.min(-1)
        sat = (mx - mn) / np.maximum(mx, 1)
        val = mx / 255.0
        chromatic = (sat > 0.12) & (val > 0.10) & (alpha[..., 0] > 200)
        if chromatic.mean() > 0.02:  # chromatic paint (green/blue/red...)
            hsv = np.asarray(im.convert("RGB").convert("HSV")).astype(np.int16)
            hues = hsv[..., 0][chromatic]
            dom = np.bincount(hues, minlength=256).argmax()
            dh = np.abs(hsv[..., 0].astype(np.int16) - int(dom))
            dh = np.minimum(dh, 256 - dh)
            mask = chromatic & (dh < 18)
        else:  # achromatic paint (black/white/grey): luminance band
            lum = rgb.mean(-1)
            sel = (alpha[..., 0] > 200) & (sat <= 0.12)
            med = np.median(lum[sel]) if sel.any() else 128.0
            mask = sel & (np.abs(lum - med) < 85)
        # heal the mask: close speckle holes (baked highlights/reflections
        # fall outside the band and leave unpainted flecks otherwise)
        from PIL import ImageFilter
        m_im = Image.fromarray((mask * 255).astype(np.uint8))
        m_im = m_im.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MinFilter(5))
        mask = np.asarray(m_im) > 127
        frac = float(mask.mean())
        if frac < 0.03:
            print(f"oem_paint: paint mask too small ({frac:.3f}), skipped",
                  file=sys.stderr)
            return None

        # --- recolour: preserve shading via per-pixel luminance ratio ---
        lum = rgb.mean(-1, keepdims=True)
        ref = np.median(lum[mask.squeeze() if lum.ndim == 3 else mask])
        shade = np.clip(lum / max(ref, 1.0), 0.05, 2.2)
        painted = np.clip(target_rgb[None, None, :] * shade, 0, 255)
        rgb = np.where(mask[..., None], painted, rgb)
        out = np.concatenate([rgb, alpha], -1).astype(np.uint8)

        buf = BytesIO()
        mime = j["images"][bc_img_i].get("mimeType", "image/webp")
        fmt = "WEBP" if "webp" in mime else "PNG"
        Image.fromarray(out).save(buf, fmt, quality=95)
        new_tex = buf.getvalue()

        # --- metallic/roughness over the same mask ---
        met_f, rough_m = FINISH_PBR[finish]
        mr_ref = pbr.get("metallicRoughnessTexture")
        new_mr = None
        if mr_ref is not None:
            mr_img_i = _tex_source(j["textures"][mr_ref["index"]])
            mrbv = j["bufferViews"][j["images"][mr_img_i]["bufferView"]]
            mro, mrl = mrbv.get("byteOffset", 0), mrbv["byteLength"]
            mrim = Image.open(BytesIO(bytes(bin_data[mro:mro + mrl]))).convert("RGB")
            mr = np.asarray(mrim).astype(np.float64)
            if mr.shape[:2] == mask.shape:
                mr[..., 2] = np.where(mask, met_f * 255, mr[..., 2])          # B=metallic
                mr[..., 1] = np.where(mask, np.clip(mr[..., 1] * rough_m, 8, 255), mr[..., 1])  # G=roughness
                b2 = BytesIO()
                mrmime = j["images"][mr_img_i].get("mimeType", "image/webp")
                Image.fromarray(mr.astype(np.uint8)).save(
                    b2, "WEBP" if "webp" in mrmime else "PNG", quality=95)
                new_mr = (mr_img_i, b2.getvalue())

        # --- rebuild BIN with replaced textures (append-new, repoint views) ---
        def append_blob(blob):
            start = len(bin_data)
            bin_data.extend(blob)
            while len(bin_data) % 4:
                bin_data.append(0)
            return start
        nbv = j["bufferViews"]
        s = append_blob(new_tex)
        nbv.append({"buffer": 0, "byteOffset": s, "byteLength": len(new_tex)})
        j["images"][bc_img_i]["bufferView"] = len(nbv) - 1
        if new_mr:
            s = append_blob(new_mr[1])
            nbv.append({"buffer": 0, "byteOffset": s, "byteLength": len(new_mr[1])})
            j["images"][new_mr[0]]["bufferView"] = len(nbv) - 1
        j["buffers"][0]["byteLength"] = len(bin_data)

        nj = json.dumps(j, separators=(",", ":")).encode()
        nj += b" " * ((4 - len(nj) % 4) % 4)
        out_glb = (data[:8]
                   + struct.pack("<I", 12 + 8 + len(nj) + 8 + len(bin_data))
                   + struct.pack("<II", len(nj), jtype) + nj
                   + struct.pack("<I", len(bin_data)) + b"BIN\x00" + bytes(bin_data))
        open(glb_path, "wb").write(out_glb)
        print(f"oem_paint: applied #{spec.get('hex') or spec.get('name')} "
              f"({finish}) over {frac:.1%} of texture", file=sys.stderr)
        return {"applied": True, "finish": finish, "coverage": round(frac, 4)}
    except Exception as e:
        print(f"oem_paint skipped: {e}", file=sys.stderr)
        return None
