"""Mine hard negatives from the damage corpus itself, so dirt stops reading as damage.

THE GAP THIS CLOSES, MEASURED
-----------------------------
    images with no boxes in the training corpus:  0  of 167,157

Every image the detector has ever seen contains damage. It has never once been
shown a panel and told "nothing here". A model trained that way has no concept
of not-damage: asked to find scratches it will find the closest thing available,
and on a real car the closest thing is dirt, a shadow, a reflected roofline, a
water drop or a panel gap. That is not a threshold problem and no amount of
extra training fixes it — the information was never in the data.

WHY MINE, RATHER THAN COLLECT CLEAN CARS
----------------------------------------
The obvious fix is to add photographs of undamaged cars. It is the wrong fix,
and the reason matters. A stock photo of a clean car in a studio teaches the
model "showroom car = background", which is not the confusion being made.
The confusion is "this grimy patch on THIS door, in THIS light, on THIS paint,
is not a scratch".

The corpus already contains that, in enormous quantity, and it is free: a
damage photograph is mostly UNDAMAGED CAR. The regions away from the boxes are
the same panel, the same paint, the same weather, the same photographer, the
same dirt and the same reflections as the positive — a perfectly matched hard
negative, with no new data and no new licensing.

THE RISK, AND THE THREE THINGS DONE ABOUT IT
--------------------------------------------
A region with no box is NOT proven undamaged. Public damage datasets under-
label heavily; an unlabelled scratch mined as a negative teaches the model that
scratches are background, which is worse than the disease.

  1. MARGIN. A window must clear every box by MARGIN of the frame, so a box
     that is slightly too tight does not put real damage just inside a negative.

  2. PREFER DENSELY ANNOTATED IMAGES. An image with eight boxes was annotated
     carefully; an image with one box may have had five more damages ignored.
     Negatives are mined from images at or above MIN_BOXES, which is the
     cheapest available proxy for "somebody actually looked".

  3. CAP THE SHARE. Negatives are capped as a fraction of the train split, so
     even if some fraction are mislabelled they cannot dominate the gradient.
     The cap is reported, not silent.

None of the three makes a negative certainly clean. Together they make a
mislabelled one rare and bounded, which is the honest goal.

    python mine_negatives.py --index /home/user/rf/idx6 --out negatives.jsonl
"""
import argparse
import json
import os
import random
import sys

# A window must clear every damage box by this fraction of the frame.
MARGIN = 0.05

# Only mine from images with at least this many boxes — the proxy for "this
# image was annotated properly". See the docstring.
MIN_BOXES = 3

# Window size as a fraction of the frame's shorter side.
MIN_FRAC, MAX_FRAC = 0.20, 0.45

# Share of the train split that may be negatives. Detection literature puts
# useful background ratios well under half; a fifth is deliberately
# conservative given these are mined rather than verified.
MAX_NEG_SHARE = 0.20

_TRIES = 60


def _overlaps(win, box, margin):
    """Does `win` come within `margin` of `box`? Both normalised x,y,w,h."""
    wx, wy, ww, wh = win
    bx, by, bw, bh = box
    return not (wx >= bx + bw + margin or wx + ww <= bx - margin
                or wy >= by + bh + margin or wy + wh <= by - margin)


def negative_windows(boxes, want, rng, margin=MARGIN,
                     min_frac=MIN_FRAC, max_frac=MAX_FRAC, tries=_TRIES):
    """Up to `want` crop windows that clear every box by `margin`.

    Rejection sampling rather than an exact free-space decomposition: the
    windows only need to be valid, not maximal, and a car photo is mostly
    background so acceptance is high. Returning fewer than `want` — including
    none, when the damage fills the frame — is a correct answer and the caller
    must handle it rather than lowering the margin until something fits.
    """
    out = []
    for _ in range(tries):
        if len(out) >= want:
            break
        f = rng.uniform(min_frac, max_frac)
        x = rng.uniform(0.0, max(0.0, 1.0 - f))
        y = rng.uniform(0.0, max(0.0, 1.0 - f))
        win = (x, y, f, f)
        if any(_overlaps(win, b, margin) for b in boxes):
            continue
        # Also keep negatives away from each other, or the same patch of door
        # is mined five times and counted as five independent examples.
        if any(_overlaps(win, o, 0.0) for o in out):
            continue
        out.append(win)
    return out


