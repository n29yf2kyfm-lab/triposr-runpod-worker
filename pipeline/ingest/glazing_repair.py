#!/usr/bin/env python3
"""glazing_repair.py — turn an opaque-but-correctly-NAMED glazing material
transparent, as a pure glTF JSON edit.

WHAT THIS IS FOR. 211 of the 358 quarantined catalogue entries were pulled for
opaque glazing (owner ruling 2026-08-11, confirmed: opaque glazing is a scrap
even when the poster is perfect). Probing ten of them 2026-08-28 found that
SEVEN of nine readable cars already carry a properly-named glazing material
bound to the real window geometry — `M_2020_Volvo_V90_Windows`, `darkglass` /
`clearglass`, `d_glass` / `r_glass` / `glass`, `bglassb`. Only the VALUES are
wrong: alphaMode OPAQUE, baseColorFactor alpha 1.0, no transmission.

That is the opposite of the generated-car problem. On a generated mesh there is
no glass material and the hard part is deciding WHICH FACES are windows. Here
the face binding is already correct and only the material needs fixing, which
is a JSON edit with the BIN chunk copied verbatim — so geometry, UVs and Draco
payload cannot be touched (the clay_rebuild pattern).

WHAT IT IS NOT. It does not prove the car reads as glass afterwards. A material
flagged BLEND can still be bound to a windscreen-shaped SOLID, and this repo
has been repeatedly burned by material-table readings that a render overturned
(glass_probe alone has three recorded blind spots, and on 2026-08-28 four
separate instruments passed a car whose windscreen took paint). THE VERDICT IS
A RENDER. This tool prints its mapping table so a human can read it before
spending a render, exactly as clay_rebuild requires.

NAME CLASSIFICATION IS IMPORTED FROM glass_probe, NOT REWRITTEN. Those regexes
carry a year of paid-for traps — lamp lenses (`backlight_glass`), dashboard
icon sheets (`Airconditioningbuttonwindscreenventilationicons1Mtl`),
infotainment touchscreens, door mirrors (`glassSideMirror`), and misspellings
(`Widnwos`, `Windiow`). Re-deriving them would re-pay for all of it.

REFUSALS (it writes nothing and exits non-zero):
  * no glass-named material in the file — there is nothing to repair, and
    inventing one is what the seg chain is for, not this.
  * the named glazing is ALREADY transparent — the car was quarantined for
    some other reason and this tool is not the fix.

Run: python3 glazing_repair.py in.glb out.glb [--alpha 0.35] [--dry-run]
"""
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from glass_probe import GLASSY  # noqa: E402  — the vetted glazing-name regex

# Lamp lenses, interior trim and mirrors are GLASSY by name and are NOT glazing.
# Copied from glass_probe's local guards (they are defined inside its function,
# so they cannot be imported) — keep the two in step if either is edited.
LAMPY = re.compile(r"red|orange|amber|yellow|tail|head|lamp|light|blink|"
                   r"turn|indicat|fog|reverse|brake|stop|feux|clignot|"
                   r"swiatl|swiatla|swiatlo", re.I)
TRIMMY = re.compile(r"icon|button|instrument|gauge|cluster|dial|dash|"
                    r"aircondition|ventilation|speedo|touchscreen|infotain|"
                    r"radio|navi|mirror|rearview|rear.?view", re.I)

# `backlight` is the REAR WINDSCREEN as often as it is a tail lamp (recorded
# 2026-08-11 on mercedes-benz-a-class-2018-w12-v1, where it is genuinely the
# only glazing). LAMPY would eat it, so rescue the compound spellings that can
# only mean the screen.
BACKLIGHT_GLASS = re.compile(r"back.?light.?(glass|window|screen)|"
                             r"rear.?(screen|windscreen|windshield)|lunette", re.I)


def read_glb(path):
    d = open(path, "rb").read()
    if d[:4] != b"glTF":
        raise ValueError(f"{path} is not a GLB")
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


def is_glazing(name):
    """True for a material name that means WINDOW, not lamp/trim/mirror."""
    if not name or not GLASSY.search(name):
        return False
    if BACKLIGHT_GLASS.search(name):      # rescue before the lamp guard
        return True
    if LAMPY.search(name) or TRIMMY.search(name):
        return False
    return True


def is_transparent(m):
    pmr = m.get("pbrMetallicRoughness") or {}
    bcf = pmr.get("baseColorFactor") or [1, 1, 1, 1]
    return (m.get("alphaMode") in ("BLEND", "MASK")
            or bcf[3] < 1.0
            or "KHR_materials_transmission" in (m.get("extensions") or {}))


def repair(src, dst, alpha=0.35, dry_run=False):
    j, rest = read_glb(src)
    mats = j.get("materials", [])
    glaz = [(i, m) for i, m in enumerate(mats) if is_glazing(m.get("name"))]

    print(f"  materials: {len(mats)}   glazing-named: {len(glaz)}")
    if not glaz:
        print("  REFUSED: no glass-named material — nothing to repair here. "
              "Inventing glazing is the seg chain's job, not this tool's.")
        return False

    already = [m for _, m in glaz if is_transparent(m)]
    if len(already) == len(glaz):
        print("  REFUSED: the named glazing is ALREADY transparent — this car "
              "was quarantined for something else; this is not its fix.")
        return False

    # THE MAPPING TABLE IS THE GATE (clay_rebuild lesson). Print every decision
    # so a human can spot a mis-hit BEFORE a render is spent on it.
    print("  mapping:")
    for i, m in enumerate(mats):
        nm = m.get("name") or f"<unnamed {i}>"
        if is_glazing(nm):
            print(f"    {nm:<46} -> GLAZING"
                  f"{'  (already transparent, left alone)' if is_transparent(m) else ''}")
        elif nm and GLASSY.search(nm):
            why = "lamp" if LAMPY.search(nm) and not BACKLIGHT_GLASS.search(nm) else "trim/mirror"
            print(f"    {nm:<46} -- glassy name, held back as {why}")

    changed = 0
    for _, m in glaz:
        if is_transparent(m):
            continue
        pmr = m.setdefault("pbrMetallicRoughness", {})
        bcf = pmr.get("baseColorFactor") or [1.0, 1.0, 1.0, 1.0]
        pmr["baseColorFactor"] = [bcf[0], bcf[1], bcf[2], alpha]
        pmr["metallicFactor"] = 0.0
        pmr["roughnessFactor"] = 0.05
        m["alphaMode"] = "BLEND"
        m["doubleSided"] = True
        ext = m.setdefault("extensions", {})
        ext["KHR_materials_transmission"] = {"transmissionFactor": 0.85}
        ext.setdefault("KHR_materials_ior", {"ior": 1.45})
        changed += 1

    if changed:
        used = j.setdefault("extensionsUsed", [])
        for e in ("KHR_materials_transmission", "KHR_materials_ior"):
            if e not in used:
                used.append(e)

    print(f"  repaired {changed} glazing material(s) -> BLEND alpha {alpha}, "
          f"transmission 0.85, ior 1.45")
    if dry_run:
        print("  --dry-run: nothing written")
        return True
    write_glb(dst, j, rest)
    print(f"  wrote {dst} ({os.path.getsize(dst)} bytes; "
          f"BIN chunk copied verbatim, geometry untouched)")
    print("  NOT A VERDICT: render it. A BLEND flag does not prove the material "
          "is bound to a real window.")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    a = float(sys.argv[sys.argv.index("--alpha") + 1]) if "--alpha" in sys.argv else 0.35
    ok = repair(sys.argv[1], sys.argv[2], a, "--dry-run" in sys.argv)
    raise SystemExit(0 if ok else 1)
