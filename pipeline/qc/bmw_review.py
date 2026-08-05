"""Resumable per-car review of the BMW wave, one candidate at a time.

The same shape as `audi_review.py` and for the same reason: 14 Audi verdicts
were lost because they lived only in conversation when the container rolled
back. This container has now rolled back five times in one session, so a
verdict is written to disk AND mirrored to Supabase in the same call, never
batched.

The difference from the Audi tool is the index. Audi used a positional U-number
into a fixed list, which works but breaks silently if the list is ever
reordered -- and a rollback did exactly that once. Here the key is the
Sketchfab uid, which is immutable and carries its own meaning, so a verdict
cannot migrate to a different car no matter what happens to file ordering. B-
numbers are still shown for readability but nothing is keyed on them.

`fetch` pulls four-view sheets from car-meshes/audit/bmw/<uid>.jpg. Nothing is
re-rendered; the render wave already paid for these and they survived two
container losses in the bucket.

Usage:
    bmw_review.py fetch --count 10 [--dir DIR] [--gate G6]
    bmw_review.py record --json '{"<uid>": ["KEEP", "reason"], ...}'
    bmw_review.py status
"""
import argparse, json, os, sys, urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QUEUE = os.path.join(REPO, "pipeline", "qc", "bmw_eye_queue.json")
VERD = os.path.join(REPO, "pipeline", "qc", "bmw_percar_verdicts.json")
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
SHEETS = "car-meshes/audit/bmw"
MIRROR = "car-meshes/audit/bmw_percar_verdicts.json"
VALID = ("KEEP", "SCRAP")


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


def queue():
    q = [r for r in json.load(open(QUEUE)) if not r.get("_scope")]
    idx = {r["uid"]: r for r in q}
    if len(idx) != len(q):
        sys.exit(f"FATAL: {len(q) - len(idx)} duplicate uids in the queue")
    return q, idx


def verdicts():
    return json.load(open(VERD)) if os.path.exists(VERD) else {}


def mirror(data):
    """Second copy, off local disk. A rollback takes the checkout, not the bucket."""
    rq = urllib.request.Request(f"{SB}/{MIRROR}",
        data=json.dumps(data, indent=1, ensure_ascii=False).encode(), method="POST",
        headers={**HDR, "Content-Type": "application/json", "x-upsert": "true"})
    return urllib.request.urlopen(rq, timeout=120).status


def cmd_fetch(a):
    q, _ = queue()
    done = verdicts()
    todo = [r for r in q if r["uid"] not in done
            and (not a.gate or r.get("auditGate") == a.gate)][:a.count]
    if not todo:
        sys.exit("nothing left to fetch for that filter")
    os.makedirs(a.dir, exist_ok=True)
    order = {r["uid"]: i for i, r in enumerate(q)}
    for r in todo:
        dst = os.path.join(a.dir, f"B{order[r['uid']] + 1:03d}_{r['uid']}.jpg")
        if not (os.path.exists(dst) and os.path.getsize(dst) > 5000):
            rq = urllib.request.Request(f"{SB}/{SHEETS}/{r['uid']}.jpg", headers=HDR)
            open(dst, "wb").write(urllib.request.urlopen(rq, timeout=300).read())
        print(f"{r['uid']}  {dst}\n     {r['name'][:66]}  |  {r['faces']:>8,} f  |  "
              f"cov {r['coverage']}  mats {r['bodyMaterials']}  {r['auditGate']}  by {r['author'][:18]}")


def cmd_record(a):
    _, idx = queue()
    done = verdicts()
    new = json.loads(a.json)
    for k, val in new.items():
        if k not in idx:
            sys.exit(f"FATAL: {k} is not a uid in the eye queue")
        if not (isinstance(val, list) and len(val) == 2 and val[0] in VALID):
            sys.exit(f"FATAL: {k} must be [KEEP|SCRAP, reason], got {val!r}")
    done.update(new)
    json.dump(done, open(VERD, "w"), indent=1, ensure_ascii=False)
    try:
        print(f"mirrored to Supabase: HTTP {mirror(done)}")
    except Exception as e:
        print(f"WARNING: mirror FAILED ({type(e).__name__}) — local copy only, "
              "this is exactly how the Audi verdicts were lost")
    k_ = sum(1 for v in done.values() if v[0] == "KEEP")
    print(f"{len(new)} recorded; {len(done)}/{len(idx)} judged, {k_} keep, "
          f"{len(done) - k_} scrap, {len(idx) - len(done)} left")


def cmd_status(a):
    q, idx = queue()
    done = verdicts()
    keeps = [(u, v[1]) for u, v in done.items() if v[0] == "KEEP"]
    print(f"{len(done)}/{len(idx)} judged — {len(keeps)} keep, "
          f"{len(done) - len(keeps)} scrap, {len(idx) - len(done)} left")
    for u, why in keeps:
        print(f"  KEEP {idx[u]['name'][:58]:58s} {why[:60]}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("--count", type=int, default=10)
    f.add_argument("--dir", default="/tmp/bmw_sheets"); f.add_argument("--gate", default="")
    f.set_defaults(fn=cmd_fetch)
    r = sub.add_parser("record"); r.add_argument("--json", required=True)
    r.set_defaults(fn=cmd_record)
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
