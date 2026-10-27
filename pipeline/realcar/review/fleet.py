"""fleet.py: the 1,000-vehicle run, cars and vans through the car machine.

    python3 fleet.py build [--workers 3] [--class car|van] [--limit N]
    python3 fleet.py redo [--workers 3]      # again: the failed, redo.txt and the rebuild queue
    python3 fleet.py licence any|commercial  # the models a run may use, kept for every build of it

The run's models: "commercial" (the machine's own rule: only models that may
be used commercially) unless the run says "any" (each vehicle from its
closest model whatever its licence, the credit naming the licence: the
owner's choice for the private October 2026 report). It is kept in
F1K_HOME/run.json, so a redo builds as the run did: a redo that had dropped
it built 36 vehicles from other models than the run's (the Fiesta as a
stand-in, the 2025 Golf as the 2017 one).

Each target in targets.json is asked of glbmachine as its request, in the
colour of its photo (photo_paint.json). One line per target goes to
results.jsonl (a re-run skips those there): what the machine built (the
car's own catalogue model, or a stand-in and its donor), its generation's
years, what opens, its notes, how long, when (built_at), or why it could
not. The finished web file goes to pending/ for hero.mjs to picture, and the
big files are cleared: the car is built again on request.

The run stops starting new builds when the disk runs low (the rig cache is
pruned first), and every line is written whole, so a run can always be
resumed with "build" where it stopped.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import paths

DEADLINE = "120"
MIN_FREE = 1.5e9          # under this free, after pruning the rig cache, no new build is started


def free():
    return shutil.disk_usage(paths.home()).free


def prune_rigs(low=2.5e9, to=3.5e9):
    """The shared rig cache is kept (a request for a rigged model only
    finishes) while the disk has room: under LOW free, the oldest rigs go
    until TO is free."""
    if free() >= low:
        return
    root = os.path.join(paths.machine_home(), "rigs")
    if not os.path.isdir(root):
        return
    dirs = [os.path.join(root, a, n) for a in os.listdir(root) if os.path.isdir(os.path.join(root, a))
            for n in os.listdir(os.path.join(root, a)) if os.path.isdir(os.path.join(root, a, n))]
    for _, d in sorted((os.path.getmtime(d), d) for d in dirs):
        if free() >= to:
            break
        shutil.rmtree(d, ignore_errors=True)


def room():
    """Whether there is room for one more build."""
    prune_rigs()
    return free() >= MIN_FREE


_PAINT = {}


def _paints():
    if not _PAINT:
        _PAINT.update(paths.load(paths.f("photo_paint.json")))
    return _PAINT


# the words that ask the machine for a roof (make.py): "body" paints a model's
# contrasting roof the body's colour, "contrast" keeps a stand-in's donor's
ROOF_WORDS = {"body": ["body", "coloured", "roof"], "contrast": ["contrast", "roof"]}


def _roof_words(key):
    """A roof of a colour named by eye ("white": the Captur's) is asked in
    that colour's paint ("#eeefed roof")."""
    from paint_label import FAMILY
    r = (paths.load(paths.f("roof_label.json")).get(key) or {}).get("roof")
    return ROOF_WORDS.get(r) or ([FAMILY[r], "roof"] if r in FAMILY else [])


def _door_words(key):
    """The photo's door count, named by the build review ("a 5-door stand-in
    for the 3-door Mii"): asked of the machine ("3 door"), which picks a donor
    with as many or closes a five-door's rear doors up."""
    n = (paths.load(paths.f("doors_label.json")).get(key) or {}).get("doors")
    return [str(n), "door"] if n else []


def unasked(rows):
    """Built cars whose build did not ask for what is now known of their photo:
    a roof or a door count named after it was built (a label set while a run
    using older code was building it, whose queue entry that run then met)."""
    from paint_label import FAMILY
    rl, dl = paths.load(paths.f("roof_label.json")), paths.load(paths.f("doors_label.json"))
    out = {}
    for k, r in rows.items():
        if r.get("status") not in ("built", "standin") or not k.startswith(("car-", "van-")):
            continue
        want = (rl.get(k) or {}).get("roof")
        if want:
            asked = "body" if want == "body" else "contrast" if want == "contrast" else FAMILY.get(want)
            if r.get("roof") != asked:
                out[k] = f"its roof ({want}) not asked by its build"
        n = (dl.get(k) or {}).get("doors")
        if n and r.get("doors") != n:
            out[k] = f"its doors ({n}) not asked by its build"
    return out


def one(t):
    """One target's row, always: a fault in reading what the build left
    (a broken record, a failed copy) is that target's failure, never the
    run's."""
    try:
        try:
            return _one(t)
        except FileNotFoundError:
            # two targets built from one catalogue file (the Austin, Morris
            # and Rover Minis) share its folder: one cleared it as the other
            # copied. Built again, once, the folder its own
            time.sleep(5)
            return _one(t)
    except Exception as e:
        return {k: t.get(k) for k in ("key", "class", "rank", "genModel", "make", "model", "licensed", "request")} | \
            {"status": "failed", "error": f"the run's own step failed: {type(e).__name__}: {e}"[:300], "built_at": paths.now()}


def licence():
    """The run's models: "any" or "commercial" (F1K_HOME/run.json; commercial when unset)."""
    return (paths.load(paths.f("run.json")).get("licence") or "commercial")


def _one(t):
    env = dict(os.environ, GLBMACHINE_HOME=paths.machine_home(), GLBMACHINE_DEADLINE_S=DEADLINE, GLBMACHINE_ONLINE="1",
               GLBMACHINE_COMMERCIAL_ONLY="0" if licence() == "any" else "1")
    t0 = time.time()
    row = {k: t[k] for k in ("key", "class", "rank", "genModel", "make", "model", "licensed", "request")}
    if t.get("base_note"):
        row["base_note"] = t["base_note"]
    try:
        # the paint of its photo (photo_paint.py), so the build wears the colour the card shows beside it
        paint = (_paints().get(t["key"]) or {}).get("hex") if t["class"] in ("car", "van") else None
        if paint:
            row["paint"] = paint
        roof = _roof_words(t["key"]) if t["class"] in ("car", "van") else []
        if roof:
            row["roof"] = roof[0]
        doors = _door_words(t["key"]) if t["class"] in ("car", "van") else []
        if doors:
            row["doors"] = int(doors[0])
        p = subprocess.run([sys.executable, "pipeline/realcar/glbmachine.py", "car", *t["request"].split(),
                            *doors, *([paint] if paint else []), *roof],
                           cwd=paths.REPO, env=env, capture_output=True, text=True, timeout=900)
        ans = json.loads(p.stdout) if p.stdout.strip() else {"error": (p.stderr or "no answer")[-300:]}
    except subprocess.TimeoutExpired:
        ans = {"error": "took over 15 minutes"}
    except ValueError:
        ans = {"error": "unreadable answer: " + (p.stdout or "")[-200:]}
    row["seconds"] = round(time.time() - t0, 1)
    row["built_at"] = paths.now()
    if ans.get("error"):
        row.update(status="failed", error=ans["error"], match=ans.get("match"), catalogue_has=ans.get("catalogue_has"))
        return row
    glb = ans.get("glb")
    car = os.path.dirname(glb) if glb else None
    rec = paths.load(os.path.join(car, "record.json")) if car else {}
    item = (paths.load(os.path.join(car, "build.json")).get("item") or {}) if car else {}
    st = rec.get("standin") or {}
    fin = rec.get("finish") or {}
    row.update(status="standin" if item.get("standin_donor") else "built", title=ans.get("title"), notes=ans.get("notes"),
               asset=item.get("standin_donor") or rec.get("asset"), source=item.get("sourceTitle"),
               opens=fin.get("opens"), missing=rec.get("missing", fin.get("missing")), credit=(rec.get("credit") or {}),
               seconds_to_file=ans.get("seconds_to_file"), web_mb=round((rec.get("web_bytes") or 0) / 1e6, 1),
               # the generation the build stands for: a stand-in's car's, an own model's own
               years=(item.get("standin") or {}).get("years") or rec.get("years"))
    if fin.get("roof_in_paint"):
        row["roof_painted"] = fin["roof_in_paint"].get("share_of_footprint")
    if st:
        row["standin"] = {"target": st.get("target"), "large_change": st.get("large_change"),
                          "roof_from_photo": bool(st.get("roof")), "debadged": st.get("debadged")}
    if glb and os.path.exists(glb):
        # the shape checked from the file: wheels inside the body, nothing
        # lying away from the car (qa_glb.mjs)
        try:
            q = subprocess.run(["node", os.path.join(paths.REVIEW, "qa_glb.mjs"), glb], capture_output=True, text=True, timeout=120)
            row["qa"] = json.loads(q.stdout.strip().splitlines()[-1]).get("issues", [])
        except Exception as e:
            row["qa"] = [f"not checked: {type(e).__name__}"]
        pend = paths.f("pending")
        part = os.path.join(pend, row["key"] + ".part.glb")
        shutil.copy(glb, part)
        os.replace(part, os.path.join(pend, row["key"] + ".glb"))
        for f in (glb, os.path.join(car, "rig", "src.glb"), os.path.join(car, "rig", "src.donor.glb")):
            if os.path.exists(f):
                os.remove(f)
    if ans.get("index"):
        shutil.rmtree(os.path.dirname(ans["index"]), ignore_errors=True)
    return row


def _done(row):
    """A row written: its rebuild-queue entry, if any, is met."""
    if row.get("status") == "failed":
        return
    with paths.lock("needs_rebuild"):
        q = paths.load(paths.f("needs_rebuild.json"))
        if row["key"] in q and q[row["key"]]["at"] <= row["built_at"]:
            q.pop(row["key"])
            paths.save(paths.f("needs_rebuild.json"), q)


def build(workers=3, cls=None, limit=None):
    os.makedirs(paths.f("pending"), exist_ok=True)
    done, bad = paths.rows()
    if bad:
        print(f"{bad} broken line(s) in results.jsonl were read past: those targets are built again", flush=True)
    todo = [t for t in paths.load(paths.f("targets.json"), [])
            if t["class"] in ((cls,) if cls else ("car", "van")) and t["key"] not in done]
    todo = todo[:limit] if limit else todo
    print(len(todo), "to do", flush=True)
    n, stopped = 0, None
    with ThreadPoolExecutor(workers) as ex:
        running, queue = set(), list(todo)
        while queue or running:
            while queue and len(running) < workers and not stopped:
                if not room():
                    stopped = f"the disk is nearly full ({free() / 1e9:.1f} GB free): no new build started"
                    break
                running.add(ex.submit(one, queue.pop(0)))
            if not running:
                break
            fin, running = wait(running, return_when=FIRST_COMPLETED)
            for fut in fin:
                row = fut.result()
                try:
                    paths.append_row(row)
                except OSError as e:
                    stopped = f"results.jsonl could not be written ({e}): stopped"
                    queue.clear()
                    continue
                _done(row)
                n += 1
                print(f"{n:4d} {row['class']:5s} {row['rank']:4d} {row['genModel'][:30]:30s} {row['status']:8s} "
                      f"{row.get('seconds')}s {(row.get('error') or row.get('title') or '')[:60]}", flush=True)
    if stopped:
        print(f"STOPPED: {stopped}. Free space, then run 'fleet.py build' to go on where it stopped.", flush=True)
        raise SystemExit(3)
    print("build done", flush=True)


def redo():
    """Again: every failed vehicle, those in redo.txt and those on the
    rebuild queue (a new photo, colour or side) are taken out of the results,
    to be built again with a longer time limit (more models tried in turn)."""
    again = set(l.strip() for l in open(paths.f("redo.txt")) if l.strip()) if os.path.exists(paths.f("redo.txt")) else set()
    again |= set(paths.load(paths.f("needs_rebuild.json")))
    mh = paths.machine_home()
    refused = paths.load(os.path.join(mh, "rig_refused.json"))
    rows, _ = paths.rows()
    again |= set(unasked(rows))
    keep = []
    for r in rows.values():
        # a width up to 2.6 m is across the mirrors (a van's, or a big car's): not a broken shape
        bad_shape = [i for i in r.get("qa") or [] if not i.startswith("not checked")
                     and not ((m := re.match(r"body ([\d.]+) m wide", i)) and float(m.group(1)) <= 2.6)]
        if r["status"] == "standin" and bad_shape and r.get("asset"):
            # the donor made a broken car: as a donor only, later in line (still built as its own car)
            rv = re.search(r'VERSION = "([^"]+)"', open(os.path.join(paths.REALCAR, "rig.py")).read()).group(1)
            refused[r["asset"]] = {"why": "check: " + "; ".join(bad_shape[:2]), "rigger": rv, "at": time.strftime("%Y-%m-%d"),
                                   "missing": ["a sound shape as a stand-in (check)"]}
        if r["status"] == "failed" or r["key"] in again or (r["status"] == "standin" and bad_shape):
            again.add(r["key"])
        else:
            keep.append(json.dumps(r) + "\n")
    paths.save(os.path.join(mh, "rig_refused.json"), refused)
    res = paths.f("results.jsonl")
    if os.path.exists(res):
        shutil.copy(res, res + ".before_redo")
    with open(res + ".part", "w") as fh:
        fh.writelines(keep)
    os.replace(res + ".part", res)
    print(len(again), "to build again", flush=True)


def main():
    global DEADLINE
    a = sys.argv[1:]
    w = int(a[a.index("--workers") + 1]) if "--workers" in a else 3
    if a[:1] == ["licence"] and len(a) == 2 and a[1] in ("any", "commercial"):
        run = paths.load(paths.f("run.json"))
        run.update(licence=a[1], licence_set=paths.now())
        paths.save(paths.f("run.json"), run)
        return print(f"this run's models: {a[1]}")
    if a and a[0] == "redo":
        DEADLINE = "400"
        redo()
        return build(w)
    if a and a[0] == "build":
        c = a[a.index("--class") + 1] if "--class" in a else None
        lim = int(a[a.index("--limit") + 1]) if "--limit" in a else None
        return build(w, c, lim)
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
