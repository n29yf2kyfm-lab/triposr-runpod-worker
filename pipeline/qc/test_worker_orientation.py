#!/usr/bin/env python3
"""test_worker_orientation.py — the render worker's auto-upright, tested.

This logic had no test and has produced two defect classes the owner caught by
eye on shipped sheets. Both are documented in CLAUDE.md as understood-but-unfixed.

  BUG A — THE ROUNDING TIE (Mazda wave). After the first rotation the worker
  asks "did the car land on its side?" with `argmin(ext2) != 2`, i.e. "is the
  vertical extent NOT the smallest". Mazda 2 (DY) measures X 201.748,
  Y 411.622, Z 202.624 there — X and Z differ by 0.4% — so argmin picks X, the
  test says "on its side", and it ROLLS A CORRECT CAR ONTO ITS SIDE.
  Deterministic; re-rendering cannot fix it.

  BUG B — THE UNREACHABLE FLIP. The 180-degree wheels-up check is nested inside
  the length-on-Z branch, so a horizontally-authored car — most of them — can
  never reach it. That is why the wheels-up Tucson rendered wheels-up.

WHAT THIS TEST ESTABLISHED — a NEGATIVE RESULT worth keeping: the inner roll
test CANNOT be made reliable from bounding-box extents alone, and **no candidate
rule scores 4/4**. (An earlier draft of this docstring claimed "never" passed
every case; the test disproved it — it misses the genuine on-side car. Corrected
here rather than quietly, because the number is the point.)

    current   roll if argmin(ext) != 2          2/4  breaks Mazda AND van
    margin    roll if ext_z > 1.1 * min(ext)    3/4  breaks van
    dominant  roll only if ext_z is the largest 3/4  misses a real on-side car
    never     never roll                        3/4  misses a real on-side car

So the choice is NOT by score, it is by the DIRECTION of the failure — the same
principle CLAUDE.md applies to `_trim_outlier_bbox` ("the movement is all in the
fail-open direction"):

  * `current` and `margin` fail DANGEROUSLY: they roll CORRECT cars onto their
    side and ship them. That is the Mazda defect the owner caught.
  * `dominant` and `never` fail SAFELY: they decline to auto-fix a genuinely
    on-side car — which ingest already rejects at the pose gate, and which
    `pose_fix` can now repair with real evidence (the TYRE material's height,
    something the worker does not have).

RECOMMENDATION: `never` — delete the inner roll and let ingest own pose. The
worker's own comment already concedes the direction: "ingest now uprights staged
GLBs, so an already-horizontal model is trusted as authored." `dominant` is the
conservative alternative if some auto-rescue is wanted.

NOT APPLIED to render/handler.py here: that image is shared with concurrent
waves and repinning it mid-flight silently invalidates their in-progress sheets
(documented, cost a 347-car wave once). Owner decision.

Usage: python3 pipeline/qc/test_worker_orientation.py
"""
import sys

# (name, extents AT THE ROLL TEST [x,y,z] with length on Y, should_roll, note)
CASES = [
    ("Mazda 2 (DY) 2003", [201.748, 411.622, 202.624], False,
     "REAL measured extents. X vs Z differ 0.4% — a tie is not evidence. "
     "The worker rolled it and shipped a sheet showing the floor pan."),
    ("normal saloon", [180.0, 450.0, 140.0], False,
     "height 140 clearly under width 180 — upright, no roll"),
    ("Sprinter-class van", [190.0, 520.0, 240.0], False,
     "height 240 RIGHTLY exceeds width 190. The worker's own comment names "
     "this case as the reason the outer gate was made conservative."),
    ("genuinely on its side", [60.0, 400.0, 200.0], True,
     "height 60 ended up on X (horizontal), width 200 on Z (vertical) — "
     "this is what a real on-side car looks like and a roll fixes it"),
]

RULES = {
    "current  (argmin != 2)": lambda e: min(range(3), key=lambda i: e[i]) != 2,
    "margin   (z > 1.1*min)": lambda e: e[2] > 1.10 * min(e),
    "dominant (z is largest)": lambda e: e[2] >= max(e),
    "never                  ": lambda e: False,
}


def main():
    print("BUG A — can any extent-only rule get all four cases right?\n")
    names = list(RULES)
    print(f"  {'case':24s} {'want':6s} " + " ".join(f"{n[:22]:>22s}" for n in names))
    score = {n: 0 for n in names}
    for cname, ext, want, note in CASES:
        cells = []
        for n in names:
            got = RULES[n](ext)
            ok = (got == want)
            score[n] += ok
            cells.append(f"{('OK' if ok else 'WRONG'):>22s}")
        print(f"  {cname:24s} {str(want):6s} " + " ".join(cells))
    print()
    for n in names:
        print(f"    {n}  {score[n]}/{len(CASES)}")

    best = max(score, key=lambda n: score[n])
    print(f"\n  best rule: '{best.strip()}' at {score[best]}/{len(CASES)}")
    if score[best] < len(CASES):
        print("  NOTE: no rule scores 4/4. Choose by FAILURE DIRECTION, not score — see docstring.")

    print("\nBUG B — is the wheels-up flip reachable for a normal car?\n")
    horiz = [4.6, 2.1, 1.6]          # length X, width Y, height Z — never stands on end
    stands_on_end = horiz[2] > 1.25 * max(horiz[0], horiz[1])
    print(f"  horizontally-authored car {horiz}")
    print(f"    stands_on_end = {stands_on_end}  -> flip check reachable = {stands_on_end}")
    print("    the wheels-up Tucson rendered wheels-up for exactly this reason")

    # The assertion is about the DIRECTION of each rule's failure, not its
    # score. A rule that rolls a correct car is a shipped defect; a rule that
    # declines to rescue an on-side car just defers to ingest.
    fails = 0
    dangerous = {"current  (argmin != 2)", "margin   (z > 1.1*min)"}
    for n in names:
        rolls_mazda = RULES[n](CASES[0][1])
        rolls_van = RULES[n](CASES[2][1])
        unsafe = rolls_mazda or rolls_van
        if unsafe and n.strip() not in {r.strip() for r in dangerous}:
            print(f"    UNEXPECTED: '{n.strip()}' rolls a correct car"); fails += 1
        if not unsafe and n.strip() in {r.strip() for r in dangerous}:
            print(f"    UNEXPECTED: '{n.strip()}' is safe after all"); fails += 1
    if stands_on_end:
        print("    UNEXPECTED: flip branch reachable — re-read handler.py"); fails += 1
    print(f"\n{'FAIL' if fails else 'PASS'}: findings reproduce as documented "
          f"(no rule is 4/4; 'dominant' and 'never' fail only in the safe direction)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
