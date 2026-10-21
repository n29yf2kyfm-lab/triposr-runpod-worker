"""Export machine builds as an app pack: one GLB and one vehicle file each.

The car page carries its car inside the page (the GLB as base64 in car*.json,
the parts catalogue and procedures in a script tag). An app needs them apart:
the model as a plain .glb it can load, and the facts about it (what each part
is called, which system it belongs to, which parts hinge and how far, which
come off and which way, where each part sits, who made the model) as data.

    python3 pipeline/realcar/app_pack.py OUT_DIR fleet.json

fleet.json lists the vehicles. Each names what to build, the way the user
would ask for it ("request", which this runs through `glbmachine.py car`), or
a bike modelled in code ("bike", built with bikes/cruiser.mjs --parts), or a
file already made ("answer": the JSON the machine printed; "glb"):

    [{"id": "volkswagen-golf-2017", "request": "Volkswagen Golf 2017 red",
      "kind": "car", "body": "hatchback", "real_layout": "..."},
     {"id": "cruiser", "bike": {"paint": "#121214"}, "kind": "motorbike", ...}]

It writes OUT_DIR/<id>.glb, OUT_DIR/<id>.json and OUT_DIR/index.json. Then

    node pipeline/realcar/app_hero.mjs OUT_DIR          # a studio picture of each, PNG
    python3 pipeline/realcar/app_pack.py --heroes OUT_DIR   # to cropped WebP, named in the files

The engine bay in every car is the machine's engine pack: one representative
teaching engine, the same in each car, not that car's own engine. The vehicle
file says so (engine.representative) and gives the car's real layout beside
it, so an app can label it honestly.
"""

import base64
import json
import os
import re
import struct
import sys

import numpy as np

SCHEMA = "expertcarcheck.vehicle/1"

# systems for the engine pack's parts, by part id (without "bay:")
SYSTEM = {
    "engine-bay-structure": "Body",
    "battery-assembly": "Electrical", "battery-negative-earth-lead": "Electrical",
    "dgea_loom": "Electrical", "dgea_coils": "Electrical",
    "radiator-condenser-cooling-pack": "Cooling", "radiator-upper-hose": "Cooling",
    "radiator-lower-hose": "Cooling", "radiator-upper-engine-hose-clamp": "Cooling",
    "radiator-upper-radiator-hose-clamp": "Cooling", "radiator-lower-radiator-hose-clamp": "Cooling",
    "radiator-lower-engine-hose-clamp": "Cooling", "coolant-expansion-reservoir": "Cooling",
    "coolant-degas-hose": "Cooling", "coolant_pump": "Cooling", "dgea_thermo": "Cooling",
    "dgea_epump": "Cooling",
    "gearbox-case": "Transmission", "bellhousing": "Transmission", "mechatronic-cover": "Transmission",
    "transmission-oil-filter": "Transmission", "transmission-oil-cooler": "Transmission",
    "integrated-front-differential": "Transmission", "cv-output-left": "Transmission",
    "cv-output-right": "Transmission",
    "blk": "Engine", "sump": "Engine", "head": "Engine", "cam_cover": "Engine",
    "timing_cover": "Engine", "dgea_filler": "Engine", "dgea_oilfilter": "Engine",
    "dgea_pulley": "Engine", "dgea_mount": "Engine",
    "dgea_intake": "Air and fuel", "dgea_airbox": "Air and fuel", "dgea_chargepipe": "Air and fuel",
    "dgea_turbo": "Air and fuel", "fuel_tank": "Air and fuel",
    "exhaust_front": "Exhaust",
    "subframe_f": "Suspension", "arb_f": "Suspension", "susp_rear": "Suspension",
}
SIDE_SYSTEM = {"knuckle": "Suspension", "strut": "Suspension", "droplink": "Suspension",
               "bj": "Suspension", "arm": "Suspension", "tre": "Steering", "ds": "Transmission"}

BODY_PARTS = {"body", "bonnet", "tailgate", "boot", "door_fl", "door_fr", "door_rl", "door_rr",
              "door_bl", "door_br", "slide_l", "slide_r"}

