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

2. TRIPO'S BAKED PAINT IS NOT CONSISTENT BETWEEN RUNS, so the look has to
   be a named choice rather than whatever came back. Same car, same
   photos, one generation from a single image and one from four:

                     roughness   metallic
       v31 (1 img)     0.150       0.603     deep glossy near-black
       mv4 (4 img)     0.222       0.124     matte grey

   — off a base colour that is identical to within a couple of levels.
   The owner picked the first by eye out of five variants and then asked
   for the multiview car to look like it, which is only reachable by
   overriding the bake.

   See PRESETS below. `asbaked` keeps whatever the generator produced;
   `studio` pins the measured v31 numbers; `premium` is the production
   brief. The brief and the owner's eye disagree here and that is not
   resolved in code — the eye is this project's arbiter, and whichever
   preset ran is printed and stored in the file.

BIN chunk verbatim, no geometry touched. Refuses on a no-op and verifies
by reading the written file back.

Run: python3 paint_pbr.py <in.glb> <out.glb>
         [--preset asbaked|studio|premium] [--material carpaint]
         [--rough R] [--clearcoat C]
"""
import argparse
import json
import os
import struct

# metallic, roughness, clearcoat, drop_mr_texture
#   None on a factor = leave the key ABSENT (the glTF default applies)
PRESETS = {
    # whatever the generator baked, untouched
    "asbaked": (None, None, None, False),
    # THE OWNER-CHOSEN LOOK, and these two numbers are MEASURED, not
    # invented. The single-image v31 Golf reads as deep glossy near-black
    # paint and the four-image Golf reads as matte grey, off an IDENTICAL
    # base colour (60.3/62.1/63.7 against 62.9/63.6/63.8). The whole
    # difference is Tripo's baked metallicRoughness texture:
    #     v31   roughness 0.150   metallic 0.603
    #     mv4   roughness 0.222   metallic 0.124
    # So it is a property of the GENERATION, not of this chain, and no
    # factor can rescue it — a glTF factor MULTIPLIES the texture, so a
    # metallicFactor of 1.0 still leaves 0.124 metal. The texture binding
    # has to go, and the v31 averages take its place. Per-texel variation
    # is lost; on an MR bake that variation is mostly noise.
    "studio": (0.60, 0.15, None, True),
    # the production brief's paint values
    "premium": (0.0, 0.24, 0.08, True),
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
            None if cc is None else cc.get("clearcoatRoughnessFactor"),
            "metallicRoughnessTexture" in pbr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--preset", default="studio", choices=sorted(PRESETS))
    ap.add_argument("--material", default="carpaint")
    ap.add_argument("--rough", type=float, default=None)
    ap.add_argument("--clearcoat", type=float, default=None)
    a = ap.parse_args()

    metal, rough, cc, drop_mr = PRESETS[a.preset]
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
        if drop_mr:
            pbr.pop("metallicRoughnessTexture", None)
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

    print(f"{a.material}: (metal, rough, clearcoat, has_MR_texture)")
    print(f"  {before[0]}  ->  {got[0]}    preset={a.preset}")
    if drop_mr:
        print(f"  metallicRoughness TEXTURE dropped — a glTF factor "
              f"MULTIPLIES it, so it cannot be overridden any other way")
    print(f"wrote {a.out} ({os.path.getsize(a.out)} bytes; BIN verbatim)")


if __name__ == "__main__":
    main()
