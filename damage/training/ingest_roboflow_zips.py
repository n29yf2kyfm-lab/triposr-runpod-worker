"""Stream Roboflow export zips into one merged, deduped, downscaled COCO set.

Staging all 205 audited exports and merging afterwards needs ~42GB against
15GB free, so nothing is staged: each zip is extracted, folded in, and deleted
before the next is touched. Peak disk is one zip plus its extraction.

FOUR THINGS HAPPEN PER IMAGE, AND THE ORDER MATTERS.

1. HASH THE ORIGINAL BYTES, BEFORE ANY RESIZE. The manifest's 267,696 images
   are heavily inflated by fork families — the same 8,857-image corpus appears
   three times in the first page alone (asandes-workspace, skillfactory,
   rfvnx-dgm7e), and several projects are already in the original 41. Hashing
   after downscaling would make identical source images hash differently
   whenever two projects exported at different sizes, and the duplicates would
   survive. Hash first, resize second.

2. MAP THE CLASS NAME. Every project invents its own vocabulary: 6 classes
   here, 17 there, 31 somewhere else, in several languages. A fixed lookup
   cannot cover that, so class_for() matches on keywords and reports whatever
   it could not place instead of silently dropping it — unmapped names are the
   thing most likely to hide a whole damage type we care about.

3. SCALE THE BOXES WITH THE IMAGE. A resize that forgets the annotations is
   the classic way to build a dataset that looks fine and trains to nothing.
   COCO bbox is [x, y, w, h] in absolute pixels, so every component scales by
   the same factor.

4. DROP DEGENERATE BOXES. Downscaling a 3px-wide box to 640px can round it to
   zero width; a zero-area box is not a hard example, it is corrupt data.

WHY 640px: RF-DETR trains at 560-640. Native resolution costs ~79KB/image and
buys nothing the model sees, which is the difference between ~21GB and ~8GB.

    python ingest_roboflow_zips.py --zips DIR --out DIR --delete-zips
"""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
import zipfile

import class_map as CM

# Keyword -> final class. Ordered: the FIRST match wins, so the more specific
# patterns must come first. "glass_shatter" has to be tested before "glass",
# and "paint chip" before "paint", or the general term swallows the specific.
CLASS_RULES = [
    # glass first — "broken glass" must not fall through to "broken part"
    (("glass shatter", "shattered glass", "glass break", "glass_break",
      "broken glass", "windshield crack", "windscreen crack", "glass crack",
      "cracked glass", "glass chip", "glass-chip", "glass spider",
      "broken windshield", "broken window", "smashed glass"), "crack_glass"),
    (("crack", "cracked", "fissure", "kirik", "retak"), "crack_glass"),
    # lamps and wheels before generic "broken"/"damage"
    (("lamp", "headlight", "head light", "tail light", "taillight", "fog light",
      "indicator", "light broken", "broken light", "lampu"), "lamp_wheel"),
    (("tire", "tyre", "wheel", "rim", "alloy", "flat tire", "tire burst",
      "ban ", "lastik"), "lamp_wheel"),
    # corrosion / paint
    (("rust", "corrosion", "corroded", "oxidation", "karat"), "rust_paint"),
    (("paint chip", "paint-chip", "chipped paint", "flaking", "peel",
      "paint damage", "paint fade", "faded paint", "primer", "clear coat",
      "discolor", "bad repair", "repaint", "cat "), "rust_paint"),
    # structural before dent — a shoved bumper is not a ding
    (("missing", "detach", "torn", "tear", "structural", "severe damage",
      "smash", "crush", "collaps", "deform", "bent", "misalign", "panel gap",
      "gap", "hilang", "kayip"), "structural"),
    (("broken", "break", "shatter", "damaged part", "broken part",
      "rusak", "hasar"), "structural"),
    # scratch family before dent, since "scratch-dent" strings are common
    (("scratch", "scuff", "scrape", "abrasion", "swirl", "graze", "key mark",
      "gores", "cizik", "rayure"), "scratch_scuff"),
    (("dent", "ding", "dint", "hail", "penyok", "gocuk", "bosselure"), "dent"),
]