# the motorbike's pieces (bikes/cruiser.mjs --parts): label, system
BIKE_PARTS = {
    "frame": ("Frame", "Chassis"), "swingarm": ("Swingarm", "Suspension"),
    "rear_shocks": ("Rear shock absorbers", "Suspension"), "fork": ("Front fork", "Suspension"),
    "crankcase": ("Crankcase", "Engine"), "cylinders": ("Cylinders (barrels)", "Engine"),
    "cylinder_heads": ("Cylinder heads", "Engine"), "rocker_covers": ("Rocker covers", "Engine"),
    "pushrod_tubes": ("Pushrod tubes", "Engine"), "spark_plugs": ("Spark plugs", "Electrical"),
    "gearbox": ("Gearbox", "Transmission"), "primary_cover": ("Primary drive cover", "Transmission"),
    "belt": ("Final drive belt", "Transmission"), "pulley_r": ("Rear belt pulley", "Transmission"),
    "air_cleaner": ("Air cleaner", "Air and fuel"), "tank": ("Fuel tank", "Air and fuel"),
    "fuel_cap": ("Fuel cap", "Air and fuel"), "exhaust": ("Exhaust", "Exhaust"),
    "headlamp": ("Headlamp", "Electrical"), "tail_lamp": ("Tail lamp", "Electrical"),
    "indicators_front": ("Front indicators", "Electrical"), "indicators_rear": ("Rear indicators", "Electrical"),
    "speedo": ("Speedometer console", "Electrical"),
    "handlebar": ("Handlebar and controls", "Steering"), "mirrors": ("Mirrors", "Body"),
    "mudguard_front": ("Front mudguard", "Body"), "mudguard_rear": ("Rear mudguard", "Body"),
    "seat": ("Seat", "Body"), "footboards": ("Footboards and pegs", "Body"),
    "brake_pedal": ("Rear brake pedal", "Brakes"), "gear_lever": ("Gear lever", "Transmission"),
    "caliper_front": ("Front brake caliper", "Brakes"), "caliper_rear": ("Rear brake caliper", "Brakes"),
    "disc_f": ("Front brake disc", "Brakes"), "disc_r": ("Rear brake disc", "Brakes"),
    "tyre_f": ("Front tyre", "Wheels"), "tyre_r": ("Rear tyre", "Wheels"),
    "rim_f": ("Front wheel", "Wheels"), "rim_r": ("Rear wheel", "Wheels"),
    "side_stand": ("Side stand", "Chassis"),
}


def loader_name(name):
    """The name three.js's GLTFLoader gives a node (PropertyBinding.sanitizeNodeName):
    whitespace to _, and [ ] . : / dropped. Repeats get _1, _2 ... after it."""
    return re.sub(r"[\[\]\.:/]", "", re.sub(r"\s", "_", name))


def read_glb(data):
    if data[:4] != b"glTF":
        raise ValueError("not a GLB")
    ln = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + ln])


def _trs(n):
    if "matrix" in n:
        return np.array(n["matrix"], dtype=float).reshape(4, 4).T
    t = np.array(n.get("translation", [0, 0, 0]), dtype=float)
    x, y, z, w = n.get("rotation", [0, 0, 0, 1])
    s = np.array(n.get("scale", [1, 1, 1]), dtype=float)
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m


def world_boxes(j):
    """Each node's world matrix, and each mesh node's world bounding box (from the
    POSITION accessors' min/max, which glTF requires, through the node chain)."""
    nodes = j["nodes"]
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i
    cache = {}

    def world(i):
        if i not in cache:
            m = _trs(nodes[i])
            cache[i] = world(parent[i]) @ m if i in parent else m
        return cache[i]

    boxes = {}
    for i, n in enumerate(nodes):
        if "mesh" not in n:
            continue
        lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
        for pr in j["meshes"][n["mesh"]]["primitives"]:
            acc = j["accessors"][pr["attributes"]["POSITION"]]
            amin, amax = np.array(acc["min"], float), np.array(acc["max"], float)
            if acc.get("normalized"):          # quantized positions: min/max are the raw integers
                scale = {5120: 127, 5121: 255, 5122: 32767, 5123: 65535}.get(acc["componentType"], 1)
                amin, amax = amin / scale, amax / scale
            corners = np.array([[a, b, c, 1] for a in (amin[0], amax[0])
                                for b in (amin[1], amax[1]) for c in (amin[2], amax[2])])
            w = (world(i) @ corners.T).T[:, :3]
            lo, hi = np.minimum(lo, w.min(0)), np.maximum(hi, w.max(0))
        boxes[i] = (lo, hi)
    return world, boxes, parent


