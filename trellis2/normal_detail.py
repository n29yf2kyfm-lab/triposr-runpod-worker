"""Panel-gap detail pass for GENERATED models.

Shut lines, grille slats and trim seams are painted INTO the baked texture
(dark thin lines) but the voxel geometry underneath is smooth, so panels read
as printed-on (user critique: "no depth to the shut lines"). This derives a
tangent-space normal map from those very lines — thin-dark-feature detection
on the baseColor texture, converted to grooves — and attaches it to the
material. Renderers then light the gaps like real creases.

No TANGENT attribute is added: three.js and Blender both derive tangents in
the shader/importer when a normal map is present (glTF spec fallback).

Input (handler): panel_detail: true (default for generated cars) | false
                 or {"strength": 0.2..3.0}
"""
import json
import struct
import sys
from io import BytesIO

import numpy as np
from PIL import Image, ImageFilter

from wheel_swap import _read_glb, _write_glb


def _tex_source(tex):
    if "source" in tex:
        return tex["source"]
    for ext in (tex.get("extensions") or {}).values():
        if isinstance(ext, dict) and "source" in ext:
            return ext["source"]
    raise KeyError("texture has no source")


def apply_panel_detail(glb_path, spec=True):
    """Attach a shut-line normal map to material 0. Returns report or None."""
    try:
        strength = 1.0
        if isinstance(spec, dict):
            strength = float(np.clip(spec.get("strength", 1.0), 0.2, 3.0))

        j, jtype, bin_data = _read_glb(glb_path)
        mat = j["materials"][0]
        pbr = mat.get("pbrMetallicRoughness", {})
        if "baseColorTexture" not in pbr:
            return None
        if "normalTexture" in mat:
            return None  # already has one; don't stack
        img_i = _tex_source(j["textures"][pbr["baseColorTexture"]["index"]])
        bv = j["bufferViews"][j["images"][img_i]["bufferView"]]
        off, ln = bv.get("byteOffset", 0), bv["byteLength"]
        im = Image.open(BytesIO(bytes(bin_data[off:off + ln]))).convert("RGBA")
        # normal map at half the colour res is plenty for grooves; cap 2048
        nw = min(2048, im.width)
        nh = max(1, round(im.height * nw / im.width))
        side = nw
        arr = np.asarray(im.resize((nw, nh), Image.LANCZOS)).astype(np.float64)
        rgb, alpha = arr[..., :3], arr[..., 3]

        # thin dark lines: dark relative to a small local blur ("black-hat").
        # Responds to shut lines / slats / seams, not to broad shading.
        L = rgb.mean(-1)
        Lb = np.asarray(Image.fromarray(L.astype(np.uint8))
                        .filter(ImageFilter.GaussianBlur(3))).astype(np.float64)
        line = np.clip(Lb - L, 0, None)
        line[alpha < 200] = 0.0            # keep glass/cutout regions flat
        ref = np.percentile(line, 99.5)
        if ref < 4.0:                       # texture has no line features
            print("panel_detail: no line features found, skipped", file=sys.stderr)
            return None
        line = np.clip(line / ref, 0, 1.0) ** 0.8

        # keep only ELONGATED features: a shut line is a ridge, texture
        # noise is round. Structure-tensor coherence separates them — dots
        # rendered as paint blisters in review ("paint work bubbles").
        def box(a, k=4):
            c = np.cumsum(np.cumsum(np.pad(a, ((k + 1, k), (k + 1, k)),
                                           mode="edge"), 0), 1)
            n = 2 * k + 1
            return (c[n:, n:] - c[n:, :-n] - c[:-n, n:] + c[:-n, :-n]) / (n * n)
        gy_l, gx_l = np.gradient(line)
        jxx, jyy, jxy = box(gx_l * gx_l), box(gy_l * gy_l), box(gx_l * gy_l)
        coh = (np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2)
               / np.maximum(jxx + jyy, 1e-12))
        line *= np.clip((coh - 0.35) / 0.25, 0.0, 1.0)

        # tiny blur only — keep seams crisp (reviewed as "a little soft")
        line = np.asarray(Image.fromarray((line * 255).astype(np.uint8))
                          .filter(ImageFilter.GaussianBlur(0.6))).astype(np.float64) / 255

        height = -line * 4.2 * strength     # grooves, in pixel units
        gy, gx = np.gradient(height)        # axis0 = rows, axis1 = cols
        # tangent frame: +X = +U (right), +Y = up = -rows (OpenGL/glTF style)
        nx, ny, nz = -gx, gy, np.ones_like(gx)
        inv = 1.0 / np.sqrt(nx * nx + ny * ny + nz * nz)
        nmap = np.stack([nx * inv, ny * inv, nz * inv], -1)
        nmap_u8 = np.clip((nmap * 0.5 + 0.5) * 255, 0, 255).astype(np.uint8)

        buf = BytesIO()
        Image.fromarray(nmap_u8).save(buf, "PNG", optimize=True)
        blob = buf.getvalue()

        while len(bin_data) % 4:
            bin_data.append(0)
        start = len(bin_data)
        bin_data.extend(blob)
        j["bufferViews"].append({"buffer": 0, "byteOffset": start,
                                 "byteLength": len(blob)})
        j["images"].append({"bufferView": len(j["bufferViews"]) - 1,
                            "mimeType": "image/png", "name": "panel_normal"})
        j.setdefault("textures", []).append({"source": len(j["images"]) - 1})
        mat["normalTexture"] = {"index": len(j["textures"]) - 1}

        _write_glb(glb_path, j, jtype, bin_data)
        cov = float((line > 0.15).mean())
        print(f"panel_detail: normal map {side}px, line coverage {cov:.1%}, "
              f"strength {strength}", file=sys.stderr)
        return {"applied": True, "coverage": round(cov, 4),
                "strength": strength, "size": side}
    except Exception as e:
        print(f"panel_detail skipped: {e}", file=sys.stderr)
        return None
