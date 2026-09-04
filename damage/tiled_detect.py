"""Run the detector on overlapping native-resolution tiles, then stitch.

WHY A WHOLE-IMAGE PASS CANNOT FIND A FINE SCRATCH
-------------------------------------------------
The detector takes a fixed square input. A phone photograph of a car door is
4032x3024; at 728 that is a 5.5x reduction, and a 3-pixel hairline scratch
becomes 0.54 of a pixel. It is not that the model is not good enough to see it.
It is that after the resize there is nothing left to see — the scratch has been
averaged into the paint before the first convolution runs.

    photo 4032 wide, scratch 3px  ->  at 728: 0.54px   gone
                                  ->  at 560: 0.42px   gone
    same photo cut into 1456px tiles, each resized to 728:
                                       1.5px            survives

Raising the training resolution helps a little and costs quadratically. Tiling
is the change that actually matters for the fine-scratch case, and it costs
only inference time on the CPU worker, where there is no GPU bill.

THE FULL-IMAGE PASS IS KEPT AS WELL, and this is not belt-and-braces. Damage
larger than a tile — a caved-in door, a bumper hanging off — appears in every
tile as a fragment of a surface and in none of them as the thing it is. Tiles
find small damage, the full frame finds large damage, and the merge below is
what lets both be reported once.

STITCHING IS THE HARD PART, NOT TILING
--------------------------------------
Plain non-maximum suppression is wrong here and quietly inflates the damage
count. A 400px scratch crossing two tile seams comes back as three boxes of
~140px each. Their IoU with each other is zero, so NMS keeps all three, and the
report says "three scratches" on a car with one. Worse, each fragment is short,
so any severity measure based on extent under-rates all three.

So merging has two rules, not one:

    duplicates  — same label, IoU above IOU_MERGE. One thing seen twice in the
                  overlap between neighbouring tiles.
    fragments   — same label, both elongated the same way, aligned across their
                  short axis, and separated by less than JOIN_GAP along their
                  long axis. One thing cut by a seam.

Both are resolved by union-find over the pairs and then taking the union box,
so a scratch broken into four pieces reassembles in one pass regardless of the
order the tiles were processed in.

WHAT THIS DOES NOT FIX
----------------------
Tiling cannot recover a scratch that the camera did not resolve. If the photo
is soft, or shot from three metres, the scratch is not in the file and no
amount of cropping puts it there. quality.py is what should catch that, before
any of this runs.

    dets = tiled_detect(img, run)     # run(PIL.Image) -> [{label,score,box}]
"""
import math

# Tile side in SOURCE pixels, as a multiple of the model's input side. 2.0
# means each tile is downsampled by at most 2x on the way in, so detail
# survives at half the sensor's resolution instead of a fifth of it. Larger
# multiples are cheaper and blinder; 1.0 would be sharpest and would multiply
# the tile count by four for very little gain, because the detector was trained
# on downsampled images and does not expect pixel-level grain.
TILE_SCALE = 2.0

# Fraction of a tile shared with its neighbour. Damage sitting exactly on a
# seam must appear WHOLE in at least one tile for the fragment rule to have
# something to anchor to; 0.25 means anything shorter than a quarter tile
# always does.
OVERLAP = 0.25

# Same-label boxes above this IoU are the same damage seen twice.
IOU_MERGE = 0.45

# Fragments of one scratch: how far apart the ends may be, as a fraction of
# the longer fragment's length.
JOIN_GAP = 0.35

# Minimum aspect ratio for a box to count as elongated, i.e. capable of being
# a fragment of something longer. A blob is never treated as a fragment.
ELONGATED = 2.0

# Classes whose damage is genuinely long and thin, and so is the only kind
# that can be cut into fragments by a seam. A dent is not stitched to another
# dent: two dents next to each other are two dents.
_FRAGMENTABLE = {"scratch_scuff", "scratch", "crack_glass", "crack",
                 "rust_paint", "surface"}


def tile_grid(size, tile, overlap=OVERLAP):
    """Cover (w, h) with square tiles of side `tile`, overlapping by `overlap`.

    The last row and column are pulled BACK to the image edge rather than
    extending past it. Padding the overhang with black was the obvious
    alternative and is worse: the detector has never seen a hard black edge in
    the middle of a panel and fires on it, so every image gained phantom
    detections along its right and bottom margins.
    """
    w, h = int(size[0]), int(size[1])
    tile = int(tile)
    if tile <= 0:
        raise ValueError("tile must be positive")
    if w <= tile and h <= tile:
        return [(0, 0, w, h)]
    step = max(1, int(round(tile * (1.0 - overlap))))

    def starts(extent):
        if extent <= tile:
            return [0]
        out = list(range(0, max(1, extent - tile) + 1, step))
        if out[-1] != extent - tile:
            out.append(extent - tile)
        return out

    return [(x, y, min(tile, w), min(tile, h))
            for y in starts(h) for x in starts(w)]


