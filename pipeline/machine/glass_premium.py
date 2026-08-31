#!/usr/bin/env python3
"""glass_premium.py — make a car's glazing read as GLASS, not tinted plastic.

Owner request 2026-08-31, on the Clio being served for SN66OGL: "clean the
windscreens and clean the glass and make it more premium."

WHAT ACTUALLY MAKES GLASS LOOK DIRTY, measured on the two library Clios
rather than assumed:

  renault-clio-2010-w7-v1  clearglass  roughness 0.755   <- FROSTED
                           greenglass  roughness 0.723
  renault-clio-w8-v1       Vitres      baseColor [0.54, 1.00, 0.77]
                                       a strong GREEN cast, alpha 0.70

Roughness is the big one. A rough glazing material scatters the
reflection into a haze, and at 0.72-0.76 that is frosted bathroom glass.
Real automotive glazing sits near 0.03. The second is the colour cast:
laminated screens are very slightly green in reality but nothing like
[0.54, 1.00, 0.77], which paints the cabin bottle-green.

And BOTH cars fake transparency with alphaMode BLEND. Blending cannot
refract, so the glass has no thickness and no depth — it reads as tinted
film. KHR_materials_transmission with an IOR gives real refraction.

THE LAMP TRAP, and it is why this is not a blanket pass: `orangeglass`
and `redglass` on the 2010 are the INDICATORS and TAIL LAMPS. They are
correctly coloured and correctly rough-ish, and neutralising them would
delete the car's light signature. Only true GLAZING is touched; anything
whose name reads as a lamp is left exactly as it is and reported.

Edits the glTF JSON with the BIN chunk verbatim (the pose_fix pattern), so
geometry, UVs and textures cannot be harmed, and KHR extensions survive —
a trimesh round-trip would silently drop them (recorded trap).

Run: python3 glass_premium.py <in.glb> <out.glb> [--tint 0.86]
                              [--rough 0.03] [--clearcoat]
"""
import argparse
import json
import struct

GLAZING = ("vitre", "glass", "window", "windscreen", "windshield",
           "scheibe", "fenster", "vidro", "glazing")
# a name that contains a glazing word but is a LAMP, a mirror or a screen
NOT_GLAZING = ("phare", "lamp", "light", "head", "tail", "fog", "indicator",
               "orange", "red", "amber", "blink", "mirror", "rearview",
               "touch", "dash", "instrument", "surr")
PAINTY = ("carpaint", "paint", "carroserie", "carrosserie", "body", "lack")


def read(p):
    d = open(p, "rb").read()
    if d[:4] != b"glTF":
        raise SystemExit(f"REFUSED: {p} is not a binary glTF")
    n = struct.unpack("<I", d[12:16])[0]
    return json.loads(d[20:20 + n]), d[20 + n:]


def write(p, j, rest):
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    with open(p, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + len(rest)))
        f.write(struct.pack("<I", len(js)) + b"JSON" + js + rest)


def is_glazing(n):
    s = n.lower()
    return any(g in s for g in GLAZING) and not any(x in s for x in NOT_GLAZING)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--rough", type=float, default=0.03,
                    help="glazing roughness; real automotive glass ~0.03")
    ap.add_argument("--tint", type=float, default=0.86,
                    help="how much light the glazing passes (transmission)")
    ap.add_argument("--clearcoat", action="store_true",
                    help="also give the body paint a clearcoat")
    a = ap.parse_args()

    j, rest = read(a.inp)
    mats = j.get("materials", [])
    if not mats:
        raise SystemExit("REFUSED: no materials to work on")

    used = set(j.get("extensionsUsed", []))
    touched, lamps, painted = [], [], []
    for m in mats:
        nm = m.get("name", "") or ""
        pbr = m.setdefault("pbrMetallicRoughness", {})
        if is_glazing(nm):
            before = {"alphaMode": m.get("alphaMode", "OPAQUE"),
                      "baseColorFactor": pbr.get("baseColorFactor"),
                      "roughnessFactor": pbr.get("roughnessFactor")}
            # a windscreen is very slightly cool, never bottle-green
            pbr["baseColorFactor"] = [0.86, 0.89, 0.91, 1.0]
            pbr["roughnessFactor"] = a.rough
            pbr["metallicFactor"] = 0.0
            # REAL transparency: transmission refracts, alpha-blend cannot.
            # Set alphaMode back to OPAQUE — with transmission present,
            # leaving BLEND on double-darkens and re-introduces the sort
            # artefacts blending is famous for.
            m["alphaMode"] = "OPAQUE"
            ex = m.setdefault("extensions", {})
            ex["KHR_materials_transmission"] = {"transmissionFactor": a.tint}
            ex["KHR_materials_ior"] = {"ior": 1.52}          # soda-lime glass
            used.update(["KHR_materials_transmission", "KHR_materials_ior"])
            touched.append((nm, before))
        elif any(x in nm.lower() for x in ("phare", "lamp", "light",
                                           "orange", "red", "tail")):
            lamps.append(nm)
        elif any(p in nm.lower() for p in PAINTY) and a.clearcoat:
            ex = m.setdefault("extensions", {})
            ex["KHR_materials_clearcoat"] = {"clearcoatFactor": 1.0,
                                             "clearcoatRoughnessFactor": 0.06}
            used.add("KHR_materials_clearcoat")
            pbr.setdefault("roughnessFactor", 0.28)
            painted.append(nm)

    if not touched:
        raise SystemExit(
            f"REFUSED: no glazing material found. Names present: "
            f"{[m.get('name') for m in mats]} — a rename is a per-car "
            f"decision, not something this tool should guess")

    j["extensionsUsed"] = sorted(used)
    write(a.out, j, rest)

    print(f"glazing cleaned on {len(touched)} material(s):")
    for nm, b in touched:
        bc = b["baseColorFactor"]
        print(f"  {nm}")
        print(f"    was: {b['alphaMode']:6s} colour "
              f"{[round(x,3) for x in bc] if bc else 'none'} "
              f"rough {b['roughnessFactor']}")
        print(f"    now: OPAQUE + transmission {a.tint} + IOR 1.52, "
              f"colour [0.86,0.89,0.91] rough {a.rough}")
    if lamps:
        print(f"left alone (lamps/indicators keep their colour): {lamps}")
    if painted:
        print(f"clearcoat added to: {painted}")
    # verify the written file rather than trusting intent
    j2, _ = read(a.out)
    got = [m.get("name") for m in j2.get("materials", [])
           if "KHR_materials_transmission" in (m.get("extensions") or {})]
    assert len(got) == len(touched), "transmission missing from the written file"
    print(f"verified in {a.out}: transmission present on {got}")


if __name__ == "__main__":
    main()
