"""Resumable per-car review of the Audi wave, one candidate at a time.

Two jobs, both about not losing work:

`fetch` pulls the four-view sheets for the next N unjudged candidates out of
`car-meshes/audit/audi/<uid>.jpg` so they can be looked at. Nothing is
re-rendered -- all 501 sheets are already in the bucket, which is the only
reason a rollback has not made this wave unrepeatable.

`record` writes verdicts and mirrors them to Supabase in the same call. This
exists because 14 judged verdicts were lost: they were only ever held in
conversation, the container rolled back, and there was nothing on disk or in
git to recover. Re-judging them means looking at 14 cars again. So a verdict is
persisted the moment it is made, to two places, and never batched up.

The U-index is positional: U<n> is `audi_unique129.json[n-1]`. A rollback has
broken an ordering like this before and silently pinned verdicts to the wrong
cars, so every call asserts the surviving verdicts still describe the entries
they point at (U001 at 539,297 faces, U002 at 538,105) and refuses to run if
they do not.

Usage:
    audi_review.py fetch --count 12 [--dir DIR]
    audi_review.py record --json '{"U003": ["SCRAP", "reason"], ...}'
    audi_review.py status
"""
import argparse, json, os, sys, urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UNIQ = os.path.join(REPO, "pipeline", "qc", "audi_unique129.json")
VERD = os.path.join(REPO, "pipeline", "qc", "audi_percar_verdicts.json")
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
SHEETS = "car-meshes/audit/audi"
MIRROR = "car-meshes/audit/audi_percar_verdicts.json"
VALID = ("KEEP", "SCRAP")
# the two surviving verdicts whose faces counts pin the positional index
ANCHORS = {"U001": 539297, "U002": 538105}


def load_env(path="/root/.alam3d_env"):
    try:
        body = open(path).read()
    except OSError:
        return
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:].lstrip() if line.startswith("export ") else line
        n, sep, v = line.partition("=")
        if sep and not os.environ.get(n.strip()):
            os.environ[n.strip()] = v.strip().strip("'\"")


load_env()
KEY = os.environ.get("SB_KEY") or sys.exit("FATAL: SB_KEY not set")
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}


def index():
    uniq = json.load(open(UNIQ))
    idx = {f"U{i + 1:03d}": e for i, e in enumerate(uniq)}
    for k, faces in ANCHORS.items():
        got = idx.get(k, {}).get("faces")
        if got != faces:
            sys.exit(f"FATAL: index drift — {k} should be {faces} faces, is {got}. "
                     "Verdicts would pin to the wrong cars; refusing to run.")
    return idx


def verdicts():
    return json.load(open(VERD)) if os.path.exists(VERD) else {}


def mirror(data):
    """Second copy, off local disk. A rollback takes the checkout, not the bucket."""
    blob = json.dumps(data, indent=1, ensure_ascii=False).encode()
    rq = urllib.request.Request(f"{SB}/{MIRROR}", data=blob, method="POST",
        headers={**HDR, "Content-Type": "application/json", "x-upsert": "true"})
    return urllib.request.urlopen(rq, timeout=120).status


def cmd_fetch(a):
    idx, done = index(), verdicts()
    todo = [k for k in sorted(idx) if k not in done][:a.count]
    if not todo:
        sys.exit("nothing left to fetch — every candidate is judged")
    os.makedirs(a.dir, exist_ok=True)
    for k in todo:
        e = idx[k]
        dst = os.path.join(a.dir, f"{k}_{e['uid']}.jpg")
        if not (os.path.exists(dst) and os.path.getsize(dst) > 5000):
            rq = urllib.request.Request(f"{SB}/{SHEETS}/{e['uid']}.jpg", headers=HDR)
            open(dst, "wb").write(urllib.request.urlopen(rq, timeout=300).read())
        print(f"{k}  {dst}\n     {e['name'][:70]}  |  {e['faces']:>7} f  |  "
              f"cov {e['coverage']}  mats {e['bodyMaterials']}  by {e['author']}")


def cmd_record(a):
    idx, done = index(), verdicts()
    new = json.loads(a.json)
    for k, val in new.items():
        if k not in idx:
            sys.exit(f"FATAL: {k} is not a candidate id")
        if not (isinstance(val, list) and len(val) == 2 and val[0] in VALID):
            sys.exit(f"FATAL: {k} must be [KEEP|SCRAP, reason], got {val!r}")
        if k in done and done[k] != val:
            print(f"  note: {k} overwrites {done[k][0]} -> {val[0]}")
    done.update(new)
    json.dump(done, open(VERD, "w"), indent=1, ensure_ascii=False)
    try:
        print(f"mirrored to Supabase: HTTP {mirror(done)}")
    except Exception as e:
        print(f"WARNING: mirror FAILED ({type(e).__name__}) — local copy only, "
              "this is exactly how the last 14 verdicts were lost")
    k_ = sum(1 for v in done.values() if v[0] == "KEEP")
    print(f"{len(new)} recorded; {len(done)}/{len(idx)} judged, {k_} keep, "
          f"{len(done) - k_} scrap, {len(idx) - len(done)} left")


def cmd_status(a):
    idx, done = index(), verdicts()
    k_ = [k for k, v in sorted(done.items()) if v[0] == "KEEP"]
    print(f"{len(done)}/{len(idx)} judged — {len(k_)} keep, {len(done) - len(k_)} scrap, "
          f"{len(idx) - len(done)} left")
    for k in k_:
        print(f"  KEEP {k}  {idx[k]['name'][:60]}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("--count", type=int, default=12)
    f.add_argument("--dir", default="/tmp/audi_sheets"); f.set_defaults(fn=cmd_fetch)
    r = sub.add_parser("record"); r.add_argument("--json", required=True)
    r.set_defaults(fn=cmd_record)
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
