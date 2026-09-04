"""Measure the corpus's LIGHT, per class, and say whether augmentation fixes it.

WHY THIS EXISTS
---------------
The product claim is "detects damage in any light — bright sun, rain, dusk".
Nothing in this project had ever checked what light the corpus actually
contains, so the claim rested on the augmentation pipeline being pointed at a
problem nobody had measured. Two different failures hide behind that:

  1. THE CORPUS IS UNIFORMLY BRIGHT. Scraped and marketplace photos are taken
     in daylight or a workshop, because that is when people photograph a car
     they are selling or claiming on. If the corpus has no dusk in it, the
     model has never seen dusk, and lowlight augmentation is the only thing
     standing between the claim and a lie.

  2. LIGHT IS CONFOUNDED WITH CLASS. This is the dangerous one. If rust photos
     are systematically darker than scratch photos — because rust is
     photographed underneath cars and in wheel arches — then brightness is a
     free signal for "rust", and the model will learn it. It will then score
     well in validation and fail on a rusty panel in direct sun, because it
     was never learning rust, it was learning shade. A per-class lighting
     table is the only way to see this before it costs a training run.

WHAT IS MEASURED, AND WHY THESE
-------------------------------
Per image, on a downscale (the statistics are global, so full resolution buys
nothing but time):

    luma        mean of ITU-R BT.601 luma. Overall exposure.
    rms_contrast   standard deviation of luma. Flat, hazy, overcast light has
                low contrast; hard sun has high. This is what separates
                "bright" from "harsh".
    clip_hi     fraction of pixels above 250. Blown highlights, which is what
                direct sun on a curved panel actually does to a photograph and
                the exact condition that destroys a chroma-based severity
                grade.
    clip_lo     fraction below 5. Crushed shadows.
    warmth      mean(R) - mean(B). A crude colour-temperature proxy: positive
                is tungsten/sunset, negative is overcast/shade/blue hour. It
                needs no white-balance metadata, which scraped JPEGs lack.
    sat         mean HSV saturation. Rain and haze desaturate.

Each is reduced to a per-class distribution and, crucially, to a SEPARATION
figure: how far apart the class means are relative to their spread. That is the
number that says whether light is a class cue, and it is reported per metric so
the offending metric can be named rather than "the data is biased".

    python audit_lighting.py --index /home/user/rf/idx8 --sample 6000
"""
import argparse
import collections
import hashlib
import json
import math
import os
import sys

# Bands used to report how much of the corpus sits in each lighting regime.
# Cuts are on 0-255 mean luma and chosen to match how a photograph reads rather
# than to split the data evenly: under 60 is genuinely dim, over 190 is a
# bright overexposed frame.
LUMA_BANDS = ((0, 60, "dim"), (60, 110, "low"), (110, 160, "normal"),
              (160, 190, "bright"), (190, 256, "blown"))

# A class mean this many pooled standard deviations from the corpus mean is
# treated as a usable shortcut for the model rather than noise. 0.35 is well
# below the conventional "small effect" 0.5 because the model gets to combine
# the cue across millions of samples, and it only needs a nudge.
CONFOUND_D = 0.35

SAMPLE_SIDE = 128


def measure(img):
    """Lighting statistics for one PIL image. Returns a dict of floats."""
    import numpy as np
    from PIL import Image as _Image
    # BOX, explicitly: a plain area average. The corpus is now 640px and 1000px
    # mixed, and the default filter would low-pass those two differently, so
    # CarDD would read as systematically flatter than the rest purely from
    # having been bigger — a fake finding manufactured by the instrument. An
    # area average reduces both to the same number of samples ACROSS THE FRAME,
    # so what survives is the scene's large-scale light, which is the thing
    # being measured, and it survives identically at either source size.
    im = img.convert("RGB").resize((SAMPLE_SIDE, SAMPLE_SIDE), _Image.BOX)
    a = np.asarray(im, dtype="float32")
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    n = luma.size
    return {
        "luma": float(luma.mean()),
        "rms_contrast": float(luma.std()),
        "clip_hi": float((luma > 250).sum()) / n,
        "clip_lo": float((luma < 5).sum()) / n,
        "warmth": float(r.mean() - b.mean()),
        "sat": float(sat.mean()),
    }


METRICS = ("luma", "rms_contrast", "clip_hi", "clip_lo", "warmth", "sat")


def band_of(luma):
    for lo, hi, name in LUMA_BANDS:
        if lo <= luma < hi:
            return name
    return LUMA_BANDS[-1][2]


def pooled_stats(values):
    """(mean, sd) with sd 0 for a degenerate sample rather than a crash."""
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    m = sum(values) / n
    if n < 2:
        return m, 0.0
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    return m, math.sqrt(max(0.0, var))


