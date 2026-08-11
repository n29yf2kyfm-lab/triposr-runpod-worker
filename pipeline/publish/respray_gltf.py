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

_BLENDER_ID_MAX = 63          # bpy.types.ID.name is capped at 63 characters

def resolve_names(want, have):
    """Map recorded paint material names onto the names actually in the glTF.

    paintMaterialNames is measured by the render worker's mat_audit, which runs
    in BLENDER, so the names it records are Blender IDs — and Blender mangles
    them on import in two ways that make a literal lookup fail against the glTF:

      * it appends `.001`, `.002`… to disambiguate, inventing names that were
        never in the file. Measured: `C1_Paint.001` recorded against a glTF that
        holds one `C1_Paint`; `pan_paint.002` against a glTF holding only
        `pan_paint.001`; `CarPaint.001` against a glTF holding `CarPaint`.
      * it truncates at 63 characters. Measured:
        `Porsche_PanameraSportTurismoRewardRecycled_2021Coloured_Materia`
        recorded for a real `…Coloured_Material` — one letter short, exactly 63.

    Four cars (three Porsches and a Jaecoo) lost their eight colours to this,
    all reported as "materials not present", which reads like a bad audit rather
    than a name-space mismatch.

    Resolution is deliberately narrow so it cannot widen the paint onto trim:
    an exact hit is taken as-is and stops there; only when a name has NO exact
    match is it allowed to fall back to its `.NNN` base, then to its siblings,
    then — only at exactly 63 characters — to a prefix. Returns the set of real
    glTF names to paint.
    """
    have = list(have)
    hs = set(have)
    out = set()
    unresolved = []
    for w in want:
        if w in hs:                                   # exact — never widen
            out.add(w)
            continue
        base = w.rsplit(".", 1)[0] if w.rsplit(".", 1)[-1].isdigit() else w
        if base != w and base in hs:                  # C1_Paint.001 -> C1_Paint
            out.add(base)
            continue
        sib = [h for h in have
               if h.startswith(base + ".") and h[len(base) + 1:].isdigit()]
        if sib:                                       # pan_paint.002 -> .001
            out.update(sib)
            continue
        if len(w) == _BLENDER_ID_MAX:                 # truncated at Blender's cap
            pre = [h for h in have if h.startswith(w)]
            if pre:
                out.update(pre)
                continue
        unresolved.append(w)
    return out, sorted(unresolved)

def respray(src, dst, body_names, hexcol, neutralise_rest=None):
    """Paint body_names hexcol. If neutralise_rest is a hex string, every other
    material is flattened to it — used by the coverage probe so the painted
    surfaces are unmistakable."""
    j, rest = read_gltf(src)
    lin = srgb_to_linear(hexcol)
    have = [(m.get("name") or "") for m in j.get("materials", [])]
    want, unresolved = resolve_names(set(body_names), have)
    if not want:
        # Nothing at all matched: the audit named materials this file does not
        # contain in any form. Still a hard failure — painting nothing would
        # ship eight identical files.
        raise KeyError(f"materials not present in {os.path.basename(src)}: "
                       f"{sorted(set(body_names))}")
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
