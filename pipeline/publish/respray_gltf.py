"""Flat respray at the glTF JSON level: set the chosen materials' base colour,
drop their base-colour texture, and give them a paint finish. The binary chunk
(geometry, Draco payload) is copied through untouched.

Why not Blender/bake_colour.py: Blender matches on ITS material names, which can
differ from the glTF ones, and when nothing matches it exports the file silently
unchanged — that is exactly how lexus-ls-w6-v1 shipped two "different" colours
that rendered identically (recolour audit dist = 0.0). Editing the JSON matches
the real glTF names and fails loudly instead.
"""
import json, os, struct

def srgb_to_linear(h):
    def c(x):
        x = int(x, 16) / 255
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return [c(h[0:2]), c(h[2:4]), c(h[4:6])]

def read_gltf(path):
    d = open(path, "rb").read()
    if d[:4] != b"glTF":
        raise ValueError("not a GLB")
    jl = struct.unpack("<I", d[12:16])[0]
    return json.loads(d[20:20 + jl]), d[20 + jl:]

def write_gltf(path, j, rest):
    nj = json.dumps(j, separators=(",", ":")).encode()
    nj += b" " * ((4 - len(nj) % 4) % 4)
    blob = (b"glTF" + struct.pack("<II", 2, 12 + 8 + len(nj) + len(rest))
            + struct.pack("<I", len(nj)) + b"JSON" + nj + rest)
    open(path, "wb").write(blob)
    with open(path, "rb") as f:
        assert struct.unpack("<I", f.read(12)[8:12])[0] == os.path.getsize(path), "GLB length header mismatch"

def paint(m, lin, metallic=0.6, roughness=0.35):
    pmr = m.setdefault("pbrMetallicRoughness", {})
    pmr.pop("baseColorTexture", None)
    pmr["baseColorFactor"] = list(lin) + [1.0]
    pmr["metallicFactor"] = metallic
    pmr["roughnessFactor"] = roughness
    # a car body is not see-through; several of these models ship the paint
    # material as BLEND alpha 0.25, which washes any colour out to nothing
    m["alphaMode"] = "OPAQUE"
    m.pop("KHR_materials_transmission", None)
    ext = m.get("extensions") or {}
    for k in ("KHR_materials_transmission", "KHR_materials_pbrSpecularGlossiness"):
        ext.pop(k, None)
    if ext:
        m["extensions"] = ext
    elif "extensions" in m:
        del m["extensions"]

def respray(src, dst, body_names, hexcol, neutralise_rest=None):
    """Paint body_names hexcol. If neutralise_rest is a hex string, every other
    material is flattened to it — used by the coverage probe so the painted
    surfaces are unmistakable."""
    j, rest = read_gltf(src)
    want = set(body_names)
    lin = srgb_to_linear(hexcol)
    hit = []
    for m in j.get("materials", []):
        nm = m.get("name") or ""
        if nm in want:
            paint(m, lin)
            hit.append(nm)
        elif neutralise_rest:
            paint(m, srgb_to_linear(neutralise_rest), metallic=0.0, roughness=0.8)
    missing = sorted(want - set(hit))
    if missing:
        raise KeyError(f"materials not present in {os.path.basename(src)}: {missing}")
    write_gltf(dst, j, rest)
    return hit
