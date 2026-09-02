"""Remap a Roboflow COCO export onto this product's damage taxonomy.

Public car-damage datasets each invent their own class names ("Rust_Corrision",
"Flat Tire", "Lamp Broken"). The worker speaks exactly one vocabulary —
taxonomy.DAMAGE_TYPES — and detect.py's severity floors, the repair pricing and
the structural-concern gate are all keyed on it. Remapping at DATA-PREP time
rather than at inference time means the trained model emits taxonomy ids
natively: no translation layer at runtime, and no chance of a class silently
failing to map on a customer's scan.

It also writes labels.txt in the exact index order the model is trained on.
That file IS the contract with DAMAGE_DETECTOR_LABELS at inference — if the two
ever disagree, every prediction is mislabelled while looking perfectly healthy,
so it is generated here rather than typed by hand anywhere.

Usage:
    python prepare_data.py --src /path/to/roboflow-coco --out /path/to/prepared
"""
import argparse
import json
import os
import collections

# Source class name (lowercased) -> taxonomy damage id. Extend this when adding
# a dataset; an unmapped class is reported loudly rather than silently dropped,
# because a class that vanishes here is damage the product can never detect.
CLASS_MAP = {
    "crack": "crack", "cracked": "crack", "crack_and_hole": "crack",
    "dent": "dent", "dents": "dent", "deformation": "deformation",
    "scratch": "scratch", "scratches": "scratch",
    "paint damage": "paint_chip", "paint_damage": "paint_chip",
    "paint chip": "paint_chip", "paint-chip": "paint_chip",
    "rust_corrision": "rust", "rust_corrosion": "rust", "rust": "rust",
    "corrosion": "rust",
    "flat tire": "tire_damage", "flat_tire": "tire_damage",
    "tire flat": "tire_damage",
    "lamp broken": "lamp_damage", "lamp_broken": "lamp_damage",
    "broken lamp": "lamp_damage", "headlight-damage": "lamp_damage",
    "taillight-damage": "lamp_damage",
    "glass shatter": "shattered_glass", "windshield_damage": "shattered_glass",
    "front-windscreen-damage": "shattered_glass",
    "rear-windscreen-damage": "shattered_glass",
    "missing part": "missing_part", "missing_part": "missing_part",
    "broken part": "missing_part",

    # ---- RECOVERED 2026-09-01 ------------------------------------------
    # An audit of the 41 manifest datasets found 35 of 59 source class
    # strings reaching no target and being DELETED at merge, along with any
    # image left with no surviving box. These are the ones whose meaning is
    # unambiguous; the junk below is left unmapped on purpose.
    #
    # Lookup is already .lower()'d by both callers, so only lower-case keys
    # are needed here -- an earlier reading of this file claimed a
    # case-sensitivity bug and was wrong.

    # gross body damage -> the existing structural bucket
    "broken": "missing_part", "broken_part": "missing_part",
    "break": "missing_part", "deframe": "missing_part",
    "missing": "missing_part",
    "crush": "deformation",

    # glass. "shatter" and "glass-broken" are the same event as the mapped
    # "glass shatter"; the three Glass-*-crack strings are windscreen cracks,
    # which belong with crack rather than with a shattered pane.
    "shatter": "shattered_glass", "broken_glass": "shattered_glass",
    "glass-broken": "shattered_glass",
    "glass-large-crack": "crack", "glass-small-crack": "crack",
    "glass-spider-crack": "crack",

    "broken_headlight": "lamp_damage",

    # corrosion, in the several vocabularies the sources use. "rost" is
    # German. The three named corrosion morphologies are all rust to us.
    "rost": "rust", "corrosion-detection": "rust",
    "copper corrosion": "rust", "crevice corrosion": "rust",
    "pitting corrosion": "rust", "uniform corrosion": "rust",

    "flaking": "paint_chip",
    "dent--1": "dent",
    # uniud-g3oa7/scratch-detection: "Defect" is that project's only class
    # and the project is a scratch dataset.
    "defect": "scratch",

    # PANEL GAP -- the four spellings four projects use for one fault.
    # Excluded until 2026-09-02, when the vocabulary went from six classes to
    # seven. Adding these SHIFTS EVERY CLASS ID, so an index built after this
    # point cannot be loaded by a six-class model such as v12b or v16.
    "misalignment": "panel_gap", "dislocation": "panel_gap",
    "disalocation": "panel_gap", "separation": "panel_gap",

    # ---- RECOVERED 2026-09-02: the thirteen undocumented projects ---------
    #
    # /home/user/rf/bulk/provenance.jsonl records 13 Roboflow projects,
    # 104,962 images, downloaded and merged in an earlier session and absent
    # from manifest.json. 78 of their 95 class strings mapped to nothing, so
    # their boxes were deleted while their pixels stayed -- the images are in
    # merged640, unlabelled, to this day.
    #
    # Three vocabularies are at work and each is handled on its own terms.

    # 1. PANEL-SPECIFIC DAMAGE. "bonnet-dent", "fender-dent", "roof-dent" are
    #    a dent plus the panel it is on. The panel half is thrown away here on
    #    purpose: panel_attribution.py derives the panel from the panel
    #    DETECTOR at inference, which works on any photo, whereas a class per
    #    panel would need 21x the data and could not generalise to a panel a
    #    given project never labelled.
    "bonnet-dent": "dent", "roof-dent": "dent", "fender-dent": "dent",
    "pillar-dent": "dent", "doorouter-dent": "dent", "boot-dent": "dent",
    "front-bumper-dent": "dent", "rear-bumper-dent": "dent",
    "quaterpanel-dent": "dent", "quarter-panel-dent": "dent",
    "runningboard-dent": "dent", "running-board-dent": "dent",
    "medium-bodypanel-dent": "dent", "major-rear-bumper-dent": "dent",
    "damaged-hood": "dent", "damaged-trunk": "dent", "damaged-door": "dent",
    "damaged_door": "dent", "damaged_fender": "dent",
    "damaged-front-bumper": "dent", "damaged-rear-bumper": "dent",
    "damaged_bumper": "dent",
    "doorouter-scratch": "scratch", "doorouter-paint-trace": "scratch",

    # 2. GLASS AND LAMPS, spelled a dozen ways across four projects.
    "damaged-windscreen": "shattered_glass",
    "windscreen-front-damage": "shattered_glass",
    "windscreen-rear-damage": "shattered_glass",
    "damaged-window": "shattered_glass",
    "damaged-rear-window": "shattered_glass",
    "broken_window": "shattered_glass",
    "damaged_mirror_glass": "shattered_glass",
    "damaged-head-light": "lamp_damage", "damaged-tail-light": "lamp_damage",
    "headlight-damage": "lamp_damage", "taillight-damage": "lamp_damage",
    "signlight-damage": "lamp_damage",
    "side-indicator-damage": "lamp_damage",
    "sidemirror-damage": "lamp_damage", "side-mirror-damage": "lamp_damage",
    "missing_grille": "missing_part",

    # 3. INDONESIAN. rfvnx-dgm7e labels in Indonesian: penyok = dent,
    #    goresan = scratch, kerusakan = damage-to-<part>, kaca = glass,
    #    lampu = lamp, spion = mirror, bagasi = boot, kap mesin = bonnet.
    "penyok": "dent", "penyok_atap": "dent", "penyok_fender": "dent",
    "penyok_pilar": "dent", "penyok_luar_pintu": "dent",
    "penyok_kap_depan": "dent", "penyok_quarterpanel": "dent",
    "penyok_bumper_depan": "dent", "penyok_bumper_belakang": "dent",
    "penyok_running_board": "dent", "penyok_atau_gores": "dent",
    "goresan": "scratch",
    "kerusakan_kaca_depan": "shattered_glass",
    "kerusakan_kaca_belakang": "shattered_glass",
    "kerusakan_kaca_samping": "shattered_glass",
    "kerusakan_windscreen": "shattered_glass",
    "kerusakan_lampu_depan": "lamp_damage",
    "kerusakan_lampu_belakang": "lamp_damage",
    "kerusakan_lampu_samping": "lamp_damage",
    "kerusakan_spion": "lamp_damage",
    "kerusakan_pintu": "dent", "kerusakan_bagasi": "dent",
    "kerusakan_kap_mesin": "dent",
    "kerusakan_bumper_depan": "dent", "kerusakan_bumper_belakang": "dent",

    # 4. SEVERITY-GRADED. The grade is dropped and the type kept: a
    #    three-point severity scale that only two projects use cannot be
    #    learned, but the underlying dent/scratch/rust can.
    "slight_deformation": "dent", "medium_deformation": "dent",
    "severe_deformation": "deformation",
    "slight_scratch": "scratch", "severe_scratch": "scratch",
    "mild-corrosion": "rust", "moderate-corrosion": "rust",
    "severe-corrosion": "rust", "corroded-part": "rust", "iron rust": "rust",

    # DELIBERATELY LEFT OUT, and why:
    #   Car-Damage, damaged, kerusakan_umum, Damage, dent-or-scratch, other
    #     -- generic "something is wrong here". Mapping them to any one type
    #        teaches the detector that dents and scratches share a class.
}