def _r(v, k=3):
    return [round(float(x), k) for x in v]


def part_id_of(name):
    """A node's part id: 'bay:blk' stays as is; the bike's and car's own names too."""
    return name


def removal(pid, centre, car_lo, car_hi):
    """Which way a part comes off, and how far: doors out sideways, the bonnet up
    and forward, a tailgate up and back, a wheel out from its hub, a bay part up
    out of the bay. A unit direction in the car's frame (+Y up, nose +Z, left +X)."""
    cx = (car_lo[0] + car_hi[0]) / 2
    side = 1.0 if centre[0] >= cx else -1.0
    if pid in ("door_bl", "door_br"):            # a van's barn doors: back and out
        return {"dir": [side * 0.5, 0.1, -1.0], "dist": 0.9}
    if pid.startswith(("door_", "slide_")):
        return {"dir": [side, 0.15, 0.0], "dist": 0.9}
    if pid == "bonnet":
        return {"dir": [0.0, 1.0, 0.35], "dist": 0.8}
    if pid in ("tailgate", "boot"):
        return {"dir": [0.0, 1.0, -0.4], "dist": 0.8}
    if pid.startswith("wheel_"):
        return {"dir": [side, 0.0, 0.0], "dist": 0.7}
    return {"dir": [0.0, 1.0, 0.0], "dist": 0.6}


def corner_label(label, end, side):
    """A pack part's label for where it actually sits: 'front left', 'rear
    right', ', left'. The engine pack's own left and right do not follow the
    car's frame (its driveshaft-output flanges are named the other way round),
    and in a rear-engined car the pack is turned round at the back, so its
    'front left' strut is the rear right one."""
    import re as _re
    out = _re.sub(r"\b(front|rear) (left|right)\b", f"{end} {side}", label)
    out = _re.sub(r", (left|right)$", f", {side}", out)
    if end == "rear":
        out = _re.sub(r"^Front (subframe|anti-roll bar|differential|exhaust pipe)",
                      lambda m: m.group(1).capitalize(), out)
    return out


def pair_sides(boxes):
    """Left or right for each sided pack part, by position: of a pair (strut_fl and
    strut_fr, cv-output-left and cv-output-right) the one further towards +X (the
    car's left) is the left one; a part with no partner goes by its own side."""
    import re as _re
    groups = {}
    for pid, (lo, hi) in boxes.items():
        m = _re.match(r"^bay:(.+?)(_f[lr]|-left|-right)$", pid)
        if m:
            groups.setdefault(m.group(1), []).append((pid, (lo[0] + hi[0]) / 2))
    side = {}
    for members in groups.values():
        if len(members) == 2:
            (a, xa), (b, xb) = members
            side[a], side[b] = ("left", "right") if xa > xb else ("right", "left")
        else:
            for pid, x in members:
                side[pid] = "left" if x >= 0 else "right"
    return side


def unit(v):
    v = np.array(v, float)
    n = np.linalg.norm(v)
    return _r(v / n if n else v)


