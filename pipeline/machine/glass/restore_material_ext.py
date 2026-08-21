#!/usr/bin/env python3
"""restore_material_ext.py — put back the glTF material extensions trimesh drops.

MEASURED on this gate, 2026-08-21: exporting a scene with trimesh 5.0.0 wrote
`extensionsUsed: None`.  The input carried KHR_materials_transmission (0.92),
KHR_materials_ior (1.45) on `glass` and KHR_materials_clearcoat on `carpaint`, and all
three were silently gone from the output.  alphaMode/baseColorFactor survive, so
glass_probe still returns clear/proven and NOTHING in the gate stack would have caught
it -- the glazing would simply have stopped refracting.  Same class as the dropped
NORMAL accessors (CLAUDE.md v7): a lossy export that no downstream check tests for.

This copies, BY MATERIAL NAME, every field the source material carries that the exported
one lacks -- extensions plus scalar PBR fields -- and rebuilds extensionsUsed.  It edits
the glTF JSON chunk only; the BIN chunk is written back verbatim, so geometry cannot be
touched (the clay_rebuild / pose_fix pattern).

Run: restore_material_ext.py <source.glb> <target.glb> [out.glb]
"""
import json
import struct
import sys

COPY_EXT = ("KHR_materials_transmission", "KHR_materials_ior", "KHR_materials_clearcoat",
            "KHR_materials_specular", "KHR_materials_volume", "KHR_materials_sheen",
            "KHR_materials_emissive_strength", "KHR_materials_iridescence")
COPY_TOP = ("alphaMode", "alphaCutoff", "doubleSided", "emissiveFactor")
COPY_PBR = ("baseColorFactor", "metallicFactor", "roughnessFactor")


def read_glb(p):
    b = open(p, "rb").read()
    assert b[:4] == b"glTF", f"{p} is not a GLB"
    jlen = struct.unpack("<I", b[12:16])[0]
    assert b[16:20] == b"JSON"
    j = json.loads(b[20:20 + jlen].decode("utf-8"))
    rest = b[20 + jlen:]
    return j, rest


def write_glb(path, j, rest):
    js = json.dumps(j, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + len(rest)
    with open(path, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, total))
        f.write(struct.pack("<I", len(js)) + b"JSON" + js)
        f.write(rest)


def main():
    src, tgt = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else tgt
    sj, _ = read_glb(src)
    tj, trest = read_glb(tgt)
    smats = {m.get("name"): m for m in sj.get("materials", [])}
    used = set(tj.get("extensionsUsed") or [])
    changed = []
    for m in tj.get("materials", []):
        s = smats.get(m.get("name"))
        if not s:
            continue
        for k in COPY_TOP:
            if k in s and k not in m:
                m[k] = s[k]; changed.append((m["name"], k))
        sp, tp = s.get("pbrMetallicRoughness") or {}, m.setdefault("pbrMetallicRoughness", {})
        for k in COPY_PBR:
            if k in sp and k not in tp:
                tp[k] = sp[k]; changed.append((m["name"], "pbr." + k))
        se = s.get("extensions") or {}
        te = m.setdefault("extensions", {})
        for k in COPY_EXT:
            if k in se and k not in te:
                te[k] = se[k]; used.add(k); changed.append((m["name"], k))
        if not te:
            m.pop("extensions")
    if used:
        tj["extensionsUsed"] = sorted(used)
    write_glb(out, tj, trest)
    print(f"restored {len(changed)} material fields -> {out}")
    for n, k in changed:
        print(f"   {n}: {k}")
    print("extensionsUsed:", tj.get("extensionsUsed"))


if __name__ == "__main__":
    main()
