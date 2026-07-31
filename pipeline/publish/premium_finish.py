"""Premium finish pass: clear-coat paint + real glass, at the glTF JSON level.

Two changes, both material-only, both reversible, neither touching geometry:

1. CLEAR COAT. Real car paint is a coloured base under a glossy transparent
   layer; that layer is where the wet depth and the sharp highlight come from.
   Our resprays currently ship flat metallic 0.6 / roughness 0.35 with no coat,
   which is why the rubric keeps saying "paint finish" rather than "premium".
   KHR_materials_clearcoat is the glTF standard for exactly this and is honoured
   by Blender's glTF importer, so the render worker picks it up with no worker
   change.

2. GLASS. Only 158 of 562 catalogue cars have a glass material at all. On the
   rest, windows are opaque body-coloured panels — which is why a black car
   reads as a solid lump. Where a glass material IS identified, give it real
   transmission, a dark tint and low roughness.

The BIN chunk is copied byte-for-byte, so geometry, Draco payload and file size
are untouched. Writes to a NEW path; nothing live is overwritten.
"""
import json, os, re, struct, sys

CLEARCOAT = "KHR_materials_clearcoat"
TRANSMISSION = "KHR_materials_transmission"
IOR = "KHR_materials_ior"

# A car has TWO kinds of glass and they must not be treated alike. Window glass
# is near-colourless and transmissive; a lamp lens is coloured and must stay
# saturated. The first version of this file matched 'red_glas' on the Golf as
# window glass, made it 86% transmissive, and washed the tail lights out to pink.
LENS = re.compile(r"lamp|light|led|lens|tail|head|brake|signal|indicat|blink|fog|rear_?l|stop",
                  re.I)
WINDOW = re.compile(r"glass|window|windscreen|windshield|screen|glazing", re.I)


def is_window(name):
    """Window glass only: named like glass AND not named like a lamp."""
    return bool(WINDOW.search(name or "")) and not LENS.search(name or "")



def read_glb(path):
    d = open(path, "rb").read()
    if d[:4] != b"glTF":
        raise ValueError("not a GLB")
    jl = struct.unpack("<I", d[12:16])[0]
    return json.loads(d[20:20 + jl]), d[20 + jl:]


def write_glb(path, j, rest):
    nj = json.dumps(j, separators=(",", ":")).encode()
    nj += b" " * ((4 - len(nj) % 4) % 4)
    blob = (b"glTF" + struct.pack("<II", 2, 12 + 8 + len(nj) + len(rest))
            + struct.pack("<I", len(nj)) + b"JSON" + nj + rest)
    open(path, "wb").write(blob)
    with open(path, "rb") as f:
        assert struct.unpack("<I", f.read(12)[8:12])[0] == os.path.getsize(path), \
            "GLB length header mismatch"


def _use(j, ext):
    for k in ("extensionsUsed",):
        j.setdefault(k, [])
        if ext not in j[k]:
            j[k].append(ext)


def premium(src, dst, body_names, glass_names=()):
    """Clear-coat the body materials; make WINDOW glass real glass.

    glass_names is filtered through is_window(), so lamp lenses that happen to
    be named '..._glass' keep their colour instead of being made transparent.
    """
    j, rest = read_glb(src)
    body = set(body_names or [])
    glass = {g for g in (glass_names or []) if is_window(g)}
    lenses = [g for g in (glass_names or []) if g not in glass]
    did_body, did_glass = [], []
    for m in j.get("materials", []):
        nm = m.get("name") or ""
        ext = m.setdefault("extensions", {})
        if nm in body:
            # A clear coat is a full-strength, near-perfectly-smooth layer over
            # the paint. Roughness 0.03 rather than 0.0: a mathematically
            # perfect mirror looks synthetic and shows banding on a 480px render.
            ext[CLEARCOAT] = {"clearcoatFactor": 1.0, "clearcoatRoughnessFactor": 0.03}
            pmr = m.setdefault("pbrMetallicRoughness", {})
            # Drop base roughness slightly so the coat has something glossy under
            # it, but keep it above 0.2 or the flake reads as chrome.
            pmr["roughnessFactor"] = min(float(pmr.get("roughnessFactor", 0.35)), 0.28)
            _use(j, CLEARCOAT)
            did_body.append(nm)
        elif nm in glass:
            pmr = m.setdefault("pbrMetallicRoughness", {})
            pmr["baseColorFactor"] = [0.04, 0.045, 0.05, 1.0]   # dark neutral tint
            pmr["metallicFactor"] = 0.0
            pmr["roughnessFactor"] = 0.03
            ext[TRANSMISSION] = {"transmissionFactor": 0.86}
            ext[IOR] = {"ior": 1.5}
            m["alphaMode"] = "BLEND"
            m["doubleSided"] = True
            _use(j, TRANSMISSION); _use(j, IOR)
            did_glass.append(nm)
        if not ext:
            m.pop("extensions", None)
    if not did_body and not did_glass:
        return None
    write_glb(dst, j, rest)
    return {"clearcoated": did_body, "glass": did_glass, "lens_skipped": lenses}


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    b = sys.argv[3].split(",") if len(sys.argv) > 3 and sys.argv[3] else []
    g = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] else []
    print(premium(src, dst, b, g))