# Names that are definitely NOT damage — parts, whole vehicles, junk labels.
# Counted and reported rather than silently ignored, because a project whose
# classes are all in here is off-domain and should not have passed the audit.
NON_DAMAGE = (
    "car", "vehicle", "bumper", "door", "hood", "bonnet", "fender", "quarter",
    "roof", "trunk", "boot", "grille", "mirror", "window", "windshield",
    "windscreen", "panel", "wing", "sill", "rocker", "pillar", "plate",
    "license", "background", "object", "not a car", "person", "_placeholder_",
)


# Materials that are corroding but are not a car. rust-detection-38s6e is a
# genuinely useful 10k corrosion set, but it mixes automotive rust with
# "copper corrosion" and pipework — and because rust is our thinnest real
# class, letting industrial corrosion in would look like fixing the gap while
# actually teaching the detector that green patina on copper is car rust.
OFF_MATERIAL = ("copper", "pipe", "pipeline", "weld", "concrete", "brick",
                "steel plate", "girder", "bridge", "hull", "roof")


def class_for(name):
    """Final class for an arbitrary Roboflow class name, or None."""
    s = str(name or "").strip().lower().replace("_", " ").replace("-", " ")
    s = " ".join(s.split())
    if not s:
        return None
    if any(m in s for m in OFF_MATERIAL):
        return None
    for keys, final in CLASS_RULES:
        for k in keys:
            if k in s:
                return final
    return None


def is_non_damage(name):
    s = str(name or "").strip().lower().replace("_", " ").replace("-", " ")
    return any(k == s or s.startswith(k + " ") or s.endswith(" " + k)
               for k in NON_DAMAGE)


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def load_state(out_dir):
    """(seen_hashes, images, annotations, next_ids) from a prior run."""
    seen, images, anns = set(), [], []
    p = os.path.join(out_dir, "_annotations.coco.json")
    if os.path.exists(p):
        with open(p) as f:
            d = json.load(f)
        images = d.get("images", [])
        anns = d.get("annotations", [])
        seen = {i.get("sha") for i in images if i.get("sha")}
    return seen, images, anns


def ingest_zip(zpath, out_img_dir, seen, images, anns, max_side, counters):
    from PIL import Image
    tmp = tempfile.mkdtemp(prefix="rfz_")
    added = 0
    try:
        try:
            with zipfile.ZipFile(zpath) as z:
                z.extractall(tmp)
        except Exception:
            counters["bad_zip"] += 1
            return 0

        for root, _d, files in os.walk(tmp):
            if "_annotations.coco.json" not in files:
                continue
            try:
                with open(os.path.join(root, "_annotations.coco.json")) as f:
                    d = json.load(f)
            except Exception:
                continue
            cats = {c["id"]: c.get("name", "") for c in d.get("categories", [])}
            by_img = {}
            for a in d.get("annotations", []):
                by_img.setdefault(a["image_id"], []).append(a)

            for im in d.get("images", []):
                src = os.path.join(root, im["file_name"])
                if not os.path.exists(src):
                    counters["missing_file"] += 1
                    continue
                # (1) hash the ORIGINAL bytes, before any resize
                try:
                    h = sha256(src)
                except OSError:
                    continue
                if h in seen:
                    counters["duplicate"] += 1
                    continue

                rows = []
                for a in by_img.get(im["id"], []):
                    raw = cats.get(a["category_id"], "")
                    final = class_for(raw)
                    if not final:
                        if is_non_damage(raw):
                            counters["non_damage_class"] += 1
                        else:
                            counters["unmapped"] += 1
                            counters.setdefault("_unmapped_names", {})
                            counters["_unmapped_names"][raw] = \
                                counters["_unmapped_names"].get(raw, 0) + 1
                        continue
                    rows.append((final, a.get("bbox")))
                if not rows:
                    counters["no_usable_boxes"] += 1
                    continue

                try:
                    with Image.open(src) as pim:
                        pim = pim.convert("RGB")
                        W, H = pim.size
                        scale = min(1.0, max_side / float(max(W, H)))
                        if scale < 1.0:
                            pim = pim.resize((max(1, int(W * scale)),
                                              max(1, int(H * scale))),
                                             Image.LANCZOS)
                        nW, nH = pim.size
                        dst = os.path.join(out_img_dir, f"{h[:20]}.jpg")
                        pim.save(dst, quality=88)
                except Exception:
                    counters["unreadable"] += 1
                    continue

                seen.add(h)
                img_id = len(images) + 1
                # `src` records which export an image came from. Omitting it
                # cost real work: rust-detection-38s6e was ingested before the
                # OFF_MATERIAL rule existed, and without a source field there
                # was no way to find its images again and strip the copper
                # corrosion — the whole project had to be re-fetched and
                # hash-matched to undo one mistake.
                images.append({"id": img_id, "file_name": os.path.basename(dst),
                               "width": nW, "height": nH, "sha": h,
                               "src": counters.get("_src", "")})
                for final, bbox in rows:
                    if not bbox or len(bbox) != 4:
                        continue
                    # (3) scale boxes with the image
                    x, y, w, hh = (float(v) * scale for v in bbox)
                    # (4) drop what rounding destroyed
                    if w < 2 or hh < 2:
                        counters["degenerate_box"] += 1
                        continue
                    x = max(0.0, min(x, nW - 1)); y = max(0.0, min(y, nH - 1))
                    w = min(w, nW - x); hh = min(hh, nH - y)
                    anns.append({"id": len(anns) + 1, "image_id": img_id,
                                 "category_id": CM.class_index()[final],
                                 "bbox": [round(x, 2), round(y, 2),
                                          round(w, 2), round(hh, 2)],
                                 "area": round(w * hh, 2), "iscrowd": 0,
                                 "cls": final})
                added += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return added


