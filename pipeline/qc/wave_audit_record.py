#!/usr/bin/env python3
"""Record Hyundai audit verdicts incrementally.

Two agents died today holding unpushed work, and this container has rolled back
four times in one session, so a verdict is written to disk the moment it is
made rather than accumulated in context and dumped at the end.

  record.py add <uid> <verdict> <reason> [<reason> ...]
  record.py build      -> pipeline/ingest/hyundai_audit_verdicts.json
  record.py todo       -> uids with a sheet but no verdict yet
"""
import json, os, sys

BASE = "/tmp/hyundai"
STORE = f"{BASE}/verdicts.json"
OUT = "pipeline/ingest/hyundai_audit_verdicts.json"
VALID = {"pass", "fail", "fail-rerender"}


def load():
    try:
        return json.load(open(STORE))
    except Exception:
        return {}


def rows():
    return {r["uid"]: r for r in json.load(open(f"{BASE}/manifest.filtered.json"))}


def main():
    cmd = sys.argv[1]
    d = load()
    if cmd == "add":
        uid, verdict, reasons = sys.argv[2], sys.argv[3], sys.argv[4:]
        assert verdict in VALID, f"bad verdict {verdict}"
        assert reasons, "a verdict with no reason is not a verdict"
        d[uid] = {"verdict": verdict, "reasons": reasons}
        json.dump(d, open(STORE, "w"), indent=1)
        print(f"{len(d)} recorded")
    elif cmd == "todo":
        have = {f[:-4] for f in os.listdir(f"{BASE}/sheets") if f.endswith(".jpg")}
        left = sorted(have - set(d))
        r = rows()
        print(f"{len(d)} done, {len(left)} to audit")
        for u in left:
            print(f"  {u} {r.get(u,{}).get('name','?')[:60]}")
    elif cmd == "build":
        r = rows()
        out = [{"uid": u, "name": r.get(u, {}).get("name", ""),
                "verdict": v["verdict"], "reasons": v["reasons"]}
               for u, v in sorted(d.items(), key=lambda kv: r.get(kv[0], {}).get("name", "").lower())]
        json.dump(out, open(OUT, "w"), indent=1)
        tally = {}
        for x in out:
            tally[x["verdict"]] = tally.get(x["verdict"], 0) + 1
        print(f"wrote {OUT}: {len(out)} rows  {tally}")


if __name__ == "__main__":
    main()
