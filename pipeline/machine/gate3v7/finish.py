#!/usr/bin/env python3
"""finish.py -- GATE 3 v7 step 3: restore what the glTF round-trip destroyed.

TRIMESH DROPS EVERY KHR MATERIAL EXTENSION ON ANY ROUND-TRIP.  Proven directly:
loading the untouched base and re-exporting it, with no edits at all, returns a
file whose `glass` material has lost `KHR_materials_transmission` (0.92) and
`KHR_materials_ior` (1.45), and whose `carpaint`, `Lamp_Lens` and
`Lamp_Lens_Rear` have lost `KHR_materials_clearcoat`.  That is not this gate's
edit -- it is trimesh's material writer -- but it IS this gate's regression if
it ships, because Gate 7+8 certified those exact values on this car.

glass_probe still reports clear/proven without them, because BLEND at alpha
0.161 is enough for its verdict.  So the probe would NOT have caught this.  It
was found by reading the written file's material table, which is why that check
exists.

TWO MORE THINGS THE ROUND-TRIP DID:
  * DUPLICATE MATERIAL NAMES.  The new parts got their own `carpaint` and
    `Trim_Black` instances alongside the originals.  A respray targets materials
    BY NAME (`colour_variants` / `respray_gltf`), so two materials called
    `carpaint` means a respray can recolour the body and leave the new bumper
    the old colour -- eight variants that differ from each other but not from
    the car.  Duplicates are merged onto the base's definition.
  * MISSING NORMAL ACCESSORS on every constructed primitive.  Fixed at the
    export call (`include_normals=True`); asserted here on the WRITTEN file,
    because that is the only place the claim can be checked.

Run: python3 finish.py <rebuilt.glb> <base.glb> <out.glb> <report.json>
"""
import json
import struct
import sys

OUT_ALIGN = 4


def read_glb(path):
    raw = open(path, "rb").read()
    if raw[:4] != b"glTF":
        raise SystemExit(f"{path}: not a GLB")
    off, js, bin_ = 12, None, b""
    while off < len(raw):
        ln, ty = struct.unpack_from("<II", raw, off)
        off += 8
        chunk = raw[off:off + ln]
        if ty == 0x4E4F534A:
            js = json.loads(chunk.decode("utf-8"))
        elif ty == 0x004E4942:
            bin_ = chunk
        off += ln
    return js, bin_


def write_glb(path, js, bin_):
    j = json.dumps(js, separators=(",", ":")).encode("utf-8")
    j += b" " * ((-len(j)) % OUT_ALIGN)
    b = bin_ + b"\0" * ((-len(bin_)) % OUT_ALIGN)
    total = 12 + 8 + len(j) + (8 + len(b) if b else 0)
    with open(path, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, total))
        f.write(struct.pack("<II", len(j), 0x4E4F534A) + j)
        if b:
            f.write(struct.pack("<II", len(b), 0x004E4942) + b)


REB, BASE, OUT, REP = sys.argv[1:5]
js, bin_ = read_glb(REB)
bjs, _ = read_glb(BASE)

base_mat = {}
for m in bjs.get("materials", []):
    if m.get("name"):
        base_mat[m["name"]] = m

R = {"restored_from_base": [], "merged_duplicates": [], "kept_new": [],
     "extensions_before": {}, "extensions_after": {}}

for m in js.get("materials", []):
    R["extensions_before"][m.get("name", "?")] = sorted(
        (m.get("extensions") or {}).keys())

# ---- rebuild the material list: one entry per NAME, base definition wins ----
order, newmats, remap = [], [], {}
for i, m in enumerate(js.get("materials", [])):
    nm = m.get("name") or f"_unnamed_{i}"
    if nm in order:
        remap[i] = order.index(nm)
        R["merged_duplicates"].append(nm)
        continue
    remap[i] = len(order)
    order.append(nm)
    if nm in base_mat:
        newmats.append(json.loads(json.dumps(base_mat[nm])))
        R["restored_from_base"].append(nm)
    else:
        newmats.append(m)
        R["kept_new"].append(nm)

js["materials"] = newmats
for mesh in js.get("meshes", []):
    for p in mesh.get("primitives", []):
        if "material" in p:
            p["material"] = remap[p["material"]]

# ---- extensionsUsed must list every extension actually referenced ----------
used = set(js.get("extensionsUsed") or [])
for m in js["materials"]:
    used |= set((m.get("extensions") or {}).keys())
for k in ("extensions",):
    used |= set((js.get(k) or {}).keys())
js["extensionsUsed"] = sorted(used)
if not js["extensionsUsed"]:
    js.pop("extensionsUsed")

for m in js["materials"]:
    R["extensions_after"][m.get("name", "?")] = sorted(
        (m.get("extensions") or {}).keys())

write_glb(OUT, js, bin_)

# ------------------------------------------------- assert on the WRITTEN file
js2, _ = read_glb(OUT)
missing_normal = [mesh.get("name", "?") for mesh in js2.get("meshes", [])
                 for p in mesh.get("primitives", [])
                 if "NORMAL" not in p.get("attributes", {})]
names = [m.get("name") for m in js2["materials"]]
dupes = sorted({n for n in names if names.count(n) > 1})
usecnt = {}
for mesh in js2.get("meshes", []):
    for p in mesh.get("primitives", []):
        usecnt[p.get("material")] = usecnt.get(p.get("material"), 0) + 1
dead = [names[i] for i in range(len(names)) if i not in usecnt]

R["written"] = {
    "materials": len(names),
    "duplicate_names": dupes,
    "dead_materials": dead,
    "primitives_missing_NORMAL": missing_normal,
    "extensionsUsed": js2.get("extensionsUsed", []),
}
json.dump(R, open(REP, "w"), indent=1)

print(f"materials {len(js.get('materials', []))} -> {len(names)}  "
      f"(merged duplicates: {sorted(set(R['merged_duplicates'])) or 'none'})")
print(f"restored from base: {R['restored_from_base']}")
print(f"kept new:           {R['kept_new']}")
print("extensions after:")
for n, e in R["extensions_after"].items():
    if e:
        print(f"    {n:18s} {e}")
print(f"duplicate names on the written file: {dupes or 'NONE'}")
print(f"dead materials:                      {dead or 'NONE'}")
print(f"primitives missing NORMAL:           {missing_normal or 'NONE'}")
ok = not dupes and not dead and not missing_normal
print("FINISH_OK" if ok else "FINISH_INCOMPLETE", OUT)
sys.exit(0 if ok else 1)
