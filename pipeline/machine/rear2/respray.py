#!/usr/bin/env python3
"""respray.py — NAME-TARGETED body respray, the way colour_variants/the viewer do it.

Edits the glTF JSON only; the BIN chunk is copied verbatim, so geometry cannot
be touched. Targets ONLY the material literally named `carpaint`, sets its
baseColorFactor and DROPS its baseColorTexture (a baked texture would otherwise
multiply the new colour away).

This is the control that label-paint can never pass: if the tail lamps were
texels on the body material they would turn blue with it.

Run: python3 respray.py <in.glb> <out.glb> r g b
"""
import json, struct, sys
INP, OUT = sys.argv[1], sys.argv[2]
COL = [float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]), 1.0]
raw = open(INP, "rb").read()
jlen = struct.unpack("<I", raw[12:16])[0]
j = json.loads(raw[20:20+jlen])
rest = raw[20+jlen:]
hit = 0
for m in j["materials"]:
    if m.get("name") == "carpaint":
        pbr = m.setdefault("pbrMetallicRoughness", {})
        pbr["baseColorFactor"] = COL
        pbr.pop("baseColorTexture", None)
        pbr.pop("metallicRoughnessTexture", None)
        pbr["metallicFactor"] = 0.0
        pbr["roughnessFactor"] = 0.28
        hit += 1
if hit != 1:
    raise SystemExit(f"REFUSED: expected exactly one material named carpaint, found {hit}")
nj = json.dumps(j, separators=(",", ":")).encode()
nj += b" " * ((4 - len(nj) % 4) % 4)
out = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(nj) + len(rest)) + \
      struct.pack("<I", len(nj)) + b"JSON" + nj + rest
open(OUT, "wb").write(out)
print(f"resprayed `carpaint` -> {COL[:3]}, BIN copied verbatim; wrote {OUT}")
