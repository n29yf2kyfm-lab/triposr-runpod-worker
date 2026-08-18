#!/usr/bin/env python3
"""materials_pass.py — production PBR pass on the assembled car (Phase 9).

Edits the GLB's JSON chunk directly (the respray_gltf pattern) — no mesh
reload, byte-identical geometry. What it fixes and why:

  * carpaint ships with NO explicit pbr factors, so viewers apply the glTF
    DEFAULTS metallic=1.0 rough=1.0 — the flat-shell trap: paint renders
    near-black metal in any viewer that honours the file. Set the brief's
    paint spec: metallic 0, rough 0.24, clearcoat 1.0 @ 0.08
    (KHR_materials_clearcoat).
  * lens/glass/trim materials get explicit sane factors where absent.
  * declares extensionsUsed for the clearcoat extension.

Run: python3 materials_pass.py <in.glb> <out.glb>
"""
import json
import struct
import sys

INP, OUT = sys.argv[1], sys.argv[2]

with open(INP, "rb") as f:
    head = f.read(12)
    magic, ver, total = struct.unpack("<III", head)
    jlen, jtype = struct.unpack("<II", f.read(8))
    jraw = f.read(jlen)
    rest = f.read()
j = json.loads(jraw)

CLEAR = {"clearcoatFactor": 1.0, "clearcoatRoughnessFactor": 0.08}
touched = []
for m in j.get("materials", []):
    name = m.get("name", "")
    pbr = m.setdefault("pbrMetallicRoughness", {})
    if name == "carpaint":
        pbr["metallicFactor"] = 0.0
        pbr["roughnessFactor"] = 0.24
        m.setdefault("extensions", {})["KHR_materials_clearcoat"] = dict(CLEAR)
        touched.append(f"{name}: metal 0 rough 0.24 clearcoat 1.0@0.08")
    elif name.startswith(("Tail_Lens", "Head_Lens", "Lamp_Lens")):
        # lens gets a clearcoat too — wet gloss over the tinted base
        m.setdefault("extensions", {})["KHR_materials_clearcoat"] = dict(CLEAR)
        touched.append(f"{name}: clearcoat")
    else:
        # any other material missing explicit factors gets non-metal matte
        if "metallicFactor" not in pbr:
            pbr["metallicFactor"] = 0.0
        if "roughnessFactor" not in pbr:
            pbr["roughnessFactor"] = 0.8

if any("KHR_materials_clearcoat" in (m.get("extensions") or {})
       for m in j.get("materials", [])):
    eu = set(j.get("extensionsUsed", []))
    eu.add("KHR_materials_clearcoat")
    j["extensionsUsed"] = sorted(eu)

for t in touched:
    print(" ", t)

jout = json.dumps(j, separators=(",", ":")).encode()
jout += b" " * (-len(jout) % 4)                    # 4-byte alignment
total = 12 + 8 + len(jout) + len(rest)
with open(OUT, "wb") as f:
    f.write(struct.pack("<III", magic, ver, total))
    f.write(struct.pack("<II", len(jout), jtype))
    f.write(jout)
    f.write(rest)
print(f"wrote {OUT} ({total} bytes, {len(touched)} materials touched)")
