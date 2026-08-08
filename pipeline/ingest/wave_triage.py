#!/usr/bin/env python3
"""wave_triage.py — turn `gpu_wave.py` render logs into the triage JSON that
`pipeline/qc/wave_review_page.py` consumes.

`gpu_wave` prints one line per finished car:

    03:07:33 [27/38] SHEET mats=1 cov=0.173 OK  2004 - 2009 Seat Toledo (5P)

and nothing else durable — the material figures never reach a file. Reading them
back out of the log is therefore the only way to know which cars split cleanly,
and doing it by hand is how the wrong number ends up in front of the owner.

The subtlety that makes this worth a script: **the index in `[27/38]` is an
offset into the manifest that run was given, not a global id.** A wave rendered
in two passes — a main run plus a top-up against a corrected manifest — has two
different index spaces, and joining a top-up log to the original manifest
silently mislabels every car. So each (log, manifest) pair is resolved
separately and merged on uid afterwards, with the name checked as a guard.

Names in the log are truncated for long titles, so the guard is a prefix
comparison rather than equality.

Usage:
    wave_triage.py --pair LOG:MANIFEST [--pair LOG2:MANIFEST2 ...] \
        --out triage.json
"""
import argparse, json, re, sys

LINE = re.compile(r"\[(\d+)/(\d+)\] SHEET mats=(\d+) cov=([\d.]+)\s+(OK|split)\s+(.*?)\s*$")


def resolve(log_path, manifest_path):
    man = json.load(open(manifest_path))
    out, bad = {}, []
    for line in open(log_path, errors="replace").read().splitlines():
        m = LINE.search(line)
        if not m:
            continue
        i, total, mats, cov, status, name = m.groups()
        i, total = int(i), int(total)
        if total != len(man):
            # The log was produced against a different manifest than the one
            # handed in. Joining them would mislabel every row, so refuse.
            bad.append(f"{log_path}: log says /{total}, manifest has {len(man)}")
            break
        if not 1 <= i <= len(man):
            bad.append(f"{log_path}: index {i} out of range")
            continue
        e = man[i - 1]
        if not e["name"].startswith(name[:28]):
            bad.append(f"{log_path}: row {i} name mismatch — log {name!r} vs manifest {e['name']!r}")
            continue
        out[e["uid"]] = {
            "uid": e["uid"], "name": e["name"], "faces": e.get("faces"),
            "author": e.get("author"), "licence": e.get("licence"), "i": i,
            "mats": int(mats), "cov": float(cov),
            "klass": "clean" if status == "OK" else "suspect",
        }
    return out, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", action="append", required=True,
                    metavar="LOG:MANIFEST",
                    help="repeatable; each render pass with the manifest it used")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    merged, problems = {}, []
    for pair in a.pair:
        log, _, man = pair.rpartition(":")
        if not log or not man:
            sys.exit(f"--pair wants LOG:MANIFEST, got {pair!r}")
        rows, bad = resolve(log, man)
        problems += bad
        # Later passes win: a top-up re-render is the more recent measurement.
        merged.update(rows)
        print(f"  {log}  ->  {len(rows)} rows")

    for p in problems:
        print("  WARNING " + p, file=sys.stderr)

    rows = sorted(merged.values(), key=lambda r: (r["klass"] != "clean", r["cov"]))
    json.dump(rows, open(a.out, "w"), indent=1)
    clean = sum(1 for r in rows if r["klass"] == "clean")
    print(f"{len(rows)} cars — {clean} clean / {len(rows) - clean} suspect -> {a.out}")
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
