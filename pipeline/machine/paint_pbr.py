#!/usr/bin/env python3
"""paint_pbr.py — set the body paint's PBR, as the LAST thing the chain does.

TWO REASONS THIS IS ITS OWN STAGE RATHER THAN A LINE INSIDE glass_polish.

1. THE CLEARCOAT WAS BEING SILENTLY EATEN. glass_polish wrote
   KHR_materials_clearcoat onto carpaint and normals_fix ran after it —
   a trimesh round trip, which drops every KHR material extension (the
   recorded trap; TANGENT and NORMAL are the other two casualties of the
   same round trip). Measured on the multiview Golf: CAR_FINAL's carpaint
   carries metallic 0 / roughness 0.24 and `extensions: []`. The core
   pbrMetallicRoughness numbers survived because they are not extensions,
   so the stage's own log line read as a success and half of what it
   claimed was gone. A material edit belongs AFTER the last round trip.

2. THE OWNER PICKS THE PAINT BY EYE, and the two candidates are one
   parameter apart. Presets, so a look is a named choice and not a number
   somebody remembers:

     v31      metallic/roughness ABSENT -> the glTF defaults apply,
              metallic 1.0 and roughness 1.0. Physically this treats the
              baked albedo as a metal's F0, which is wrong on paper and
              is exactly the state CLAUDE.md flagged as the flat-shell
              trap. It also renders the near-black, high-contrast studio
              car the owner chose on 2026-08-29 out of five variants.
     premium  metallic 0, roughness 0.24, clearcoat 1.0 @ 0.08 — the
              production brief's paint values.

   The disagreement is real and it is not resolved here. The owner's eye
   is the arbiter in this project; the brief is the default. Whichever
   runs, the file states plainly which one it was.

BIN chunk verbatim, no geometry touched. Refuses on a no-op and verifies
by reading the written file back.

Run: python3 paint_pbr.py <in.glb> <out.glb> [--preset v31|premium]
                                             [--material carpaint]
                                             [--rough R] [--clearcoat C]
"""
import argparse
import json
import os
import struct

PRESETS = {
    # metallic, roughness, clearcoat  (None = leave the key ABSENT)
    "v31": (None, None, None),
    "premium": (0.0, 0.24, 0.08),
}


def read_glb(path):
    d = open(path, "rb").read()
    if d[:4] != b"glTF":
        raise SystemExit(f"REFUSED: {path} is not a binary glTF")
    n = struct.unpack("<I", d[12:16])[0]
    return json.loads(d[20:20 + n]), d[20 + n:]


def write_glb(path, j, rest):
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    with open(path, "wb") as fh:
        fh.write(b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + len(rest)))
        fh.write(struct.pack("<I", len(js)) + b"JSON" + js)
        fh.write(rest)


def describe(m):
    pbr = m.get("pbrMetallicRoughness", {})
    cc = m.get("extensions", {}).get("KHR_materials_clearcoat")
    return (pbr.get("metallicFactor"), pbr.get("roughnessFactor"),
            None if cc is None else cc.get("clearcoatRoughnessFactor"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--preset", default="v31", choices=sorted(PRESETS))
    ap.add_argument("--material", default="carpaint")
    ap.add_argument("--rough", type=float, default=None)
    ap.add_argument("--clearcoat", type=float, default=None)
    a = ap.parse_args()

    metal, rough, cc = PRESETS[a.preset]
    if a.rough is not None:
        rough = a.rough
    if a.clearcoat is not None:
        cc = a.clearcoat

    j, rest = read_glb(a.inp)
    hits = [m for m in j.get("materials", []) if m.get("name") == a.material]
    if not hits:
        have = [m.get("name") for m in j.get("materials", [])]
        raise SystemExit(f"REFUSED: no material named {a.material!r}; "
                         f"this file has {have}")

    before = [describe(m) for m in hits]
    for m in hits:
        pbr = m.setdefault("pbrMetallicRoughness", {})
        for key, val in (("metallicFactor", metal), ("roughnessFactor", rough)):
            if val is None:
                pbr.pop(key, None)
            else:
                pbr[key] = val
        ext = m.setdefault("extensions", {})
        if cc is None:
            ext.pop("KHR_materials_clearcoat", None)
            if not ext:
                m.pop("extensions")
        else:
            ext["KHR_materials_clearcoat"] = {
                "clearcoatFactor": 1.0, "clearcoatRoughnessFactor": cc}
    after = [describe(m) for m in hits]

    if before == after:
        raise SystemExit(f"REFUSED: preset {a.preset!r} is already what "
                         f"{a.material!r} carries — writing an unchanged copy "
                         f"would be a no-op dressed as a fix")

    used = j.setdefault("extensionsUsed", [])
    if cc is None:
        still = any("KHR_materials_clearcoat" in m.get("extensions", {})
                    for m in j.get("materials", []))
        if not still and "KHR_materials_clearcoat" in used:
            used.remove("KHR_materials_clearcoat")
    elif "KHR_materials_clearcoat" not in used:
        used.append("KHR_materials_clearcoat")
    if not used:
        j.pop("extensionsUsed")

    write_glb(a.out, j, rest)

    # verify on the WRITTEN file — the point of this stage is that an
    # earlier edit did NOT survive to the file, and nothing checked.
    j2, _ = read_glb(a.out)
    got = [describe(m) for m in j2.get("materials", [])
           if m.get("name") == a.material]
    if got != after:
        raise SystemExit(f"REFUSED: read-back disagrees: {got} != {after}")

    lbl = "metallic/roughness (glTF defaults 1.0/1.0 apply)"
    print(f"{a.material}: {before[0]} -> {got[0]}   preset={a.preset}")
    if metal is None:
        print(f"  {a.preset}: {lbl} — the owner-chosen studio look; "
              f"physically it treats baked albedo as metal F0")
    else:
        print(f"  {a.preset}: production-brief paint, clearcoat 1.0 @ {cc}")
    print(f"wrote {a.out} ({os.path.getsize(a.out)} bytes; BIN verbatim)")


if __name__ == "__main__":
    main()