# DELIBERATELY NOT MAPPED, so the unmapped report stays a real signal:
#   object, doggie, 0, 1, 2   -- junk or unlabelled placeholder classes
#   non-corrosion             -- a NEGATIVE class; merge() deletes images with
#                                no positive box, so it cannot be expressed here
#   spall                     -- concrete spalling (universita-di-pisa), and
#                                that project is off-domain anyway
#
# The four panel-gap spellings used to be listed here as deliberately excluded.
# They were mapped on 2026-09-02 and are now in CLASS_MAP above.

# Roboflow exports carry a supercategory row with no annotations; it is not a
# class and must not consume a model index.
IGNORE = {"cars", "car", "damage", "objects", "none"}

# A class the model has barely seen fires essentially at random. Shipping one is
# worse than not detecting it at all: a confident-looking wrong finding lands on
# an invoice. Anything under this many boxes is dropped, and the drop is logged.
MIN_BOXES = 50

# Category 0 is a reserved supercategory slot in the Roboflow/RF-DETR COCO
# convention, not a detectable class.
PLACEHOLDER = "_placeholder_"


def load(path):
    with open(path) as f:
        return json.load(f)


def remap_split(coco, keep=None):
    """Return (new_coco, per-class box counts, unmapped names)."""
    cats = {c["id"]: c["name"] for c in coco.get("categories", [])}
    counts = collections.Counter()
    unmapped = collections.Counter()
    for a in coco.get("annotations", []):
        name = cats.get(a["category_id"], "")
        low = name.strip().lower()
        if low in IGNORE:
            continue
        tid = CLASS_MAP.get(low)
        if not tid:
            unmapped[name] += 1
            continue
        counts[tid] += 1
    if keep is None:
        keep = sorted(t for t, n in counts.items() if n >= MIN_BOXES)

    # Real classes start at id 1, with a placeholder occupying id 0.
    #
    # This is not cosmetic. RF-DETR (and the Roboflow COCO convention it is
    # built around) reserves category 0 as a supercategory placeholder and
    # expects real classes from 1. Reindexing from 0 here trains a model whose
    # every prediction is off by one class — dents reported as cracks — while
    # loss curves and mAP look completely healthy, because the labels are
    # self-consistent during training and only wrong against the taxonomy. The
    # placeholder is carried into labels.txt for the same reason, so the
    # index -> name lookup at inference lines up with what was trained.
    index = {t: i + 1 for i, t in enumerate(keep)}
    new_cats = [{"id": 0, "name": PLACEHOLDER, "supercategory": "none"}]
    new_cats += [{"id": i, "name": t, "supercategory": "damage"}
                 for t, i in sorted(index.items(), key=lambda kv: kv[1])]
    new_anns = []
    for a in coco.get("annotations", []):
        tid = CLASS_MAP.get(cats.get(a["category_id"], "").strip().lower())
        if tid is None or tid not in index:
            continue
        x, y, w, h = a["bbox"]
        if w <= 0 or h <= 0:          # degenerate boxes break box losses
            continue
        b = dict(a)
        b["category_id"] = index[tid]
        new_anns.append(b)
    out = dict(coco)
    out["categories"] = new_cats
    out["annotations"] = new_anns
    return out, counts, unmapped, keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="Roboflow COCO export root")
    ap.add_argument("--out", required=True)
    ap.add_argument("--splits", default="train,valid,test")
    args = ap.parse_args()

    splits = [s for s in args.splits.split(",") if s]
    os.makedirs(args.out, exist_ok=True)

    # The train split decides the label set; valid/test must reuse it verbatim,
    # or the indices drift between splits and the metrics become meaningless.
    keep = None
    all_unmapped = collections.Counter()
    for split in splits:
        src = os.path.join(args.src, split, "_annotations.coco.json")
        if not os.path.exists(src):
            print(f"  ! {split}: no annotations, skipped")
            continue
        coco = load(src)
        new, counts, unmapped, keep = remap_split(coco, keep)
        all_unmapped.update(unmapped)
        dst_dir = os.path.join(args.out, split)
        os.makedirs(dst_dir, exist_ok=True)
        with open(os.path.join(dst_dir, "_annotations.coco.json"), "w") as f:
            json.dump(new, f)
        print(f"  {split:6s} images={len(new.get('images', [])):6d} "
              f"boxes={len(new['annotations']):6d}")
        if split == splits[0]:
            for t in keep:
                print(f"      {t:18s} {counts[t]:6d}")
            dropped = {t: n for t, n in counts.items() if t not in keep}
            if dropped:
                print(f"      dropped (<{MIN_BOXES} boxes): {dropped}")

    with open(os.path.join(args.out, "labels.txt"), "w") as f:
        # Leading placeholder keeps this aligned with category id 0.
        f.write(",".join([PLACEHOLDER] + (keep or [])))
    print(f"\nlabels.txt -> {','.join([PLACEHOLDER] + (keep or []))}")
    print("Set DAMAGE_DETECTOR_LABELS to exactly this string at inference.")
    if all_unmapped:
        print(f"\n! UNMAPPED source classes (add to CLASS_MAP or they are lost): "
              f"{dict(all_unmapped)}")


if __name__ == "__main__":
    main()
