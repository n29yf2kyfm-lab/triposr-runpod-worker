#!/usr/bin/env python3
"""r2_textures.py — REPAIR 2: de-duplicate and downsize the texture payload.

TWO PROBLEMS, ONE OF THEM MINE.

The baseline carried two unique 4096x4096 PNGs referenced by FOUR image entries
that shared two bufferViews -- 37.35 MB, 57.4% of a 65.1 MB file. Then R1's
Blender round-trip split those shared bufferViews into four separate copies, so
unique texture bytes doubled to 74.70 MB and the file grew to 102.3 MB. That
regression is mine and this repair undoes it.

Both are fixed here by rewriting the container directly rather than round-tripping
through Blender again, because the exporter is what duplicated them in the first
place. Identical image payloads are collapsed to one image entry by content hash,
every texture is repointed at the survivor, and each survivor is downsized to
MAXDIM and re-encoded.

Encoding is chosen per ROLE, not globally: a baseColor map is photographic and
takes JPEG, while a metallicRoughness / normal / occlusion map carries data in
its channels where JPEG's chroma subsampling and ringing corrupt the values, so
those stay PNG. Getting that backwards is a silent quality bug -- the file gets
small and the shading goes subtly wrong.

UNUSED ALPHA IS DROPPED, BUT ONLY WHEN PROVABLY UNUSED. The baseColor map here
is RGBA with 42.5% non-opaque pixels, which looks like real transparency and is
not: every material referencing it declares alphaMode OPAQUE, so no renderer
ever reads that channel. It costs 6.7 MB and forces PNG. The alpha is therefore
dropped ONLY when EVERY material referencing the image is OPAQUE -- if a single
one is BLEND or MASK the channel is kept and the image stays PNG, because
guessing wrong there deletes real transparency.

Run: python3 r2_textures.py in.glb out.glb report.json
Env: R2_MAXDIM (2048) · R2_JPEG_Q (90)
"""
import hashlib
import io
import json
import os
import struct
import sys

from PIL import Image

SRC, DST, REPORT = sys.argv[1], sys.argv[2], sys.argv[3]
MAXDIM = int(os.environ.get("R2_MAXDIM", "2048"))
JPEG_Q = int(os.environ.get("R2_JPEG_Q", "90"))


def read_glb(p):
    b = open(p, "rb").read()
    assert b[:4] == b"glTF", "not a GLB"
    off, js, binc = 12, None, b""
    while off < len(b):
        ln, ty = struct.unpack_from("<II", b, off)
        ch = b[off + 8: off + 8 + ln]
        if ty == 0x4E4F534A:
            js = json.loads(ch)
        elif ty == 0x004E4942:
            binc = ch
        off += 8 + ln + ((4 - ln % 4) % 4 if ln % 4 else 0)
    return js, binc, len(b)


js, binc, size_in = read_glb(SRC)
bvs = js["bufferViews"]


def bv_bytes(i):
    bv = bvs[i]
    o = bv.get("byteOffset", 0)
    return binc[o: o + bv["byteLength"]]


# ---- which images feed a DATA channel? those must not become JPEG ----
data_imgs = set()
colour_imgs = set()
for m in js.get("materials", []):
    pbr = m.get("pbrMetallicRoughness", {})
    for key, bucket in (("baseColorTexture", colour_imgs),
                        ("metallicRoughnessTexture", data_imgs)):
        t = pbr.get(key)
        if t is not None:
            bucket.add(js["textures"][t["index"]].get("source"))
    for key in ("normalTexture", "occlusionTexture"):
        t = m.get(key)
        if t is not None:
            data_imgs.add(js["textures"][t["index"]].get("source"))
    t = m.get("emissiveTexture")
    if t is not None:
        colour_imgs.add(js["textures"][t["index"]].get("source"))

# alphaMode of every material referencing each image
img_alpha_modes = {}
for m in js.get("materials", []):
    mode = m.get("alphaMode", "OPAQUE")
    pbr = m.get("pbrMetallicRoughness", {})
    refs = []
    for key in ("baseColorTexture", "metallicRoughnessTexture"):
        if key in pbr:
            refs.append(js["textures"][pbr[key]["index"]].get("source"))
    for key in ("normalTexture", "occlusionTexture", "emissiveTexture"):
        if key in m:
            refs.append(js["textures"][m[key]["index"]].get("source"))
    for r in refs:
        img_alpha_modes.setdefault(r, set()).add(mode)

# ---- collapse identical payloads by CONTENT HASH ----
digest_to_img = {}
img_remap = {}
originals = []
for i, im in enumerate(js.get("images", [])):
    raw = bv_bytes(im["bufferView"])
    h = hashlib.sha256(raw).hexdigest()
    originals.append({"image": i, "bytes": len(raw), "sha256": h[:16]})
    if h in digest_to_img:
        img_remap[i] = digest_to_img[h]
    else:
        digest_to_img[h] = i
        img_remap[i] = i
