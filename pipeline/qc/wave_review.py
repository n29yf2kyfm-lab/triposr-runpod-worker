#!/usr/bin/env python3
"""wave_review.py — resumable per-car eye review for any sourcing wave.

The generalisation of `bmw_review.py` / `audi_review.py`, which were the same
tool copied twice. Four waves are now queued for review (Skoda, SEAT, MINI, Kia)
and copying it twice more would guarantee they drift apart.

Everything that made the BMW tool safe is kept:

  * **Keyed on the Sketchfab uid, never a position.** The Audi tool used a
    positional U-number, which breaks silently if the list is reordered — and a
    rollback did exactly that once, migrating verdicts onto the wrong cars. A uid
    is immutable, so a verdict cannot move.
  * **Written to disk AND mirrored to Supabase in the same call, never batched.**
    14 Audi verdicts were lost because they lived only in the conversation when
    the container rolled back. This container has rolled back repeatedly.
  * **Nothing is re-rendered.** Sheets come from the bucket the render wave
    already paid for.

Queue is the wave's triage JSON (`pipeline/ingest/<marque>_triage.json`);
verdicts land in `pipeline/qc/<marque>_percar_verdicts.json`.

Usage:
    wave_review.py --marque skoda fetch --count 8 [--klass clean|suspect]
    wave_review.py --marque skoda record --file verdicts.json
    wave_review.py --marque skoda status [--keeps]
"""
import argparse, json, os, sys, urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
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


def paths(marque):
    m = marque.lower()
    return (os.path.join(REPO, "pipeline", "ingest", f"{m}_triage.json"),
            os.path.join(REPO, "pipeline", "qc", f"{m}_percar_verdicts.json"),
            f"car-meshes/audit/{m}",
            f"car-meshes/audit/{m}_percar_verdicts.json")


def queue(marque):
    qp, _, _, _ = paths(marque)
    q = json.load(open(qp))
    idx = {r["uid"]: r for r in q}
    if len(idx) != len(q):
        sys.exit(f"FATAL: {len(q) - len(idx)} duplicate uids in {qp}")
    return q, idx


def verdicts(marque):
    _, vp, _, _ = paths(marque)
    return json.load(open(vp)) if os.path.exists(vp) else {}


def mirror(marque, data):
    """Second copy, off local disk. A rollback takes the checkout, not the bucket."""
    _, _, _, dst = paths(marque)
    rq = urllib.request.Request(f"{SB}/{dst}",
        data=json.dumps(data, indent=1, ensure_ascii=False).encode(), method="POST",
        headers={**HDR, "Content-Type": "application/json", "x-upsert": "true"})
    return urllib.request.urlopen(rq, timeout=120).status


def cmd_fetch(a):
    q, _ = queue(a.marque)
    done = verdicts(a.marque)
    _, _, sheets, _ = paths(a.marque)
    todo = [r for r in q if r["uid"] not in done
            and (not a.klass or r.get("klass") == a.klass)][:a.count]
    if not todo:
        sys.exit("nothing left to fetch for that filter")
    d = a.dir or f"/tmp/{a.marque.lower()}_review"
    os.makedirs(d, exist_ok=True)
    order = {r["uid"]: i for i, r in enumerate(q)}
    for r in todo:
        dst = os.path.join(d, f"N{order[r['uid']] + 1:03d}_{r['uid']}.jpg")
        if not (os.path.exists(dst) and os.path.getsize(dst) > 5000):
            rq = urllib.request.Request(f"{SB}/{sheets}/{r['uid']}.jpg", headers=HDR)
            open(dst, "wb").write(urllib.request.urlopen(rq, timeout=300).read())
        print(f"{r['uid']}  {dst}\n     {r['name'][:66]}  |  {(r.get('faces') or 0):>8,} f  |  "
              f"cov {r['cov']}  mats {r['mats']}  {r['klass']}  by {(r.get('author') or '')[:18]}")


def cmd_record(a):
    _, idx = queue(a.marque)
    done = verdicts(a.marque)
    new = json.load(open(a.file)) if a.file else json.loads(a.json)
    for k, val in new.items():
        if k not in idx:
            sys.exit(f"FATAL: {k} is not a uid in the {a.marque} queue")
        if not (isinstance(val, list) and len(val) == 2 and val[0] in VALID):
            sys.exit(f"FATAL: {k} must be [KEEP|SCRAP, reason], got {val!r}")
    done.update(new)
    _, vp, _, _ = paths(a.marque)
    json.dump(done, open(vp, "w"), indent=1, ensure_ascii=False)
    try:
        print(f"mirrored to Supabase: HTTP {mirror(a.marque, done)}")
    except Exception as e:
        print(f"WARNING: mirror FAILED ({type(e).__name__}) — local copy only, "
              "this is exactly how the Audi verdicts were lost")
    k_ = sum(1 for v in done.values() if v[0] == "KEEP")
    print(f"{len(new)} recorded; {len(done)}/{len(idx)} judged, {k_} keep, "
          f"{len(done) - k_} scrap, {len(idx) - len(done)} left")


def cmd_status(a):
    q, idx = queue(a.marque)
    done = verdicts(a.marque)
    keeps = [(u, v[1]) for u, v in done.items() if v[0] == "KEEP"]
    print(f"{a.marque}: {len(done)}/{len(idx)} judged — {len(keeps)} keep, "
          f"{len(done) - len(keeps)} scrap, {len(idx) - len(done)} left")
    if a.keeps:
        for u, w in keeps:
            print(f"  KEEP {idx[u]['name'][:52]:52s} cov {idx[u]['cov']:<6} {w[:70]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--marque", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("--count", type=int, default=8)
    f.add_argument("--dir", default=""); f.add_argument("--klass", default="")
    f.set_defaults(fn=cmd_fetch)
    r = sub.add_parser("record")
    r.add_argument("--file", default=""); r.add_argument("--json", default="")
    r.set_defaults(fn=cmd_record)
    s = sub.add_parser("status"); s.add_argument("--keeps", action="store_true")
    s.set_defaults(fn=cmd_status)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
