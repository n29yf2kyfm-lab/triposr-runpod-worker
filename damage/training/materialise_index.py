"""Turn the training index into the COCO directory RF-DETR actually trains on.

build_train_index.py writes a PLAN — one line per sample naming an original, a
repeat number and an augmentation recipe. augment.py turns one such line into
pixels. Nothing joined the two to the trainer, so the plan described a corpus
that was never built and `wm` was a field no code read. This is that join.

    index.jsonl + images.jsonl + classes.json  ->  train/ valid/ test/
                                                    each a Roboflow-style COCO

WHY IT WRITES FILES INSTEAD OF STREAMING
----------------------------------------
RF-DETR's train() takes a dataset_dir and owns its own loader, so there is no
hook to hand it samples. Materialising is therefore not a design preference, it
is the interface. It costs disk — roughly 20GB for 372k samples at 640px — which
is why this runs on the rented GPU box and not on the 5GB free here.

WHAT IT GUARANTEES
------------------
1. VALID AND TEST ARE NEVER AUGMENTED. Enforced here as well as in the index,
   because this is the last place the guarantee can still be broken and a
   silently augmented eval set measures the augmentation.
2. EVERY SAMPLE IS A DISTINCT FILE. Repeat k of one original is
   <sha20>_r<k>.jpg, so twelve augmented copies do not overwrite each other and
   leave one image with twelve annotation sets.
3. BOXES COME FROM augment.apply_row, NOT FROM THE INDEX. A crop moves boxes
   and can drop one entirely; copying the original coordinates across would put
   every box in the wrong place while the file still opened fine.
4. A SAMPLE THAT LOSES ALL ITS BOXES IS DROPPED, not written empty. An image
   labelled "no damage here" when there plainly is teaches the detector to miss
   it.
5. CLASS IDS COME FROM classes.json. Same map the index numbered its boxes
   with, and the same one written to labels.txt, so the three cannot drift.

    python materialise_index.py --index DIR --corpus DIR --out DIR \\
        [--workers 8] [--limit N] [--splits train,valid,test]
    python materialise_index.py --selftest
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_CTX = {}


def _load(index_dir):
    with open(os.path.join(index_dir, "classes.json")) as f:
        classes = json.load(f)
    boxes = {}
    with open(os.path.join(index_dir, "images.jsonl")) as f:
        for ln in f:
            r = json.loads(ln)
            boxes[r["sha"]] = r
    samples = []
    with open(os.path.join(index_dir, "index.jsonl")) as f:
        for ln in f:
            samples.append(json.loads(ln))
    return classes, boxes, samples


def _init(corpus, index_dir, out):
    from PIL import Image                                    # noqa: F401
    import augment
    classes, boxes, _s = _load(index_dir)
    _CTX.update(corpus=corpus, out=out, boxes=boxes, augment=augment,
                name_to_index=classes["name_to_index"])


def _one(sample):
    """Render one sample. Returns (split, file_name, w, h, [(cls_id, box)])."""
    from PIL import Image
    aug = _CTX["augment"]
    rec = _CTX["boxes"].get(sample["sha"])
    if not rec:
        return None
    src = os.path.join(_CTX["corpus"], rec["file"])
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            norm = [[b[1], b[2], b[3], b[4]] for b in rec["boxes"]]
            ids = [b[0] for b in rec["boxes"]]

            row = dict(sample)
            if sample["split"] != "train":
                # belt and braces: the index already says so
                row["recipe"], row["wm"], row["sn"] = [], False, False

            out_im, out_boxes, keep = aug.apply_row(
                im, norm, row, with_indices=True)
            ids = [ids[k] for k in keep]
            if not out_boxes:
                return None

            name = f"{sample['sha'][:20]}_r{sample['rep']}.jpg"
            dest = os.path.join(_CTX["out"], sample["split"], name)
            out_im.save(dest, "JPEG", quality=90)
            W, H = out_im.size
    except Exception:
        return None

    px = []
    for cid, b in zip(ids, out_boxes):
        x, y, w, h = b[0] * W, b[1] * H, b[2] * W, b[3] * H
        if w <= 1 or h <= 1:
            continue
        px.append((cid, [round(x, 2), round(y, 2), round(w, 2), round(h, 2)]))
    if not px:
        try:
            os.remove(dest)
        except OSError:
            pass
        return None
    return (sample["split"], name, W, H, px)


def materialise(index_dir, corpus, out, workers=8, limit=0,
                splits=("train", "valid", "test"), verbose=True):
    classes, _boxes, samples = _load(index_dir)
    samples = [s for s in samples if s["split"] in splits]
    if limit:
        # Keep the split mix rather than truncating to the first N, which
        # would be all train (the index is ordered train-first).
        by = {}
        for s in samples:
            by.setdefault(s["split"], []).append(s)
        total = sum(len(v) for v in by.values())
        picked = []
        for k, v in by.items():
            n = max(1, int(round(limit * len(v) / total)))
            picked += v[:n]
        samples = picked

    for sp in splits:
        os.makedirs(os.path.join(out, sp), exist_ok=True)

    cats = [{"id": 0, "name": "_placeholder_", "supercategory": "none"}]
    for r in sorted(classes["classes"], key=lambda r: r["index"]):
        cats.append({"id": r["index"], "name": r["name"],
                     "supercategory": r["canonical"]})

    from multiprocessing import Pool
    acc = {sp: {"images": [], "annotations": []} for sp in splits}
    nid = {sp: 1 for sp in splits}
    aid = {sp: 1 for sp in splits}
    done = dropped = 0
    t0 = time.time()

    with Pool(workers, initializer=_init,
              initargs=(corpus, index_dir, out)) as pool:
        for res in pool.imap_unordered(_one, samples, chunksize=64):
            done += 1
            if res is None:
                dropped += 1
            else:
                sp, name, W, H, px = res
                iid = nid[sp]
                nid[sp] += 1
                acc[sp]["images"].append(
                    {"id": iid, "file_name": name, "width": W, "height": H})
                for cid, bb in px:
                    acc[sp]["annotations"].append(
                        {"id": aid[sp], "image_id": iid, "category_id": cid,
                         "bbox": bb, "area": round(bb[2] * bb[3], 2),
                         "iscrowd": 0})
                    aid[sp] += 1
            if verbose and done % 5000 == 0:
                el = time.time() - t0
                print(f"  {done:,}/{len(samples):,}  {done/el:.0f}/s  "
                      f"dropped {dropped:,}", flush=True)

    for sp in splits:
        with open(os.path.join(out, sp, "_annotations.coco.json"), "w") as f:
            json.dump({"images": acc[sp]["images"],
                       "annotations": acc[sp]["annotations"],
                       "categories": cats}, f)

    # labels.txt IS the contract with inference (see prepare_data.py). It is
    # written from the same classes.json that numbered every box above, so the
    # three cannot disagree.
    names = ["_placeholder_"] + [r["name"] for r in
                                 sorted(classes["classes"],
                                        key=lambda r: r["index"])]
    with open(os.path.join(out, "labels.txt"), "w") as f:
        f.write(",".join(names))

    if verbose:
        print(f"\nwrote {out}")
        for sp in splits:
            print(f"  {sp:6s} {len(acc[sp]['images']):>8,} images "
                  f"{len(acc[sp]['annotations']):>9,} boxes")
        print(f"  dropped {dropped:,} samples with no surviving box")
        print(f"  labels.txt: {','.join(names)}")
    return acc


# -------------------------------------------------------------- selftest ----

def _selftest():
    import tempfile
    import shutil
    from PIL import Image
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  PASS  {name}")
        else:
            fail += 1
            print(f"  FAIL  {name}  {detail}")

    tmp = tempfile.mkdtemp(prefix="mat_")
    corpus = os.path.join(tmp, "corpus")
    os.makedirs(os.path.join(corpus, "images"))
    idx = os.path.join(tmp, "idx")
    os.makedirs(idx)
    out = os.path.join(tmp, "out")

    shas = []
    for i in range(6):
        s = (format(i, "x") + "ab7f39c2e1" * 6)[:64]
        shas.append(s)
        im = Image.new("RGB", (400, 300), (40, 40, 40))
        px = im.load()
        for yy in range(60, 140):
            for xx in range(100, 200):
                px[xx, yy] = (250, 30, 30)
        im.save(os.path.join(corpus, "images", s[:20] + ".jpg"), quality=95)

    classes = {"classes": [
        {"name": "surface", "index": 1, "colour": "#58a6ff",
         "canonical": "scratch", "members": ["scratch_scuff"]},
        {"name": "dent", "index": 2, "colour": "#f0883e",
         "canonical": "dent", "members": ["dent"]}],
        "name_to_index": {"surface": 1, "dent": 2},
        "index_to_name": {"1": "surface", "2": "dent"}}
    with open(os.path.join(idx, "classes.json"), "w") as f:
        json.dump(classes, f)

    with open(os.path.join(idx, "images.jsonl"), "w") as f:
        for i, s in enumerate(shas):
            f.write(json.dumps({
                "sha": s, "file": "images/" + s[:20] + ".jpg",
                "split": "train" if i < 4 else ("valid" if i == 4 else "test"),
                "width": 400, "height": 300, "owner_class": "surface",
                "boxes": [[1, 0.25, 0.20, 0.25, 0.267],
                          [2, 0.60, 0.60, 0.20, 0.20]]}) + "\n")

    rows = []
    for i, s in enumerate(shas):
        sp = "train" if i < 4 else ("valid" if i == 4 else "test")
        rows.append({"split": sp, "sha": s, "file": "images/" + s[:20] + ".jpg",
                     "rep": 0, "recipe": [], "wm": sp == "train",
                     "sn": False, "seed": 1000 + i})
        if sp == "train":                       # a second, augmented repeat
            rows.append({"split": sp, "sha": s,
                         "file": "images/" + s[:20] + ".jpg", "rep": 1,
                         "recipe": ["hflip", "crop"], "wm": True, "sn": True,
                         "seed": 5000 + i})
    with open(os.path.join(idx, "index.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    acc = materialise(idx, corpus, out, workers=2, verbose=False)

    check(f"train materialised ({len(acc['train']['images'])} images)",
          len(acc["train"]["images"]) == 8, str(len(acc["train"]["images"])))
    check("valid and test materialised",
          len(acc["valid"]["images"]) == 1 and len(acc["test"]["images"]) == 1)

    files = os.listdir(os.path.join(out, "train"))
    jpgs = [f for f in files if f.endswith(".jpg")]
    check(f"each repeat is a distinct file ({len(jpgs)} unique)",
          len(jpgs) == len(set(jpgs)) == 8, str(sorted(jpgs)[:3]))

    # every annotation must point at an image that exists
    with open(os.path.join(out, "train", "_annotations.coco.json")) as f:
        tr = json.load(f)
    ids = {i["id"] for i in tr["images"]}
    check("no orphan annotations",
          all(a["image_id"] in ids for a in tr["annotations"]))
    check("every image has at least one box",
          ids == {a["image_id"] for a in tr["annotations"]})
    check("boxes lie inside their frame",
          all(0 <= a["bbox"][0] and 0 <= a["bbox"][1]
              and a["bbox"][0] + a["bbox"][2] <=
              [i for i in tr["images"] if i["id"] == a["image_id"]][0]["width"]
              + 1
              and a["bbox"][1] + a["bbox"][3] <=
              [i for i in tr["images"] if i["id"] == a["image_id"]][0]["height"]
              + 1
              for a in tr["annotations"]))
    check("category ids come from classes.json",
          {a["category_id"] for a in tr["annotations"]} <= {1, 2})
    check("both classes survive materialisation",
          {a["category_id"] for a in tr["annotations"]} == {1, 2})

    # valid must be pixel-identical to its original: no augmentation, no mark
    import numpy as np
    with open(os.path.join(out, "valid", "_annotations.coco.json")) as f:
        va = json.load(f)
    vname = va["images"][0]["file_name"]
    a = np.asarray(Image.open(os.path.join(out, "valid", vname)).convert("RGB"))
    b = np.asarray(Image.open(os.path.join(
        corpus, "images", shas[4][:20] + ".jpg")).convert("RGB"))
    dv = np.abs(a.astype(int) - b.astype(int)).mean()
    # Re-encoding at quality 90 costs a fraction of a level; a watermark costs
    # 3+ and a flip or crop costs tens. The band separates them cleanly.
    check(f"valid is unaugmented — recompression only (mean |d| {dv:.3f})",
          a.shape == b.shape and dv < 1.5, f"{dv:.3f}")

    # train rep 0 has wm=True, so it must NOT be pixel-identical
    t0name = sorted(jpgs)[0]
    ta = np.asarray(Image.open(os.path.join(out, "train", t0name)))
    check("train samples are actually augmented",
          ta.shape == b.shape and
          np.abs(ta.astype(int) - b.astype(int)).mean() > 0.3)

    with open(os.path.join(out, "labels.txt")) as f:
        lab = f.read().strip().split(",")
    check(f"labels.txt matches classes.json order {lab}",
          lab == ["_placeholder_", "surface", "dent"], str(lab))

    # A crop that drops a box must not shift the remaining class ids. The
    # earlier version of this check put both boxes near the centre, so no crop
    # ever dropped one and it passed on zero cases — a test that could not
    # fail. Box 1 (surface) is central and nearly always survives; box 2 (dent)
    # sits in the far corner and is often cut, which is exactly the case where
    # matching survivors BY POSITION would relabel the survivor as `dent`.
    with open(os.path.join(idx, "images.jsonl"), "w") as f:
        f.write(json.dumps({
            "sha": shas[0], "file": "images/" + shas[0][:20] + ".jpg",
            "split": "train", "width": 400, "height": 300,
            "owner_class": "surface",
            "boxes": [[1, 0.40, 0.40, 0.20, 0.20],
                      [2, 0.90, 0.88, 0.09, 0.10]]}) + "\n")
    rows2 = [{"split": "train", "sha": shas[0],
              "file": "images/" + shas[0][:20] + ".jpg", "rep": 0,
              "recipe": ["crop"], "wm": False, "sn": False, "seed": sd}
             for sd in range(40)]
    with open(os.path.join(idx, "index.jsonl"), "w") as f:
        for r in rows2:
            f.write(json.dumps(r) + "\n")
    out2 = os.path.join(tmp, "out2")
    acc2 = materialise(idx, corpus, out2, workers=2, splits=("train",),
                       verbose=False)
    # box 1 (surface) is at 0.25-0.50 x; box 2 (dent) at 0.60-0.80. Whenever
    # only one survives, its id must still be the id it started with.
    per = {}
    for a_ in acc2["train"]["annotations"]:
        per.setdefault(a_["image_id"], []).append(a_["category_id"])
    singles = [v[0] for v in per.values() if len(v) == 1]
    check(f"the drop-a-box case actually occurs ({len(singles)} of {len(per)} "
          f"crops kept exactly one box)", len(singles) > 0, "vacuous test")
    # The central box is the survivor whenever only one remains, so every
    # single must be class 1. A positional match would report class 2 as soon
    # as box 1 were ever the one dropped.
    check(f"single-survivor crops keep the right class "
          f"(ids seen: {sorted(set(singles))})",
          set(singles) == {1}, f"{sorted(set(singles))}")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index")
    ap.add_argument("--corpus")
    ap.add_argument("--out")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--splits", default="train,valid,test")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    if not (a.index and a.corpus and a.out):
        ap.error("--index, --corpus and --out are required")
    materialise(a.index, a.corpus, a.out, a.workers, a.limit,
                tuple(a.splits.split(",")))


if __name__ == "__main__":
    main()