def cohens_d(a_mean, a_sd, b_mean, b_sd, na, nb):
    """Standardised difference between two groups, pooled sd."""
    if na < 2 or nb < 2:
        return 0.0
    sp2 = ((na - 1) * a_sd ** 2 + (nb - 1) * b_sd ** 2) / (na + nb - 2)
    sp = math.sqrt(max(1e-12, sp2))
    return (a_mean - b_mean) / sp


def run(index_dir, corpus, sample, out_json, seed):
    import random
    from PIL import Image

    with open(os.path.join(index_dir, "classes.json")) as f:
        classes = json.load(f)
    idx_to_name = {int(k): v for k, v in classes["index_to_name"].items()}

    # Rarest-class ownership needs corpus-wide counts, exactly as the index
    # builder computes them, so read the whole images file once first.
    recs = []
    counts = collections.Counter()
    with open(os.path.join(index_dir, "images.jsonl")) as f:
        for ln in f:
            rec = json.loads(ln)
            recs.append(rec)
            for b in rec["boxes"]:
                counts[idx_to_name.get(int(b[0]), str(b[0]))] += 1

    def owner(rec):
        # The index already records the grouping the sampler used. Trust it
        # over a recomputation: if the two ever disagreed, this table would
        # describe a split that was never trained, and quietly.
        if rec.get("owner_class"):
            return rec["owner_class"]
        present = {idx_to_name.get(int(b[0]), str(b[0]))
                   for b in rec["boxes"]}
        if not present:
            return "negative"
        return min(present, key=lambda c: (counts.get(c, 0), c))

    rng = random.Random(seed)
    rng.shuffle(recs)

    per_class = collections.defaultdict(lambda: collections.defaultdict(list))
    bands = collections.defaultdict(collections.Counter)
    want = sample or len(recs)
    done = failed = 0
    for rec in recs:
        if done >= want:
            break
        path = os.path.join(corpus, rec["file"])
        if not os.path.exists(path):
            failed += 1
            continue
        try:
            with Image.open(path) as im:
                m = measure(im)
        except Exception:
            failed += 1
            continue
        c = owner(rec)
        for k in METRICS:
            per_class[c][k].append(m[k])
        bands[c][band_of(m["luma"])] += 1
        done += 1
        if done % 1000 == 0:
            print(f"  {done}/{want}", flush=True)

    print(f"\nmeasured {done:,} images ({failed:,} unreadable)\n")

    names = sorted(per_class)
    # ---- overall lighting regime -------------------------------------
    print("LIGHTING REGIME, share of each class's images")
    band_names = [b[2] for b in LUMA_BANDS]
    print(f"{'class':16s} {'n':>7} " + " ".join(f"{b:>8}" for b in band_names))
    for c in names:
        tot = sum(bands[c].values()) or 1
        row = " ".join(f"{100.0 * bands[c][b] / tot:7.1f}%"
                       for b in band_names)
        print(f"{c:16s} {tot:>7,} {row}")

    all_bands = collections.Counter()
    for c in names:
        all_bands.update(bands[c])
    tot = sum(all_bands.values()) or 1
    row = " ".join(f"{100.0 * all_bands[b] / tot:7.1f}%" for b in band_names)
    print(f"{'ALL':16s} {tot:>7,} {row}")

    # ---- per-metric class means --------------------------------------
    stats = {}
    for c in names:
        stats[c] = {k: pooled_stats(per_class[c][k]) for k in METRICS}
        stats[c]["n"] = len(per_class[c]["luma"])

    print("\nPER-CLASS LIGHT (mean +- sd)")
    print(f"{'class':16s} {'n':>7} " + " ".join(f"{m:>16}" for m in METRICS))
    for c in names:
        cells = " ".join(f"{stats[c][k][0]:8.2f}+-{stats[c][k][1]:<6.2f}"
                         for k in METRICS)
        print(f"{c:16s} {stats[c]['n']:>7,} {cells}")

    # ---- the confound test -------------------------------------------
    # Each class against EVERY OTHER CLASS POOLED, which is the comparison the
    # model actually faces: it does not tell classes apart from the corpus
    # mean, it tells them apart from each other.
    print(f"\nIS LIGHT A CLASS CUE?  (Cohen's d vs all other classes pooled; "
          f"|d| >= {CONFOUND_D} flagged)")
    findings = []
    for c in names:
        for k in METRICS:
            mine = per_class[c][k]
            others = [v for o in names if o != c for v in per_class[o][k]]
            am, asd = pooled_stats(mine)
            bm, bsd = pooled_stats(others)
            d = cohens_d(am, asd, bm, bsd, len(mine), len(others))
            if abs(d) >= CONFOUND_D:
                findings.append((abs(d), c, k, d, am, bm))
    findings.sort(reverse=True)
    if findings:
        for ad, c, k, d, am, bm in findings:
            direction = "HIGHER" if d > 0 else "LOWER"
            print(f"  d {d:+6.2f}  {c:16s} {k:14s} {direction} "
                  f"({am:.2f} vs {bm:.2f} elsewhere)")
        print(f"\n  {len(findings)} class/metric pairs are separable by light "
              f"alone. Each is a shortcut the model can take instead of "
              f"learning the damage.")
    else:
        print("  none — no class is distinguishable by light alone at "
              f"|d| >= {CONFOUND_D}")

    if out_json:
        with open(out_json, "w") as f:
            json.dump({
                "measured": done, "metrics": list(METRICS),
                "per_class": {c: {k: list(stats[c][k]) for k in METRICS}
                              | {"n": stats[c]["n"]} for c in names},
                "bands": {c: dict(bands[c]) for c in names},
                "confounds": [{"class": c, "metric": k, "d": round(d, 3),
                               "class_mean": round(am, 3),
                               "other_mean": round(bm, 3)}
                              for _ad, c, k, d, am, bm in findings],
            }, f, indent=1)
        print(f"\nwrote {out_json}")
    return 0