def car_entry(spec, out_dir):
    ans = json.load(open(spec["answer"]))
    if "error" in ans:
        raise SystemExit(f"{spec['id']}: the machine refused it: {ans['error']}")
    page = os.path.dirname(ans["index"])
    html = open(ans["index"], encoding="utf-8").read()
    cfg = json.loads(re.search(r'id="car-config"[^>]*>(.*?)</script>', html, re.S).group(1))
    chunks = sorted((json.load(open(os.path.join(page, f))) for f in ans["files"] if f.startswith("car")),
                    key=lambda c: c["part"])
    glb = base64.b64decode("".join(c["glb_base64"] for c in chunks))
    j = read_glb(glb)
    world, boxes, parent = world_boxes(j)

    # every mesh node belongs to the part named by itself or its nearest named ancestor
    by_part = {}
    names = {i: n.get("name", "") for i, n in enumerate(j["nodes"])}
    catalogue_ids = {it["id"] for sec in cfg["catalogue"] for it in sec["items"]}

    def owner(i):
        k = i
        while k is not None:
            nm = names[k]
            if nm in catalogue_ids:
                return nm
            k = parent.get(k)
        return None

    for i, (lo, hi) in boxes.items():
        pid = owner(i)
        if pid:
            a = by_part.setdefault(pid, [np.full(3, np.inf), np.full(3, -np.inf)])
            a[0], a[1] = np.minimum(a[0], lo), np.maximum(a[1], hi)
    body_box = by_part.get("body")
    car_lo = np.min([v[0] for k, v in by_part.items() if not k.startswith("bay:")], axis=0)
    car_hi = np.max([v[1] for k, v in by_part.items() if not k.startswith("bay:")], axis=0)

    blk0 = by_part.get("bay:blk")
    pack_turned = blk0 is not None and (blk0[0][2] + blk0[1][2]) / 2 < (car_lo[2] + car_hi[2]) / 2
    sides = pair_sides({k: v for k, v in by_part.items() if k.startswith("bay:")})

    hinges = []
    for i, n in enumerate(j["nodes"]):
        if n.get("name", "").endswith("_hinge") and n.get("extras"):
            pid = n["name"][:-len("_hinge")]
            hinges.append({"part": pid, "node": n["name"], "node_loaded": loader_name(n["name"]),
                           "pivot": _r(world(i)[:3, 3]), "axis": n["extras"]["axis"],
                           "open_deg": n["extras"]["open_deg"],
                           "clip": f"{pid}_open" if any(a.get("name") == f"{pid}_open" for a in j.get("animations", [])) else None})
    hinged = {h["part"] for h in hinges}

    parts = []
    for sec in cfg["catalogue"]:
        for it in sec["items"]:
            pid = it["id"]
            raw = pid[4:] if pid.startswith("bay:") else pid
            side = re.match(r"^([a-z]+)_f([lr])$", raw)
            if pid.startswith("bay:"):
                system = SYSTEM.get(raw) or (SIDE_SYSTEM.get(side.group(1)) if side else None) or "Other"
            elif pid.startswith("wheel_"):
                system = "Wheels"
            elif pid == "exhaust":
                system = "Exhaust"
            else:
                system = "Body"
            box = by_part.get(pid)
            label = (spec.get("labels") or {}).get(pid, it["label"])
            if pid.startswith("bay:") and box is not None and (pid in sides or pack_turned):
                mid_z = (car_lo[2] + car_hi[2]) / 2
                label = corner_label(label, "front" if (box[0][2] + box[1][2]) / 2 >= mid_z else "rear",
                                     sides.get(pid, ""))
            entry = {"id": pid, "label": label,
                     "section": sec["title"], "system": system,
                     "node": pid, "node_loaded": loader_name(pid),
                     "representative": pid.startswith("bay:"),
                     "opens": pid in hinged,
                     "removable": pid != "body"}
            if box is not None:
                lo, hi = box
                entry["box"] = {"min": _r(lo), "max": _r(hi)}
                entry["remove"] = removal(pid, (lo + hi) / 2, car_lo, car_hi)
                entry["remove"]["dir"] = unit(entry["remove"]["dir"])
            parts.append(entry)

    engine_lid = (cfg.get("engine") or {}).get("lid") or "bonnet"
    blk = by_part.get("bay:blk")
    engine_at = "rear" if blk is not None and (blk[0][2] + blk[1][2]) / 2 < (car_lo[2] + car_hi[2]) / 2 else "front"
    credit = cfg.get("credit") or {}
    vid = spec["id"]
    glb_name = f"{vid}.glb"
    open(os.path.join(out_dir, glb_name), "wb").write(glb)
    v = {
        "schema": SCHEMA, "id": vid, "title": spec.get("title") or cfg["title"],
        "kind": spec["kind"], "body": spec.get("body"), "machine_key": cfg.get("key"),
        "glb": glb_name, "bytes": len(glb),
        "frame": "metres; +Y up, nose +Z, the vehicle's left +X; ground at y = 0",
        "box": {"min": _r(car_lo), "max": _r(car_hi)},
        "paint": {"hex": ((cfg.get("start") or {}).get("body") or {}).get("hex"),
                  "finish": ((cfg.get("start") or {}).get("body") or {}).get("finish"),
                  "materials": ((cfg.get("lab") or {}).get("body") or {}).get("names", []),
                  "wheel_materials": ((cfg.get("lab") or {}).get("wheels") or {}).get("names", []),
                  "caliper_materials": ((cfg.get("lab") or {}).get("calipers") or {}).get("names", [])},
        "hinges": hinges,
        "clips": [a.get("name") for a in j.get("animations", [])],
        "parts": parts,
        "procedures": cfg.get("procedures", []),
        "engine": {"representative": True, "at": engine_at, "lid": engine_lid,
                   "note": "The engine bay is the machine's teaching engine pack: a representative "
                           "transverse four-cylinder with its gearbox, cooling, front suspension and "
                           "driveshafts. It is the same in every car here, not this vehicle's own engine.",
                   "real_layout": spec.get("real_layout")},
        "notes": ans.get("notes") or [],
        "credit": {"title": credit.get("title"), "author": credit.get("author"),
                   "licence": credit.get("licence"), "url": credit.get("url"),
                   "commercial": credit.get("commercial"),
                   "line": _credit_line(credit)},
    }
    return v


