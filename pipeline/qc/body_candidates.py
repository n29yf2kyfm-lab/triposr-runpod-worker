"""Generate body-paint CANDIDATE GROUPS by colour cluster rather than by name.

Ripped car models overwhelmingly assign one flat base colour to every painted
panel and split them across many materials (Paint2..Paint8, chassis.1..4). Name
matching misses the siblings — that is exactly why genesis-g70 recoloured only
6 of its 8 Paint materials and failed the audit at dist=0.067. Clustering on the
exact baseColorFactor catches the whole panel set, and the cluster's total area
share is a measurable quantity rather than a guess.
"""
import json, os, sys

D = os.path.dirname(os.path.abspath(__file__))
mats = json.load(open(f"{D}/MATS.json"))

EXC_TOK = ('glass', 'window', 'windscreen', 'vitre', 'tyre', 'tire', 'wheel', 'rim',
           'brake', 'caliper', 'disc', 'interior', 'seat', 'dash', 'carpet',
           'steering', 'leather', 'fabric', 'engine', 'motor')

def cluster(aid):
    ms = mats[aid]["materials"]
    groups = {}
    import re as _re
    def toks(n):
        return set(t.lower() for t in _re.findall(r"[A-Za-z]+", _re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", n)))
    for m in ms:
        if m["tex"]:
            continue                       # a textured panel can't take a flat respray
        key = tuple(m["rgb"])
        g = groups.setdefault(key, {"rgb": list(key), "pct": 0.0, "names": [],
                                    "blend": 0, "opaque": 0})
        g["pct"] += m["pct"]
        g["names"].append(m["name"])
        g["blend" if m["alphaMode"] != "OPAQUE" or m["alpha"] < 0.95 else "opaque"] += 1
    out = []
    for g in groups.values():
        # token-aware: substring matching fires 'rim' inside 'primary'
        tk = set().union(*[toks(n) for n in g["names"]])
        g["hits_excluded"] = sorted(tk & set(EXC_TOK))
        g["n"] = len(g["names"])
        out.append(g)
    return sorted(out, key=lambda g: -g["pct"])

if __name__ == "__main__":
    sel = sys.argv[1:] or sorted(mats)
    for aid in sel:
        d = mats[aid]
        print("=" * 76)
        print(f"{aid}  | current={d['current']} | audit={d['audit']} {d['dist']}")
        for g in cluster(aid)[:6]:
            flag = ("  EXCL:" + ",".join(g["hits_excluded"])) if g["hits_excluded"] else ""
            print(f"  {g['pct']:6.2f}%  n={g['n']:3d} rgb={g['rgb']} "
                  f"blend={g['blend']}{flag}")
            print(f"           {', '.join(g['names'][:9])}{' …' if g['n'] > 9 else ''}")