def save(out_dir, images, anns):
    idx = CM.class_index()
    cats = [{"id": 0, "name": "_placeholder_", "supercategory": "none"}]
    cats += [{"id": i, "name": c, "supercategory": CM.canonical(c)}
             for c, i in sorted(idx.items(), key=lambda kv: kv[1])]
    tmp = os.path.join(out_dir, "_annotations.coco.json.tmp")
    with open(tmp, "w") as f:
        json.dump({"images": images, "annotations": anns, "categories": cats}, f)
    os.replace(tmp, os.path.join(out_dir, "_annotations.coco.json"))


def free_gb(p="/"):
    st = os.statvfs(p)
    return st.f_bavail * st.f_frsize / (1 << 30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zips", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-side", type=int, default=640)
    ap.add_argument("--delete-zips", action="store_true")
    ap.add_argument("--min-free-gb", type=float, default=2.0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    img_dir = os.path.join(args.out, "images")
    os.makedirs(img_dir, exist_ok=True)
    seen, images, anns = load_state(args.out)
    print(f"resuming with {len(images)} images, {len(anns)} boxes, "
          f"{len(seen)} hashes")

    zips = sorted(z for z in os.listdir(args.zips) if z.endswith(".zip"))
    if args.limit:
        zips = zips[:args.limit]
    counters = {k: 0 for k in ("duplicate", "unmapped", "non_damage_class",
                               "no_usable_boxes", "degenerate_box",
                               "unreadable", "missing_file", "bad_zip")}
    for i, z in enumerate(zips, 1):
        if free_gb() < args.min_free_gb:
            print(f"STOPPING: {free_gb():.1f} GB free")
            break
        zp = os.path.join(args.zips, z)
        counters["_src"] = z[:-4].replace("__", "/")
        n = ingest_zip(zp, img_dir, seen, images, anns, args.max_side, counters)
        if args.delete_zips:
            try:
                os.remove(zp)
            except OSError:
                pass
        save(args.out, images, anns)
        print(f"  [{i}/{len(zips)}] +{n:>6} -> {len(images):>7} imgs, "
              f"{len(anns):>7} boxes, {free_gb():.1f} GB free  {z[:44]}",
              flush=True)

    save(args.out, images, anns)
    print(f"\nTOTAL {len(images)} images, {len(anns)} boxes")
    from collections import Counter
    print("per class:")
    for c, n in Counter(a["cls"] for a in anns).most_common():
        print(f"    {c:16s} {n:>8}")
    print("skipped:")
    for k, v in counters.items():
        if not k.startswith("_") and v:
            print(f"    {k:20s} {v}")
    un = counters.get("_unmapped_names", {})
    if un:
        print(f"  top unmapped class names ({len(un)} distinct):")
        for n, c in sorted(un.items(), key=lambda kv: -kv[1])[:25]:
            print(f"    {n[:44]:46s} {c}")


if __name__ == "__main__":
    main()
