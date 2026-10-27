"""gold.py: answers checked by hand, mixed into the agents' sheets.

An agent cannot tell a checked item from the others on its sheet. When it
answers one wrongly the tool refuses the answer, says what the right one is
and why, and tells it to look again at the rest of that sheet: the agent
learns the rule from its own mistake while it works, not after. Every answer
on a checked item is logged, so each batch has a score (check.py), and a
batch that missed one has its sheets looked at again.

A checked answer holds only for what was checked: a build's answer for that
build (its built_at), a photo's for that photo (its fingerprint). After a
rebuild or a new photo the item is left out until it is checked again.

    python3 gold.py add build KEY ok|bad ["fault,fault"] "why"
    python3 gold.py add side KEY left|right "why"
    python3 gold.py add paint KEY FAMILY "why"
    python3 gold.py list            # every checked item, and whether it still holds
    python3 gold.py score           # each batch's answers on checked items
"""
import json
import os
import random
import sys

import paths

KINDS = ("build", "side", "paint")


def gold_path():
    return os.environ.get("F1K_GOLD") or os.path.join(paths.REVIEW, "gold.json")


def load():
    g = paths.load(gold_path())
    return {k: g.get(k) or {} for k in KINDS}


def _holds(kind, key, item, rows=None):
    """Whether a checked answer is still about what is there now."""
    if kind == "build":
        rows = rows if rows is not None else paths.rows()[0]
        r = rows.get(key) or {}
        return bool(item.get("built_at")) and r.get("built_at") == item["built_at"] and r.get("status") in ("built", "standin")
    return bool(item.get("photo_sha")) and paths.sha(paths.photo(key)) == item["photo_sha"]


def active(kind, rows=None):
    g = load()[kind]
    rows = rows if rows is not None or kind != "build" else paths.rows()[0]
    return {k: v for k, v in g.items() if _holds(kind, k, v, rows)}


def pick(kind, n, avoid=(), seed=None):
    """N checked items not among AVOID, the least used first (spread over the batches)."""
    use = paths.load(paths.f("gold_usage.json"))
    pool = [k for k in active(kind) if k not in set(avoid)]
    rnd = random.Random(seed)
    rnd.shuffle(pool)
    pool.sort(key=lambda k: use.get(f"{kind}:{k}", 0))
    got = pool[:n]
    with paths.lock("gold_usage"):
        use = paths.load(paths.f("gold_usage.json"))
        for k in got:
            use[f"{kind}:{k}"] = use.get(f"{kind}:{k}", 0) + 1
        paths.save(paths.f("gold_usage.json"), use)
    return got


def judge(kind, key, answer, faults=()):
    """None when KEY is no checked item of KIND (or its check no longer
    holds); else {"right", "expected", "why"}. A bad build is answered right
    when it is called bad with at least one of the checked faults."""
    item = load()[kind].get(key)
    if not item or not _holds(kind, key, item):
        return None
    if kind == "build":
        right = answer == item["verdict"] and (answer == "ok" or bool(set(faults) & set(item.get("faults") or [])))
        exp = item["verdict"] + (f" ({', '.join(item['faults'])})" if item.get("faults") else "")
    else:
        right = answer == item["answer"]
        exp = item["answer"]
    return {"right": right, "expected": exp, "why": item.get("why", "")}


def log(kind, key, answer, right):
    """Every answer on a checked item, with the batches whose sheets carried it."""
    man = paths.load(paths.f("sheets", "manifest.json"))
    batches = sorted({m.get("batch") or "?" for m in man.values() if key in (m.get("gold") or [])}) or ["?"]
    os.makedirs(paths.home(), exist_ok=True)
    with paths.lock("gold_score"):
        with open(paths.f("gold_score.jsonl"), "a") as fh:
            fh.write(json.dumps({"kind": kind, "key": key, "answer": answer, "right": right,
                                 "batches": batches, "at": paths.now()}) + "\n")


def note_sheet(out, batch, keys, gold_keys):
    with paths.lock("manifest"):
        man = paths.load(paths.f("sheets", "manifest.json"))
        man[os.path.abspath(out)] = {"batch": batch, "keys": list(keys), "gold": list(gold_keys), "at": paths.now()}
        paths.save(paths.f("sheets", "manifest.json"), man)


def mix(keys, kind, n, out, batch):
    """KEYS with N checked items of KIND put among them, at places fixed by
    the sheet's name (the same sheet made again comes out the same)."""
    gold_keys = pick(kind, n, avoid=keys, seed=out) if n else []
    rnd = random.Random(out)
    keys = list(keys)
    for g in gold_keys:
        keys.insert(rnd.randint(0, len(keys)), g)
    note_sheet(out, batch, keys, gold_keys)
    return keys


def scores():
    """{batch: {"answered", "missed", "misses": [...]}} from the log; an item
    answered again after a miss still counts as the miss it was."""
    out = {}
    if not os.path.exists(paths.f("gold_score.jsonl")):
        return out
    seen = set()
    for line in open(paths.f("gold_score.jsonl")):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        for b in e.get("batches") or ["?"]:
            first = (b, e["kind"], e["key"]) not in seen
            seen.add((b, e["kind"], e["key"]))
            if not first:
                continue
            s = out.setdefault(b, {"answered": 0, "missed": 0, "misses": []})
            s["answered"] += 1
            if not e["right"]:
                s["missed"] += 1
                s["misses"].append(f"{e['kind']} {e['key']}: said {e['answer']}")
    return out


def add(kind, key, answer, why, faults=()):
    if kind not in KINDS:
        raise SystemExit(f"kind is one of {KINDS}")
    g = paths.load(gold_path())
    g.setdefault(kind, {})
    if kind == "build":
        r = paths.rows()[0].get(key)
        if not r or r.get("status") not in ("built", "standin"):
            raise SystemExit(f"{key} has no build to check")
        if not r.get("built_at"):
            raise SystemExit(f"{key}'s build has no built_at: build it with fleet.py first")
        if answer not in ("ok", "bad") or (answer == "bad") != bool(faults):
            raise SystemExit("a checked build is ok with no faults, or bad with at least one")
        g[kind][key] = {"verdict": answer, "faults": list(faults), "built_at": r["built_at"], "why": why, "checked": paths.now()}
    else:
        sha = paths.sha(paths.photo(key))
        if not sha:
            raise SystemExit(f"{key} has no photo")
        g[kind][key] = {"answer": answer, "photo_sha": sha, "why": why, "checked": paths.now()}
    paths.save(gold_path(), g)
    print(f"checked {kind} {key} = {answer}")


def main():
    a = sys.argv[1:]
    if a[:1] == ["add"] and len(a) >= 4:
        kind, key, ans = a[1], a[2], a[3]
        if kind == "build":
            faults = [x.strip() for x in (a[4] if ans == "bad" and len(a) > 5 else "").split(",") if x.strip()]
            why = a[5] if ans == "bad" and len(a) > 5 else (a[4] if len(a) > 4 else "")
        else:
            faults, why = [], a[4] if len(a) > 4 else ""
        return add(kind, key, ans, why, faults)
    if a[:1] == ["list"]:
        g, rows = load(), paths.rows()[0]
        for kind in KINDS:
            for k, v in sorted(g[kind].items()):
                print(f"{kind:5s} {k:34s} {v.get('verdict') or v.get('answer'):6s} "
                      f"{'holds' if _holds(kind, k, v, rows) else 'NOT CURRENT (rebuilt or new photo: check again)'}")
        return
    if a[:1] == ["score"]:
        return print(json.dumps(scores(), indent=1))
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