def run_augmented(index_dir, corpus, sample, seed):
    """Does augmentation actually reach the light the corpus does not contain?

    The corpus table answers "what light do we have". This answers the only
    question that follows from it: whether the weather ops move images INTO the
    empty regions, or merely jitter them around where they already were. An
    augmentation that darkens a normal frame to another normal frame adds
    nothing but compute, and the difference is invisible without measuring.

    Every op is applied to the SAME sample, so the bands are directly
    comparable and a shift cannot be an artefact of which images were drawn.
    """
    import random
    from PIL import Image
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import augment

    recs = []
    with open(os.path.join(index_dir, "images.jsonl")) as f:
        for ln in f:
            recs.append(json.loads(ln))
    rng = random.Random(seed)
    rng.shuffle(recs)

    ops = [("original", None),
           ("photometric", augment.photometric),
           ("lowlight", augment.lowlight),
           ("harshsun", augment.harshsun),
           ("wet", augment.wet)]
    bands = {n: collections.Counter() for n, _ in ops}
    means = {n: collections.defaultdict(list) for n, _ in ops}

    done = 0
    for rec in recs:
        if done >= sample:
            break
        path = os.path.join(corpus, rec["file"])
        if not os.path.exists(path):
            continue
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                for name, fn in ops:
                    # Seeded from the sha TEXT, not from hash(): Python
                    # randomises str hashing per process, so hash((sha, name))
                    # gave a different seed on every run while the comment
                    # here claimed the table reproduced exactly. Two runs of
                    # this audit were not comparable, which is the one thing
                    # an audit has to be.
                    r = random.Random(
                        int(hashlib.sha256(
                            (rec["sha"] + name).encode()).hexdigest()[:8], 16))
                    out = im if fn is None else fn(im, r)
                    m = measure(out)
                    bands[name][band_of(m["luma"])] += 1
                    for k in METRICS:
                        means[name][k].append(m[k])
        except Exception:
            continue
        done += 1
        if done % 200 == 0:
            print(f"  {done}/{sample}", flush=True)

    print(f"\naugmented {done:,} images through {len(ops)} paths\n")
    band_names = [b[2] for b in LUMA_BANDS]
    print("LIGHTING REGIME after each op, share of the sample")
    print(f"{'op':14s} " + " ".join(f"{b:>8}" for b in band_names)
          + f" {'luma':>8} {'contrast':>9} {'clip_hi':>8} {'sat':>6}")
    for name, _fn in ops:
        tot = sum(bands[name].values()) or 1
        row = " ".join(f"{100.0 * bands[name][b] / tot:7.1f}%"
                       for b in band_names)
        lm = pooled_stats(means[name]["luma"])[0]
        ct = pooled_stats(means[name]["rms_contrast"])[0]
        ch = pooled_stats(means[name]["clip_hi"])[0]
        st = pooled_stats(means[name]["sat"])[0]
        print(f"{name:14s} {row} {lm:8.1f} {ct:9.1f} {ch:8.3f} {st:6.3f}")

    # The verdict: an op EARNS its place only by putting images somewhere the
    # original sample is thin. Stated as the band it fills and by how much.
    print("\nWHAT EACH OP ADDS (share in each band, minus the original's)")
    base = bands["original"]
    btot = sum(base.values()) or 1
    for name, _fn in ops[1:]:
        tot = sum(bands[name].values()) or 1
        deltas = []
        for b in band_names:
            d = 100.0 * bands[name][b] / tot - 100.0 * base[b] / btot
            deltas.append(f"{b} {d:+.1f}pp")
        print(f"  {name:12s} " + "  ".join(deltas))
    return 0