def _iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = ((ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter)
    return inter / ua if ua > 0 else 0.0


def _shape(box):
    """(long axis length, short axis length, 'h' or 'v')."""
    w = max(0.0, box[2] - box[0])
    h = max(0.0, box[3] - box[1])
    return (w, h, "h") if w >= h else (h, w, "v")


def _is_fragment_pair(a, b):
    """Are these two boxes pieces of one long thin thing cut by a seam?

    Requires all three of: both elongated, elongated the SAME way, and
    overlapping across the short axis while nearly touching along the long
    axis. Dropping any one of them merges genuinely separate damage — two
    parallel scratches on a door panel are two scratches, and they overlap
    along the long axis without overlapping across the short one.
    """
    la, sa, da = _shape(a)
    lb, sb, db = _shape(b)
    if da != db:
        return False
    if sa <= 0 or sb <= 0:
        return False
    if la / sa < ELONGATED or lb / sb < ELONGATED:
        return False

    if da == "h":
        lo_a, hi_a, cross_a = a[0], a[2], (a[1], a[3])
        lo_b, hi_b, cross_b = b[0], b[2], (b[1], b[3])
    else:
        lo_a, hi_a, cross_a = a[1], a[3], (a[0], a[2])
        lo_b, hi_b, cross_b = b[1], b[3], (b[0], b[2])

    # Across the short axis the two pieces must line up: a scratch does not
    # jump sideways at a seam.
    overlap = min(cross_a[1], cross_b[1]) - max(cross_a[0], cross_b[0])
    if overlap <= 0:
        return False
    if overlap < 0.5 * min(cross_a[1] - cross_a[0], cross_b[1] - cross_b[0]):
        return False

    gap = max(lo_a, lo_b) - min(hi_a, hi_b)     # negative when they overlap
    return gap <= JOIN_GAP * max(la, lb)


def merge_detections(dets, iou_merge=IOU_MERGE):
    """Collapse duplicates and reassemble seam-split damage. Union-find.

    Order-independent by construction, which matters because tiles are
    processed in raster order and a scratch's fragments therefore arrive in an
    arbitrary order relative to the whole-image detection of the same scratch.
    """
    n = len(dets)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    for i in range(n):
        for j in range(i + 1, n):
            if dets[i]["label"] != dets[j]["label"]:
                continue
            a, b = dets[i]["box"], dets[j]["box"]
            if _iou(a, b) >= iou_merge:
                union(i, j)
            elif (dets[i]["label"] in _FRAGMENTABLE
                  and _is_fragment_pair(a, b)):
                union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    out = []
    for members in groups.values():
        boxes = [dets[i]["box"] for i in members]
        merged = [min(b[0] for b in boxes), min(b[1] for b in boxes),
                  max(b[2] for b in boxes), max(b[3] for b in boxes)]
        best = max(members, key=lambda i: dets[i]["score"])
        out.append({
            "label": dets[best]["label"],
            # The best fragment's score, not the mean. A scratch seen clearly
            # in one tile and marginally in the next is a scratch seen clearly;
            # averaging would penalise it for having been cut in half by a
            # grid this module chose.
            "score": dets[best]["score"],
            "box": merged,
            "parts": len(members),
        })
    out.sort(key=lambda d: -d["score"])
    return out


def tiled_detect(img, run, model_size=728, tile_scale=TILE_SCALE,
                 overlap=OVERLAP, full_pass=True, max_tiles=64):
    """Detect over tiles plus the whole frame, in ORIGINAL image coordinates.

    `run` takes a PIL image and returns [{label, score, box}] with boxes in
    that image's own pixels — i.e. exactly what onnx_detect already returns —
    so this composes with the existing backend instead of replacing it.

    max_tiles is a guard, not an optimisation: a 48MP panorama at TILE_SCALE 2
    would otherwise be 200 tiles and several minutes of CPU per photograph.
    Past the limit the tile side grows until the count fits, which loses
    resolution gracefully rather than hanging the worker.
    """
    w, h = img.size
    tile = max(64, int(round(model_size * tile_scale)))
    grid = tile_grid((w, h), tile, overlap)
    while len(grid) > max_tiles and tile < max(w, h):
        tile = int(tile * 1.4)
        grid = tile_grid((w, h), tile, overlap)

    # A TILE THE SIZE OF THE FRAME IS NOT A TILE.
    #
    # tile_scale 2.0 at model_size 560 asks for 1120px tiles, so any image
    # below that gets a grid of exactly one tile covering the whole picture.
    # With full_pass on, the same frame is then run twice through the same
    # model and the two identical result sets are merged: double the inference
    # cost, no extra resolution, and a merge step that can only lose. Measured
    # on 250 ECC photos (median 676px, so every one hit this path) it cost
    # -0.8pp F1 against the plain untiled run, and recall on sub-0.01% damage
    # stayed at exactly 0.0% -- the band tiling exists to rescue.
    #
    # Tiling helps only when the SOURCE has more pixels than the model input.
    # When the grid degenerates, say so and take the full pass alone.
    if full_pass and len(grid) == 1:
        tx, ty, tw, th = grid[0]
        if tw >= w and th >= h:
            return merge_detections([
                {"label": d["label"], "score": float(d["score"]),
                 "box": list(d["box"]), "source": "full"}
                for d in run(img) or []])

    dets = []
    for (tx, ty, tw, th) in grid:
        crop = img.crop((tx, ty, tx + tw, ty + th))
        for d in run(crop) or []:
            b = d["box"]
            dets.append({"label": d["label"], "score": float(d["score"]),
                         "box": [b[0] + tx, b[1] + ty, b[2] + tx, b[3] + ty],
                         "source": "tile"})
    if full_pass:
        for d in run(img) or []:
            dets.append({"label": d["label"], "score": float(d["score"]),
                         "box": list(d["box"]), "source": "full"})
    return merge_detections(dets)


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

    # --- the grid covers every pixel and never leaves the frame ---
    for size in [(4032, 3024), (1000, 800), (700, 700), (1456, 300)]:
        g = tile_grid(size, 1456)
        inside = all(x >= 0 and y >= 0 and x + tw <= size[0]
                     and y + th <= size[1] for x, y, tw, th in g)
        check(f"grid {size} stays inside the frame", inside)
        covered = set()
        for x, y, tw, th in g:
            covered.add((x, y, x + tw, y + th))
        # Coverage: every pixel of a coarse lattice must fall in some tile.
        gaps = 0
        for py in range(0, size[1], 37):
            for px in range(0, size[0], 37):
                if not any(x <= px < x + tw and y <= py < y + th
                           for x, y, tw, th in g):
                    gaps += 1
        check(f"grid {size} leaves no gaps", gaps == 0, f"{gaps} uncovered")

    check("a small image is one tile", tile_grid((500, 400), 1456) ==
          [(0, 0, 500, 400)])
    check("tiles overlap by roughly OVERLAP",
          tile_grid((3000, 100), 1000)[1][0] == 750,
          str(tile_grid((3000, 100), 1000)))

    # --- coordinates map back correctly ---
    from PIL import Image
    img = Image.new("RGB", (3000, 2000), (128, 128, 128))
    seen = []

    def run_record(im):
        seen.append(im.size)
        # one detection at a fixed spot inside every tile
        return [{"label": "dent", "score": 0.9, "box": [10, 10, 40, 40]}]

    out = tiled_detect(img, run_record, model_size=728, full_pass=False)
    check("every tile was actually run", len(seen) == len(
        tile_grid((3000, 2000), 1456)), f"{len(seen)} runs")
    check("detections land at distinct places in the full frame",
          len({tuple(d["box"]) for d in out}) > 1, str(out[:2]))
    check("no detection escapes the image",
          all(d["box"][2] <= 3000 and d["box"][3] <= 2000 for d in out))

    # --- THE POINT OF THE MODULE: a seam-split scratch becomes ONE ---
    frag = [
        {"label": "scratch_scuff", "score": 0.7, "box": [100, 500, 240, 508]},
        {"label": "scratch_scuff", "score": 0.8, "box": [235, 501, 380, 509]},
        {"label": "scratch_scuff", "score": 0.6, "box": [372, 500, 500, 507]},
    ]
    m = merge_detections(frag)
    check("three fragments of one scratch merge into one", len(m) == 1,
          f"{len(m)} kept")
    check("the merged scratch spans the whole length",
          m and m[0]["box"][0] == 100 and m[0]["box"][2] == 500,
          str(m[0]["box"]) if m else "")
    check("the merged scratch keeps the best fragment's score",
          m and abs(m[0]["score"] - 0.8) < 1e-9)
    check("the merge records how many pieces it joined",
          m and m[0]["parts"] == 3)

    # --- and NMS alone would not have done it ---
    worst = max(_iou(frag[0]["box"], frag[1]["box"]),
                _iou(frag[1]["box"], frag[2]["box"]))
    check("plain NMS would have kept all three", worst < IOU_MERGE,
          f"max IoU between neighbours {worst:.3f}")

    # --- two PARALLEL scratches must stay two ---
    par = [
        {"label": "scratch_scuff", "score": 0.7, "box": [100, 500, 400, 508]},
        {"label": "scratch_scuff", "score": 0.7, "box": [100, 560, 400, 568]},
    ]
    check("parallel scratches are not joined", len(merge_detections(par)) == 2)

    # --- collinear but far apart stays two ---
    far = [
        {"label": "scratch_scuff", "score": 0.7, "box": [100, 500, 240, 508]},
        {"label": "scratch_scuff", "score": 0.7, "box": [900, 500, 1040, 508]},
    ]
    check("distant collinear scratches are not joined",
          len(merge_detections(far)) == 2)

    # --- duplicates from overlapping tiles collapse ---
    dup = [
        {"label": "dent", "score": 0.6, "box": [100, 100, 200, 200]},
        {"label": "dent", "score": 0.9, "box": [104, 98, 205, 203]},
    ]
    d = merge_detections(dup)
    check("a duplicate across an overlap collapses to one", len(d) == 1)
    check("the duplicate keeps the higher score",
          d and abs(d[0]["score"] - 0.9) < 1e-9)

    # --- dents are never stitched, however collinear ---
    dents = [
        {"label": "dent", "score": 0.7, "box": [100, 500, 240, 560]},
        {"label": "dent", "score": 0.7, "box": [242, 500, 380, 560]},
    ]
    check("adjacent dents stay separate", len(merge_detections(dents)) == 2)

    # --- different labels never merge ---
    mixed = [
        {"label": "dent", "score": 0.7, "box": [100, 100, 200, 200]},
        {"label": "scratch_scuff", "score": 0.7, "box": [101, 101, 201, 201]},
    ]
    check("different labels never merge", len(merge_detections(mixed)) == 2)

    # --- the full-frame pass survives to the output ---
    big = Image.new("RGB", (3000, 2000), (128, 128, 128))

    def run_big(im):
        if im.size == (3000, 2000):
            return [{"label": "structural", "score": 0.95,
                     "box": [200, 200, 2800, 1800]}]
        return []

    o = tiled_detect(big, run_big, model_size=728)
    check("damage larger than a tile survives via the full pass",
          any(d["label"] == "structural" and d["box"][2] > 2000 for d in o),
          str(o))

    # --- a tile-found and a full-found copy of one thing merge ---
    # The dent is fired by the FIRST tile only (which starts at 0,0) and by
    # the full frame, so both land on the same full-image box. Firing it in
    # every tile would be six different dents, not one seen twice.
    state = {"n": 0}

    def run_both(im):
        if im.size == (3000, 2000):
            return [{"label": "dent", "score": 0.5, "box": [100, 100, 300, 300]}]
        state["n"] += 1
        return ([{"label": "dent", "score": 0.9, "box": [100, 100, 300, 300]}]
                if state["n"] == 1 else [])

    o2 = tiled_detect(big, run_both, model_size=728)
    check("the same dent seen by a tile and the full frame reports once",
          len([d for d in o2 if d["label"] == "dent"]) == 1,
          str([d["box"] for d in o2]))

    # --- the tile-count guard actually bounds the work ---
    huge = Image.new("RGB", (12000, 9000))
    calls = []
    tiled_detect(huge, lambda im: calls.append(1) or [], model_size=728,
                 max_tiles=20)
    check("max_tiles bounds the number of crops", len(calls) <= 21,
          f"{len(calls)} crops")

    # --- resolution arithmetic: the claim in the docstring ---
    scratch_px, photo_w = 3.0, 4032.0
    at_full = scratch_px * 728 / photo_w
    at_tile = scratch_px * 728 / (728 * TILE_SCALE)
    check("a 3px scratch is sub-pixel in a full-frame pass", at_full < 1.0,
          f"{at_full:.2f}px")
    check("the same scratch survives in a tile", at_tile > 1.0,
          f"{at_tile:.2f}px")

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