def _credit_line(c):
    if not c.get("title"):
        return None
    who = f" by {c['author']}" if c.get("author") else ""
    return f"“{c['title']}”{who}, {c.get('licence') or 'licence as stated'}" + (f", {c['url']}" if c.get("url") else "")


def bike_entry(spec, out_dir):
    glb = open(spec["glb"], "rb").read()
    j = read_glb(glb)
    world, boxes, parent = world_boxes(j)
    names = {i: n.get("name", "") for i, n in enumerate(j["nodes"])}
    lo_all, hi_all = np.min([b[0] for b in boxes.values()], 0), np.max([b[1] for b in boxes.values()], 0)
    cx = (lo_all[0] + hi_all[0]) / 2
    parts = []
    for i, (lo, hi) in sorted(boxes.items(), key=lambda kv: names[kv[0]]):
        pid = names[i]
        label, system = BIKE_PARTS.get(pid, (pid.replace("_", " ").capitalize(), "Other"))
        moves = (j["nodes"][i].get("extras") or {}).get("moves_with")
        centre = (lo + hi) / 2
        side = 1.0 if centre[0] >= cx else -1.0
        if system in ("Engine", "Air and fuel", "Exhaust", "Transmission") and pid not in ("belt", "pulley_r", "gear_lever"):
            d = [side * 0.6, 0.5, 0.0] if abs(centre[0] - cx) > 0.08 else [0.0, 1.0, 0.0]
        elif pid in ("seat", "tank", "fuel_cap", "speedo"):
            d = [0.0, 1.0, 0.0]
        elif pid.startswith(("tyre_", "rim_", "disc_")):
            d = [side * 1.0, 0.2, 0.0]
        else:
            d = [side * 1.0, 0.3, 0.0]
        parts.append({"id": pid, "label": label, "system": system, "node": pid, "node_loaded": loader_name(pid),
                      "moves_with": moves, "representative": False, "opens": False, "removable": True,
                      "box": {"min": _r(lo), "max": _r(hi)}, "remove": {"dir": unit(d), "dist": 0.5}})
    vid = spec["id"]
    open(os.path.join(out_dir, f"{vid}.glb"), "wb").write(glb)
    return {
        "schema": SCHEMA, "id": vid, "title": spec.get("title") or "Heavy cruiser motorbike",
        "kind": "motorbike", "body": spec.get("body") or "cruiser", "glb": f"{vid}.glb", "bytes": len(glb),
        "frame": "metres; +Y up, nose +Z, the rider's left +X; ground at y = 0",
        "box": {"min": _r(lo_all), "max": _r(hi_all)},
        "paint": {"hex": spec.get("paint"), "materials": ["paint"]},
        "hinges": [], "clips": [a.get("name") for a in j.get("animations", [])],
        "pivots": {n: {"node": n, "moves": m} for n, m in
                   (("steer", "the fork, wheel, lamp and bars turn about the raked steering axis"),
                    ("wheel_f", "the front wheel turns on its axle"), ("wheel_r", "the rear wheel turns on its axle"),
                    ("stand", "the side stand swings down"))},
        "parts": parts, "procedures": spec.get("procedures", []),
        "engine": {"representative": False, "at": "middle",
                   "note": "Modelled in code by the machine: a 45-degree air-cooled pushrod V-twin with "
                           "a separate gearbox, a primary drive on the left and a belt final drive.",
                   "real_layout": spec.get("real_layout")},
        "notes": spec.get("notes", []),
        "credit": {"title": spec.get("title"), "author": "ExpertCarCheck GLB machine (bikes/cruiser.mjs)",
                   "licence": "ExpertCarCheck own work", "url": None, "commercial": True,
                   "line": "Modelled in code by the ExpertCarCheck GLB machine. No maker's model, badge or lettering."},
    }