def _selftest():
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  ok   {name}")
        else:
            fail += 1
            print(f"  FAIL {name} {detail}")

    from PIL import Image
    import numpy as np

    def img(arr):
        return Image.fromarray(np.asarray(arr, dtype="uint8"), "RGB")

    dark = img(np.full((64, 64, 3), 20))
    bright = img(np.full((64, 64, 3), 220))
    md, mb = measure(dark), measure(bright)
    check("a dark frame measures lower luma than a bright one",
          md["luma"] < mb["luma"], f"{md['luma']} vs {mb['luma']}")
    check("a flat frame has near-zero contrast", md["rms_contrast"] < 1.0,
          str(md["rms_contrast"]))

    # A blown frame must register on clip_hi, or the harsh-sun case is
    # invisible to this audit and the whole point is lost.
    blown = img(np.full((64, 64, 3), 255))
    check("a blown frame is caught by clip_hi",
          measure(blown)["clip_hi"] > 0.9, str(measure(blown)["clip_hi"]))
    black = img(np.zeros((64, 64, 3)))
    check("a crushed frame is caught by clip_lo",
          measure(black)["clip_lo"] > 0.9)

    warm = np.zeros((64, 64, 3))
    warm[..., 0] = 200
    warm[..., 2] = 100
    cool = np.zeros((64, 64, 3))
    cool[..., 0] = 100
    cool[..., 2] = 200
    check("warmth is positive for a red-heavy frame",
          measure(img(warm))["warmth"] > 50)
    check("warmth is negative for a blue-heavy frame",
          measure(img(cool))["warmth"] < -50)

    grey = img(np.full((64, 64, 3), 128))
    check("a grey frame has near-zero saturation",
          measure(grey)["sat"] < 0.01)

    # A high-contrast frame must beat a flat one, which is what separates
    # hard sun from overcast. The split is HALF THE FRAME rather than a fine
    # checkerboard: an area downsample averages a 1px checkerboard to flat
    # grey and would report zero contrast, which is correct behaviour for a
    # LIGHTING measure and a wrong test. Contrast here means light and shade
    # across the scene, not texture.
    split = np.zeros((256, 256, 3))
    split[:128] = 255
    check("a half-lit frame has high contrast",
          measure(img(split))["rms_contrast"] > 100,
          str(measure(img(split))["rms_contrast"]))
    fine = np.zeros((256, 256, 3))
    fine[::2] = 255
    check("fine texture is not counted as lighting contrast",
          measure(img(fine))["rms_contrast"] < 5.0,
          str(measure(img(fine))["rms_contrast"]))

    check("bands cover the whole 0-255 range without a gap",
          all(LUMA_BANDS[i][1] == LUMA_BANDS[i + 1][0]
              for i in range(len(LUMA_BANDS) - 1))
          and LUMA_BANDS[0][0] == 0 and LUMA_BANDS[-1][1] == 256)
    check("band_of places a dim frame in dim", band_of(30) == "dim")
    check("band_of places a blown frame in blown", band_of(240) == "blown")

    m, sd = pooled_stats([1.0, 1.0, 1.0])
    check("a constant sample has zero spread", m == 1.0 and sd == 0.0)
    check("a single sample does not crash the spread",
          pooled_stats([5.0]) == (5.0, 0.0))
    check("an empty sample does not crash", pooled_stats([]) == (0.0, 0.0))

    # Cohen's d sign and magnitude.
    d = cohens_d(10.0, 1.0, 8.0, 1.0, 50, 50)
    check("two sd of separation reads as d ~ 2", abs(d - 2.0) < 0.05, str(d))
    check("d is signed by direction",
          cohens_d(8.0, 1.0, 10.0, 1.0, 50, 50) < 0)
    check("identical groups have d 0",
          cohens_d(5.0, 2.0, 5.0, 2.0, 50, 50) == 0.0)
    check("the confound threshold is stricter than a conventional "
          "small effect", CONFOUND_D < 0.5)

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="/home/user/rf/idx8")
    ap.add_argument("--corpus", default="/home/user/rf/merged640")
    ap.add_argument("--sample", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--out", default="/home/user/rf/lighting_audit.json")
    ap.add_argument("--augmented", action="store_true",
                    help="measure what the weather ops do to the light, "
                         "rather than what the corpus already contains")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.augmented:
        return run_augmented(a.index, a.corpus, a.sample, a.seed)
    return run(a.index, a.corpus, a.sample, a.out, a.seed)


if __name__ == "__main__":
    sys.exit(main())
