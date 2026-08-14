#!/usr/bin/env python3
"""validate_glass_probe.py — the re-validation CLAUDE.md requires before any
glass_probe change ships.

Two ground-truth sets, because glass_probe answers two separate questions and a
change to one can silently move the other:

  PORSCHE_GLASS.json      107 cars, glazing verdicts settled by magenta-backlight
                          renders and 3x sheet inspection. Guards the GLAZING
                          verdict, which is a hard scrap under the owner's ruling
                          -- a regression here culls good cars.
  retro_alpha_shell.json    5 live cars confirmed as global-alpha shells. Guards
                          `alpha_shell`, which build_car gate G3 treats as a hard
                          fail.

Run it BEFORE and AFTER a change and diff the two scores. "I did not touch that
code path" is not evidence; this project has been burned by exactly that.

Usage:
  validate_glass_probe.py [--stage staging/porsche] [--out /tmp/before.json]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import glass_probe as G                                   # noqa: E402


def porsche(stage, limit=None):
    truth = json.load(open(os.path.join(HERE, "PORSCHE_GLASS.json")))
    if limit:
        truth = truth[:limit]
    rows, agree, unread = [], 0, 0
    for i, t in enumerate(truth, 1):
        uid, want = t["uid"], t["verdict"]
        try:
            r = G.probe(uid, stage=stage)
            got = r.get("verdict")
        except Exception as e:
            got = f"ERROR:{type(e).__name__}"
            unread += 1
        # "ambiguous" is NEVER a fail (owner ruling): it routes to the eye, so
        # scoring it as a miss would push the probe toward culling good cars.
        ok = (got == want) or got == "ambiguous"
        agree += bool(ok)
        rows.append({"uid": uid, "name": t.get("name", ""), "want": want, "got": got, "ok": ok})
        if i % 20 == 0:
            print(f"  ...{i}/{len(truth)}", flush=True)
    return {"n": len(truth), "agree": agree, "unreadable": unread, "rows": rows}


def alpha_shell():
    truth = json.load(open(os.path.join(HERE, "retro_alpha_shell.json")))
    rows, caught = [], 0
    for t in truth:
        # these are LIVE cars; probe the published desktop GLB by URL
        aid = t["assetId"]
        url = t.get("desktopGlbUrl")
        if not url:
            cat = json.load(open(os.path.join(
                os.path.dirname(os.path.dirname(HERE)), "platform", "catalogue",
                "catalogue.v2.json")))
            e = next((x for x in cat if x["assetId"] == aid), None)
            url = e.get("desktopGlbUrl") if e else None
        if not url:
            rows.append({"assetId": aid, "flagged": None, "note": "no url"})
            continue
        try:
            r = G.probe(aid, url=url)
            f = bool(r.get("alpha_shell"))
        except Exception as ex:
            rows.append({"assetId": aid, "flagged": None, "note": f"{type(ex).__name__}"})
            continue
        caught += f
        rows.append({"assetId": aid, "flagged": f,
                     "body_transparent": r.get("body_transparent")})
    return {"n": len(truth), "caught": caught, "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="staging/porsche")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-porsche", action="store_true")
    a = ap.parse_args()

    res = {}
    if not a.skip_porsche:
        print("PORSCHE glazing ground truth:", flush=True)
        res["porsche"] = porsche(a.stage, a.limit or None)
        p = res["porsche"]
        print(f"  GLAZING {p['agree']}/{p['n']}  (unreadable {p['unreadable']})", flush=True)
    print("ALPHA-SHELL ground truth:", flush=True)
    res["alpha_shell"] = alpha_shell()
    s = res["alpha_shell"]
    print(f"  ALPHA_SHELL caught {s['caught']}/{s['n']}", flush=True)
    json.dump(res, open(a.out, "w"), indent=1)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