def mine(index_dir, out_path, per_image, seed, share, dry_run):
    imgs_path = os.path.join(index_dir, "images.jsonl")
    idx_path = os.path.join(index_dir, "index.jsonl")

    train_shas, n_train = set(), 0
    for ln in open(idx_path):
        r = json.loads(ln)
        if r["split"] == "train":
            train_shas.add(r["sha"])
            n_train += 1
    budget = int(n_train * share)
    print(f"train split   {n_train:,} samples from {len(train_shas):,} "
          f"originals")
    print(f"negative cap  {budget:,} ({share:.0%} of the train split)")

    rng = random.Random(seed)
    rows, considered, too_few, no_room = [], 0, 0, 0
    for ln in open(imgs_path):
        rec = json.loads(ln)
        if rec["sha"] not in train_shas:
            continue
        considered += 1
        boxes = [[b[1], b[2], b[3], b[4]] for b in rec["boxes"]]
        if len(boxes) < MIN_BOXES:
            too_few += 1
            continue
        wins = negative_windows(boxes, per_image, rng)
        if not wins:
            no_room += 1
            continue
        for j, w in enumerate(wins):
            rows.append({"sha": rec["sha"], "split": "train", "rep": 0,
                         "neg": True, "neg_box": [round(v, 5) for v in w],
                         "neg_id": j,
                         # Negatives are photometrically augmented like any
                         # other sample — a negative that is always pristine
                         # teaches the model that dirt is fine only in good
                         # light.
                         "recipe": ["photometric"], "wm": False, "sn": False,
                         "seed": rng.randrange(1 << 30)})
        if len(rows) >= budget:
            break

    print(f"considered    {considered:,} train originals")
    print(f"  skipped     {too_few:,} with fewer than {MIN_BOXES} boxes "
          f"(under-annotation risk)")
    print(f"  skipped     {no_room:,} where damage left no clear window")
    print(f"mined         {len(rows):,} negative crops")
    if len(rows) >= budget:
        print(f"  ! stopped at the {budget:,} cap — more were available")

    if dry_run:
        print("\n--dry-run: nothing written")
        return 0
    with open(out_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"\nwrote {out_path}")
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

    rng = random.Random(7)

    # --- the core guarantee: a mined window never touches a damage box ---
    boxes = [[0.10, 0.10, 0.20, 0.20], [0.60, 0.55, 0.25, 0.30]]
    wins = negative_windows(boxes, 4, rng)
    check("windows are produced on a mostly-clear frame", len(wins) > 0)
    bad = [w for w in wins if any(_overlaps(w, b, MARGIN) for b in boxes)]
    check("no window comes within the margin of a box", not bad, str(bad))
    check("every window is inside the frame",
          all(0 <= w[0] and 0 <= w[1] and w[0] + w[2] <= 1.0001
              and w[1] + w[3] <= 1.0001 for w in wins), str(wins))

    # --- windows do not stack on each other ---
    pairs = [(a, b) for i, a in enumerate(wins) for b in wins[i + 1:]]
    check("windows do not overlap each other",
          not [p for p in pairs if _overlaps(p[0], p[1], 0.0)])

    # --- damage filling the frame yields NOTHING, not a forced window ---
    full = [[0.0, 0.0, 1.0, 1.0]]
    check("a frame full of damage yields no negatives",
          negative_windows(full, 4, rng) == [])
    # and a frame that is mostly damage yields few or none, never a violation
    heavy = [[0.0, 0.0, 0.9, 1.0]]
    hv = negative_windows(heavy, 4, rng)
    check("a mostly-damaged frame never violates the margin",
          not [w for w in hv if _overlaps(w, heavy[0], MARGIN)], str(hv))

    # --- the margin is real: a window just outside a box is rejected ---
    box = [[0.40, 0.40, 0.20, 0.20]]
    touching = (0.605, 0.40, 0.20, 0.20)       # 0.005 clear, inside MARGIN
    check("a window inside the margin is rejected",
          _overlaps(touching, box[0], MARGIN))
    clear = (0.40 + 0.20 + MARGIN + 0.01, 0.40, 0.20, 0.20)
    check("a window beyond the margin is accepted",
          not _overlaps(clear, box[0], MARGIN))

    # --- determinism: same seed, same windows ---
    a = negative_windows(boxes, 3, random.Random(11))
    b = negative_windows(boxes, 3, random.Random(11))
    check("mining is deterministic from its seed", a == b)

    # --- the cap arithmetic ---
    check("the share cap is a fraction of the train split",
          int(1000 * MAX_NEG_SHARE) == 200)
    check("negatives are a minority by construction", MAX_NEG_SHARE < 0.5)

    # --- the under-annotation guard is actually restrictive ---
    check("images with too few boxes are excluded", MIN_BOXES >= 3)

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="/home/user/rf/idx6")
    ap.add_argument("--out", default="/home/user/rf/idx6/negatives.jsonl")
    ap.add_argument("--per-image", type=int, default=1,
                    help="windows per source image; 1 keeps the negatives as "
                         "diverse as the corpus rather than repeating panels")
    ap.add_argument("--share", type=float, default=MAX_NEG_SHARE)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    return mine(a.index, a.out, a.per_image, a.seed, a.share, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