keep = sorted(set(img_remap.values()))
print(f"R2_DEDUPE images {len(js.get('images', []))} -> {len(keep)} unique by content hash")

# ---- re-encode the survivors ----
new_payload = {}
recoded = []
for i in keep:
    raw = bv_bytes(js["images"][i]["bufferView"])
    img = Image.open(io.BytesIO(raw))
    w0, h0 = img.size
    if max(img.size) > MAXDIM:
        s = MAXDIM / max(img.size)
        img = img.resize((max(1, int(round(w0 * s))), max(1, int(round(h0 * s)))),
                         Image.LANCZOS)
    is_data = i in data_imgs and i not in colour_imgs
    modes = img_alpha_modes.get(i, {"OPAQUE"})
    alpha_unused = img.mode in ("RGBA", "LA") and modes <= {"OPAQUE"}
    if alpha_unused:
        img = img.convert("RGB")
    buf = io.BytesIO()
    if is_data or img.mode in ("RGBA", "LA", "P"):
        if img.mode == "P":
            img = img.convert("RGBA")
        img.save(buf, format="PNG", optimize=True)
        mime = "image/png"
    else:
        img.convert("RGB").save(buf, format="JPEG", quality=JPEG_Q, optimize=True)
        mime = "image/jpeg"
    new_payload[i] = (buf.getvalue(), mime)
    recoded.append({"image": i, "from": [w0, h0], "to": list(img.size),
                    "role": "data" if is_data else "colour",
                    "alpha_dropped": bool(alpha_unused),
                    "alpha_modes_referencing": sorted(modes),
                    "mime": mime, "bytes_before": len(raw),
                    "bytes_after": len(buf.getvalue())})
    print(f"R2_RECODE image {i}: {w0}x{h0} -> {img.size[0]}x{img.size[1]} "
          f"{'DATA->PNG' if is_data else 'COLOUR->'+mime.split('/')[1].upper()}"
          f"{' alpha-dropped(all OPAQUE)' if alpha_unused else ''}  "
          f"{len(raw):,} -> {len(buf.getvalue()):,} B")

# ---- rebuild the BIN with new offsets ----
image_bv = {js["images"][i]["bufferView"]: i for i in range(len(js.get("images", [])))}
out = bytearray()
newbvs = []
for idx, bv in enumerate(bvs):
    if idx in image_bv and image_bv[idx] in new_payload:
        data = new_payload[image_bv[idx]][0]
    elif idx in image_bv:
        continue                      # a duplicate image's view; drop it
    else:
        data = bv_bytes(idx)
    while len(out) % 4:
        out.append(0)
    nb = {k: v for k, v in bv.items() if k != "byteOffset"}
    nb["byteOffset"] = len(out)
    nb["byteLength"] = len(data)
    newbvs.append((idx, nb))
    out += data

old_to_new = {old: n for n, (old, _) in enumerate(newbvs)}
js["bufferViews"] = [nb for _, nb in newbvs]
for a in js.get("accessors", []):
    if "bufferView" in a:
        a["bufferView"] = old_to_new[a["bufferView"]]

new_images = []
img_old_to_new = {}
for i in keep:
    img_old_to_new[i] = len(new_images)
    new_images.append({"bufferView": old_to_new[js["images"][i]["bufferView"]],
                       "mimeType": new_payload[i][1]})
js["images"] = new_images
for t in js.get("textures", []):
    if "source" in t:
        t["source"] = img_old_to_new[img_remap[t["source"]]]
js["buffers"] = [{"byteLength": len(out)}]

jsb = json.dumps(js, separators=(",", ":")).encode()
while len(jsb) % 4:
    jsb += b" "
while len(out) % 4:
    out.append(0)
glb = (b"glTF" + struct.pack("<II", 2, 12 + 8 + len(jsb) + 8 + len(out))
       + struct.pack("<II", len(jsb), 0x4E4F534A) + jsb
       + struct.pack("<II", len(out), 0x004E4942) + bytes(out))
open(DST, "wb").write(glb)

tex_bytes = sum(len(new_payload[i][0]) for i in keep)
print(f"R2_SIZE {size_in:,} -> {len(glb):,} B  ({100*len(glb)/size_in:.1f}%)  "
      f"textures {tex_bytes:,} = {100*tex_bytes/len(glb):.1f}% of file")
json.dump({"repair": "R2 texture dedupe + downsize",
           "in": SRC, "out": DST,
           "bytes_before": size_in, "bytes_after": len(glb),
           "images_before": len(originals), "images_after": len(keep),
           "originals": originals, "recoded": recoded,
           "texture_bytes_after": tex_bytes,
           "texture_share_pct": round(100 * tex_bytes / len(glb), 2),
           "maxdim": MAXDIM, "jpeg_quality": JPEG_Q},
          open(REPORT, "w"), indent=2)
print("R2_DONE")