HERE = os.path.dirname(os.path.abspath(__file__))


def build(spec, work):
    """Run the machine (or the bike modeller) for a spec that names a request."""
    import subprocess
    if spec.get("request"):
        r = subprocess.run([sys.executable, os.path.join(HERE, "glbmachine.py"), "car", *spec["request"].split()],
                           capture_output=True, text=True, timeout=600)
        ans = json.loads(r.stdout)
        if "error" in ans:
            raise SystemExit(f"{spec['id']}: the machine refused {spec['request']!r}: {ans['error']}")
        path = os.path.join(work, f"{spec['id']}.answer.json")
        json.dump(ans, open(path, "w"))
        spec["answer"] = path
    elif spec.get("bike") is not None:
        raw, web = os.path.join(work, f"{spec['id']}_raw.glb"), os.path.join(work, f"{spec['id']}.glb")
        paint = (spec["bike"] or {}).get("paint") or "#121214"
        subprocess.run(["node", os.path.join(HERE, "bikes", "cruiser.mjs"), raw, f"--paint={paint}", "--parts"],
                       check=True, capture_output=True, timeout=300)
        subprocess.run(["node", os.path.join(HERE, "encode.mjs"), raw, web], check=True, capture_output=True, timeout=300)
        spec.setdefault("paint", paint)
        spec["glb"] = web


def heroes(out_dir):
    """The studio pictures app_hero.mjs rendered: cropped to the vehicle, saved as
    WebP with its transparency, and named in index.json and each vehicle file."""
    from PIL import Image
    idx = json.load(open(os.path.join(out_dir, "index.json")))
    for v in idx["vehicles"]:
        png = os.path.join(out_dir, f"{v['id']}.png")
        if not os.path.exists(png):
            continue
        im = Image.open(png).convert("RGBA")
        bb, pad = im.getbbox(), 40
        im = im.crop((max(0, bb[0] - pad), max(0, bb[1] - pad), min(im.width, bb[2] + pad), min(im.height, bb[3] + pad)))
        im.save(os.path.join(out_dir, f"{v['id']}.webp"), "WEBP", quality=86, method=6)
        os.remove(png)
        v["hero"] = f"{v['id']}.webp"
        vp = os.path.join(out_dir, f"{v['id']}.json")
        vj = json.load(open(vp)); vj["hero"] = v["hero"]
        json.dump(vj, open(vp, "w"), indent=1, ensure_ascii=False)
        print(f"{v['id']:32s} hero {im.size[0]}x{im.size[1]}")
    json.dump(idx, open(os.path.join(out_dir, "index.json"), "w"), indent=1, ensure_ascii=False)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--heroes":
        return heroes(sys.argv[2])
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    import tempfile
    out_dir, fleet = sys.argv[1], json.load(open(sys.argv[2]))
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.dirname(os.path.abspath(sys.argv[2]))
    work = tempfile.mkdtemp(prefix="app_pack_")
    index = []
    for spec in fleet:
        build(spec, work)
        for k in ("answer", "glb"):
            if spec.get(k) and not os.path.isabs(spec[k]):
                spec[k] = os.path.join(base, spec[k])
        v = bike_entry(spec, out_dir) if spec.get("glb") else car_entry(spec, out_dir)
        for k in ("summary", "teaches", "hero"):
            if spec.get(k):
                v[k] = spec[k]
        json.dump(v, open(os.path.join(out_dir, f"{v['id']}.json"), "w"), indent=1, ensure_ascii=False)
        index.append({"id": v["id"], "title": v["title"], "kind": v["kind"], "body": v["body"],
                      "glb": v["glb"], "json": f"{v['id']}.json", "bytes": v["bytes"],
                      "hero": spec.get("hero"), "summary": spec.get("summary"),
                      "parts": len(v["parts"]), "opens": [h["part"] for h in v["hinges"]],
                      "credit": v["credit"]["line"]})
        print(f"{v['id']:32s} {v['bytes'] / 1e6:5.1f} MB  {len(v['parts']):3d} parts  opens {[h['part'] for h in v['hinges']]}")
    json.dump({"schema": "expertcarcheck.fleet/1", "vehicles": index}, open(os.path.join(out_dir, "index.json"), "w"),
              indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
