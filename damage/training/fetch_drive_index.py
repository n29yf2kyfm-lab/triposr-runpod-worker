"""Download a Drive corpus from its own index file, by file id.

gdown's --folder walker is not reliable at this size: on this dataset it
crashed partway with a KeyError('content-type') — a known failure when Google
returns an interstitial instead of the file — and left 37 categories in a state
where several had none of their declared archives and the thinnest classes were
the emptiest. crack_hairline had 0 of 11, alloy_scratch 0 of 6, paint_rust 1 of
12. Those are precisely the faint-damage classes worth having.

The folder happens to ship CAR_DAMAGE_FULL_INDEX.json, which lists every
archive with its file id. Fetching by id one at a time is slower than a folder
walk but it is RESUMABLE and VERIFIABLE: each file is checked for existence and
plausible size before being skipped, a failure affects one archive rather than
aborting the run, and the index gives an expected count to check the result
against. Re-running tops up whatever is missing.

    python fetch_drive_index.py --index CAR_DAMAGE_FULL_INDEX.json --out drive_raw
    python fetch_drive_index.py --index ... --out ... --only scratch_faint,paint_rust
"""
import argparse
import json
import os
import time


def declared(index_path):
    """[(category, name, file_id, size_mb)] from either index layout."""
    with open(index_path) as f:
        d = json.load(f)
    cats = d.get("categories") or {}
    rows = []
    if isinstance(cats, dict):
        for cat, files in cats.items():
            for fl in (files or []):
                if isinstance(fl, dict) and fl.get("file_id"):
                    rows.append((cat, fl.get("name") or fl["file_id"],
                                 fl["file_id"], float(fl.get("size_mb") or 0)))
    return rows


def already_have(path, size_mb):
    """True when the file looks complete.

    Size is checked, not just existence: an aborted download leaves a truncated
    or zero-byte file behind, and skipping those is how a 'resumed' run quietly
    keeps a corrupt archive. A 10% tolerance covers the index rounding its
    megabytes.
    """
    if not os.path.exists(path):
        return False
    have = os.path.getsize(path)
    if have == 0:
        return False
    if size_mb > 0 and have < size_mb * 1024 * 1024 * 0.90:
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default=None,
                    help="comma-separated categories to fetch")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = declared(args.index)
    if args.only:
        want = {c.strip() for c in args.only.split(",")}
        rows = [r for r in rows if r[0] in want]

    by_cat = {}
    for cat, name, fid, mb in rows:
        by_cat.setdefault(cat, []).append((name, fid, mb))
    print(f"index declares {len(rows)} archives across {len(by_cat)} categories")

    missing = []
    for cat, files in sorted(by_cat.items()):
        d = os.path.join(args.out, cat)
        gone = [(n, i, m) for n, i, m in files
                if not already_have(os.path.join(d, n), m)]
        if gone:
            missing.append((cat, gone))
        print(f"  {cat:24s} have {len(files)-len(gone):>3}/{len(files):<3}"
              + ("" if not gone else f"  missing {len(gone)}"))
    total_missing = sum(len(g) for _, g in missing)
    print(f"\n{total_missing} archives to fetch")
    if args.dry_run or not total_missing:
        return

    import gdown
    ok = fail = 0
    for cat, files in missing:
        d = os.path.join(args.out, cat)
        os.makedirs(d, exist_ok=True)
        for name, fid, mb in files:
            dst = os.path.join(d, name)
            for attempt in range(args.retries):
                try:
                    gdown.download(id=fid, output=dst, quiet=True)
                    if already_have(dst, mb):
                        ok += 1
                        break
                except Exception as e:
                    if attempt == args.retries - 1:
                        print(f"    FAILED {cat}/{name}: {type(e).__name__}")
                time.sleep(2 * (attempt + 1))
            else:
                fail += 1
            if (ok + fail) % 25 == 0:
                print(f"    {ok} ok, {fail} failed, "
                      f"{total_missing-ok-fail} left")
    print(f"\nfetched {ok}, failed {fail}")


if __name__ == "__main__":
    main()
