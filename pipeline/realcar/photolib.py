#!/usr/bin/env python3
"""photolib.py — the standby roofline library, built by an agent.

    python3 pipeline/realcar/photolib.py --top 100            # the 100 most-licensed UK models
    python3 pipeline/realcar/photolib.py --top 2000 --hours 8 # all of them, a night's run
    python3 pipeline/realcar/photolib.py --status

For each car in the UK licensing list (platform/catalogue/uk_targets/
top2000_cars.csv), by rank, and each of its generations from --since on
(the wheelbase table's, looked up online once for a model the table does
not have), the agent finds a licensed true side photograph (photos.py:
Openverse and Wikimedia Commons, CC BY / BY-SA / CC0 / public domain only,
checked to be one plain car side on with the generation's own wheel spacing
and proportions) and keeps its measured outline:

  roofline_table.json   (shipped with the machine) the outline as heights
                        along the car, the wheel centres, and the photo's
                        file, author, licence and page. Numbers and a
                        credit only: no photograph, so no licence goes with it.
  $GLBMACHINE_HOME/photos/<car>/   the photograph and its cut-out, for
                        showing beside a stand-in.

A stand-in (make.py) takes its roofline from the library at once, and only
searches when the library has nothing. Google Images is not used: its
photographs are copyrighted and Google's terms forbid scraping its results.

The run can be stopped and started again: a generation in the library, or
searched without success in the last --retry-days, is skipped. It slows
down when a source answers "too many requests".
"""
import argparse
import csv
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import photos  # noqa: E402
import wheelbase  # noqa: E402

HOME = os.path.abspath(os.path.expanduser(os.environ.get("GLBMACHINE_HOME", "~/.glbmachine")))
STATE = os.path.join(HOME, "photolib_state.json")
TARGETS = os.path.join(REPO, "platform", "catalogue", "uk_targets", "top2000_cars.csv")
MAKE = {"mercedes": "mercedes-benz", "land rover": "land-rover", "alfa romeo": "alfa-romeo", "vw": "volkswagen"}


def _load(p, default):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return default


def _save(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(obj, open(p + ".tmp", "w"), indent=0, sort_keys=True)
    os.replace(p + ".tmp", p)


def targets(top):
    rows = list(csv.DictReader(open(TARGETS)))
    rows.sort(key=lambda r: int(r["rank"]))
    for r in rows[:top]:
        mk = MAKE.get(r["make"].lower(), r["make"].lower())
        model = r["model"].strip()
        if re.search(r"\b(?:van|camper|motorhome|taxi|hearse|limousine)\b", model, re.I):
            continue
        yield int(r["rank"]), mk, model


def generations(make, model, since):
    """The table's generations of MAKE MODEL from SINCE on, with a full size."""
    try:
        wheelbase.lookup(make, model.lower(), since, online=True)   # fetched once if the table lacks it
    except Exception:
        pass
    ent = wheelbase.table().get(f"{make}|{model.lower()}") or {}
    seen, out = set(), []
    for b in ent.get("boxes", []):
        y = b.get("years")
        if not y or y[0] < since - 6 or (y[1] or 2100) < since or wheelbase.RACE.search(b.get("name") or ""):
            continue
        if not all(b.get(k) for k in ("length", "wheelbase", "height")):
            continue
        k = (y[0], b["wheelbase"])
        if k in seen:
            continue
        seen.add(k)
        out.append(b)
    return out


def run(top, since, hours, retry_days, per_gen_s):
    lib = photos.library()
    state = _load(STATE, {})
    t_end = time.time() + hours * 3600
    done = found = 0
    for rank, make, model in targets(top):
        if time.time() > t_end:
            print("time is up", flush=True)
            break
        for b in generations(make, model, since):
            y = [b["years"][0], None if b["years"][1] >= 2100 else b["years"][1]]
            key = photos.libkey(make, model, y[0])
            if key in lib:
                continue
            last = state.get(key)
            if last and time.time() - last.get("at", 0) < retry_days * 86400:
                continue
            if photos.THROTTLED["openverse"] >= 3:          # the source asks for a pause
                print("  throttled: pausing 10 min", flush=True)
                time.sleep(600)
                photos.THROTTLED["openverse"] = 0
            if time.time() > t_end:
                break
            d = os.path.join(HOME, "photos", re.sub(r"[^a-z0-9]+", "-", f"{make} {model} {y[0]}".lower()).strip("-"))
            t0 = time.time()
            try:
                r = photos.side_photo(make, wheelbase.wiki_title(model.lower()), y, d,
                                      {k: b[k] for k in ("length", "wheelbase", "height")}, deadline_s=per_gen_s)
            except Exception as e:
                r = {"none": True, "error": str(e)[:200]}
            done += 1
            if r and r.get("cutout"):
                rl = photos.roofline(r["cutout"], b["length"])
                lib[key] = {"make": make, "model": model, "years": y, "generation": b.get("name"),
                            "size_mm": {k: b[k] for k in ("length", "wheelbase", "width", "height") if b.get(k)},
                            "roof": rl["roof"], "u": rl["u"], "u_front": rl["u_front"], "u_rear": rl["u_rear"],
                            "height_photo": rl["height_photo"],
                            "photo": {k: r.get(k) for k in ("file", "author", "licence", "page")},
                            "checked": time.strftime("%Y-%m-%d")}
                _save(photos.LIBRARY, lib)
                _save(os.path.join(d, "found.json"), dict(r, roofline=rl))
                found += 1
                print(f"{rank:5d} {make} {model} {y[0]}: {r['file'][:60]} ({time.time() - t0:.0f} s)", flush=True)
            else:
                state[key] = {"at": time.time(), "looked_at": len((r or {}).get("rejected") or []),
                              "why": (r or {}).get("error") or "no usable side photo"}
                _save(STATE, state)
                print(f"{rank:5d} {make} {model} {y[0]}: none ({len((r or {}).get('rejected') or [])} looked at, "
                      f"{time.time() - t0:.0f} s)", flush=True)
    print(json.dumps({"searched": done, "found": found, "library": len(lib), "throttled": photos.THROTTLED}), flush=True)


def status():
    lib, state = photos.library(), _load(STATE, {})
    makes = {}
    for v in lib.values():
        makes[v["make"]] = makes.get(v["make"], 0) + 1
    print(json.dumps({"generations_in_library": len(lib), "searched_without_success": len(state),
                      "by_make": dict(sorted(makes.items(), key=lambda kv: -kv[1]))}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=100, help="how far down the UK licensing list")
    ap.add_argument("--since", type=int, default=2000, help="generations on sale from this year")
    ap.add_argument("--hours", type=float, default=2.0, help="stop after this long (start again to carry on)")
    ap.add_argument("--retry-days", type=float, default=30, help="look again for a car not found this long ago")
    ap.add_argument("--per-car", type=float, default=60, help="seconds to spend on one generation")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status:
        status()
    else:
        run(a.top, a.since, a.hours, a.retry_days, a.per_car)
