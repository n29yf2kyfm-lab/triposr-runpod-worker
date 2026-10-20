#!/usr/bin/env python3
"""page.py — a built car as a page anyone can open: the machine's own 3D
viewer (spin, flip, open every part, the Finish Lab), filled in from the
build's report. The GLB travels as base64 JSON parts (15 MB each at most), so
the folder can be published where only data files are served.

    glbmachine make "Peugeot 307 2001 blue" --page OUT_DIR
    python3 page.py REPORT.json OUT_DIR

OUT_DIR gets index.html and car1.json … carN.json (and views.jpg when the
build drew a check sheet). It takes a second or two: nothing is rebuilt.
"""
import base64
import html
import json
import os
import re
import shutil
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PART = 15_000_000                     # base64 characters a part: a multiple of 4

PART_NAMES = {"door_fl": "Front left door", "door_fr": "Front right door", "door_rl": "Rear left door",
              "door_rr": "Rear right door", "bonnet": "Bonnet", "tailgate": "Tailgate",
              "door_bl": "Back door, left", "door_br": "Back door, right"}
TYRE = re.compile(r"tyre|tire|pneu|rubber|reifen|lastik|gomma|neumatico|band", re.I)
RIM = re.compile(r"\brim|rims?_|wheel|roda|jante|felge|alloy|rueda|cerchio|velg", re.I)
CALIPER = re.compile(r"caliper|calliper|freio|pinca|pinza|bremse|sattel|etrier|brake", re.I)
NOT_CALIPER = re.compile(r"dis[ck]|rotor|scheibe|light|lamp|luz", re.I)
CAPS = {"bmw": "BMW", "mg": "MG", "ds": "DS", "byd": "BYD", "seat": "SEAT", "vw": "VW", "gmc": "GMC", "kgm": "KGM"}


def _glb_json(data):
    n = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + n])


def _word(w):
    """A model word as written on the car: a short code of letters then digits
    in capitals (M5, RS6, X5, A4), but BMW's i cars stay lower case (i4, iX4)."""
    if w.lower() in CAPS:
        return CAPS[w.lower()]
    if re.fullmatch(r"[a-z]{1,3}\d{1,3}", w) and not w.startswith("i"):
        return w.upper()
    return w if any(c.isdigit() for c in w) or w.isupper() else w.capitalize()


def _name(make, model):
    mk = "-".join(CAPS.get(w, w.capitalize()) for w in str(make or "").split("-"))
    md = " ".join(_word(w) for w in str(model or "").replace(str(make or ""), "").split())
    return f"{mk} {md}".strip()


def start_finish(asked, finish, srgb):
    """The Finish Lab state the page starts in, from the request: the body in
    the finish asked ("matt grey"), the rims in the colour asked ("gloss
    black wheels"). None when the request names neither."""
    hx = lambda c: "#%02x%02x%02x" % tuple(c)  # noqa: E731
    out = {}
    if finish and srgb:
        out["body"] = {"finish": finish, "hex": hx(srgb)}
    w = asked.get("wheels") or {}
    if w.get("srgb"):
        out["wheels"] = {"finish": w.get("finish") or "gloss", "hex": hx(w["srgb"])}
    return out or None


def lab_parts(j, paint_names):
    """The Finish Lab's parts, by material name: the rims (in the wheel
    groups, or by name where a model keeps them on the body), the calipers,
    the body paint."""
    mats = j.get("materials") or []
    nodes = j.get("nodes") or []

    def names_under(i, out):
        n = nodes[i]
        for pr in (j["meshes"][n["mesh"]]["primitives"] if "mesh" in n else []):
            if pr.get("material") is not None:
                out.add(mats[pr["material"]].get("name") or "")
        for c in n.get("children", []):
            names_under(c, out)
        return out
    in_wheels = set()
    for i, n in enumerate(nodes):
        if re.fullmatch(r"wheel_[fr][lr]", n.get("name") or ""):
            names_under(i, in_wheels)
    rims = sorted(m for m in in_wheels if m and not TYRE.search(m))
    every = {m.get("name") or "" for m in mats if not (m.get("name") or "").startswith("cabin_")}
    wheels = {"names": rims, "where": "wheel"} if rims else \
        {"names": sorted(m for m in every if m and RIM.search(m) and not TYRE.search(m)), "where": "any"}
    calipers = {"names": sorted(m for m in every if m and CALIPER.search(m) and not NOT_CALIPER.search(m)), "where": "any"}
    body = {"names": sorted(set(paint_names) & every), "where": "body"}
    return {"wheels": wheels, "calipers": calipers, "body": body}


# ── parts catalogue and procedures (the page's Parts & procedures panel) ──
PART_LABEL = {
    "body": "Body shell", "bonnet": "Bonnet", "tailgate": "Tailgate", "door_fl": "Front left door", "door_fr": "Front right door",
    "door_rl": "Rear left door", "door_rr": "Rear right door", "door_bl": "Back door, left", "door_br": "Back door, right",
    "wheel_fl": "Front left wheel", "wheel_fr": "Front right wheel", "wheel_rl": "Rear left wheel", "wheel_rr": "Rear right wheel",
    "engine_bay": "Engine bay", "rear_running_gear": "Under the back", "exhaust": "Exhaust system", "cabin": "Cabin",
    "bay_front_wall": "Bay wall",
    # the workshop's engine pack, by its node names
    "bay:engine-bay-structure": "Bay structure and inner wings", "bay:battery-assembly": "Battery",
    "bay:battery-negative-earth-lead": "Battery earth lead", "bay:radiator-condenser-cooling-pack": "Radiator and cooling pack",
    "bay:radiator-upper-hose": "Radiator top hose", "bay:radiator-lower-hose": "Radiator bottom hose",
    "bay:radiator-upper-engine-hose-clamp": "Top hose clamp, engine end", "bay:radiator-upper-radiator-hose-clamp": "Top hose clamp, radiator end",
    "bay:radiator-lower-radiator-hose-clamp": "Bottom hose clamp, radiator end", "bay:radiator-lower-engine-hose-clamp": "Bottom hose clamp, engine end",
    "bay:coolant-expansion-reservoir": "Coolant expansion tank", "bay:coolant-degas-hose": "Coolant degas hose",
    "bay:gearbox-case": "Gearbox", "bay:bellhousing": "Bell housing", "bay:mechatronic-cover": "Gearbox control unit cover",
    "bay:transmission-oil-filter": "Transmission oil filter", "bay:transmission-oil-cooler": "Transmission oil cooler",
    "bay:integrated-front-differential": "Front differential", "bay:cv-output-left": "Driveshaft output, left",
    "bay:cv-output-right": "Driveshaft output, right", "bay:blk": "Engine block", "bay:sump": "Oil sump", "bay:head": "Cylinder head",
    "bay:cam_cover": "Cam cover", "bay:timing_cover": "Timing cover", "bay:coolant_pump": "Coolant pump", "bay:dgea_coils": "Ignition coils",
    "bay:dgea_filler": "Oil filler cap", "bay:dgea_intake": "Intake manifold", "bay:dgea_airbox": "Air filter box",
    "bay:dgea_chargepipe": "Charge pipe", "bay:dgea_turbo": "Turbocharger", "bay:dgea_mount": "Engine mount",
    "bay:dgea_pulley": "Crank pulley and belt", "bay:dgea_thermo": "Thermostat housing", "bay:dgea_oilfilter": "Oil filter",
    "bay:dgea_epump": "Electric coolant pump", "bay:dgea_loom": "Engine wiring loom", "bay:exhaust_front": "Front exhaust pipe",
    "bay:subframe_f": "Front subframe", "bay:arb_f": "Front anti-roll bar", "bay:fuel_tank": "Fuel tank", "bay:susp_rear": "Rear suspension",
}
SIDE = {"fl": "front left", "fr": "front right", "rl": "rear left", "rr": "rear right"}
CORNER_PART = {"knuckle": "hub carrier", "strut": "strut", "droplink": "anti-roll bar drop link", "tre": "track rod end",
               "bj": "ball joint", "arm": "lower arm", "ds": "driveshaft"}


def part_label(name):
    """A part's name for people: the dictionary, else the node name cleaned
    up ("bay:dgea_airbox" -> "Air filter box"; "bay:knuckle_fl" -> "Hub
    carrier, front left")."""
    if name in PART_LABEL:
        return PART_LABEL[name]
    n = re.sub(r"^bay:", "", name)
    m = re.fullmatch(r"([a-z]+)_([fr][lr])", n)
    if m and m.group(1) in CORNER_PART:
        return f"{CORNER_PART[m.group(1)].capitalize()}, {SIDE[m.group(2)]}"
    n = re.sub(r"^dgea_", "", n).replace("_", " ").replace("-", " ").strip()
    return n[:1].upper() + n[1:]


def catalogue(j):
    """The car's parts as the page lists them: groups of items, each item a
    node of the file (its name is how the page finds it), numbered through
    the whole list, as a parts catalogue numbers its callouts."""
    nodes = j.get("nodes") or []
    root = nodes[j["scenes"][j.get("scene", 0)]["nodes"][0]]
    top = {nodes[c].get("name") or "": c for c in root.get("children", [])}

    def kids(name):
        i = top.get(name)
        return [nodes[c].get("name") for c in (nodes[i].get("children") or [])] if i is not None else []
    groups = []

    def group(title, names, drill=None):
        items = [{"id": n, "label": part_label(n)} for n in names if n]
        if items:
            groups.append({"title": title, "drill": drill, "items": items})
    body = [n for n in ("body", "bonnet", "door_fl", "door_fr", "door_rl", "door_rr", "door_bl", "door_br", "tailgate")
            if n in top or n + "_hinge" in top]
    group("Body and openings", body)
    group("Wheels", [n for n in ("wheel_fl", "wheel_fr", "wheel_rl", "wheel_rr") if n in top])
    bay = [n for n in kids("engine_bay") if not str(n).startswith("bay:engine-bay-structure")]
    group("Engine bay", bay, drill="engine_bay")
    under = kids("rear_running_gear") + (["exhaust"] if "exhaust" in top else [])
    group("Under the car", under, drill="rear_running_gear")
    if "cabin" in top:
        group("Cabin", ["cabin"])
    k = 0
    for g in groups:
        for it in g["items"]:
            k += 1
            it["n"] = k
    return groups


def procedures(cat, opens, rear_engine=False):
    """Step-by-step checks over the car, as a maintenance manual walks a
    procedure: each step says what to look at, which parts to open and
    highlight, and where the camera goes. Only steps whose parts this car
    has are kept."""
    have = {it["id"] for g in cat for it in g["items"]}
    opens = set(opens or [])

    def step(text, view, parts=(), open_=(), note=None):
        parts = [p for p in parts if p in have]
        open_ = [p for p in open_ if p in opens]
        return {"text": text, "view": view, "parts": parts, "open": open_, **({"note": note} if note else {})}
    walk = [
        step("Front: bonnet shut line even both sides, lamps clear and matching, bumper paint matching the wings.", "front",
             ["bonnet"]),
        step("Front left corner: tyre tread and wear across the width, wheel for kerbing, arch for rust.", "wheel:fl", ["wheel_fl"]),
        step("Left side: door gaps even, paint matching panel to panel, sills straight. Look along the side for ripples.", "nearside",
             ["door_fl", "door_rl"]),
        step("Rear left corner: tyre and wheel as at the front; the arch lip.", "wheel:rl", ["wheel_rl"]),
        step("Rear: tailgate shut lines, lamps, bumper. A boot that does not close flush has been hit.", "rear", ["tailgate"]),
        step("Rear right corner.", "wheel:rr", ["wheel_rr"]),
        step("Right side: the same as the left, and the fuel filler area.", "offside", ["door_fr", "door_rr"]),
        step("Front right corner.", "wheel:fr", ["wheel_fr"]),
    ]
    lid = "tailgate" if rear_engine else "bonnet"
    bay = [
        step("Open the lid. Look for fresh paint on the slam panel and bolt heads: a sign of front-end repair.", "bay", [lid], [lid]),
        step("Battery: terminals clean, clamp tight, no white deposits.", "part", ["bay:battery-assembly"], [lid]),
        step("Coolant tank: level between the marks, no oil film on the coolant.", "part", ["bay:coolant-expansion-reservoir"], [lid]),
        step("Radiator and hoses: hoses firm, clamps dry, radiator fins straight.", "part",
             ["bay:radiator-condenser-cooling-pack", "bay:radiator-upper-hose", "bay:radiator-lower-hose"], [lid]),
        step("Oil filler and cam cover: no mayonnaise under the cap, no oil weeping from the cover gasket.", "part",
             ["bay:dgea_filler", "bay:cam_cover"], [lid]),
        step("Air box and intake: clips in place, no split ducting.", "part", ["bay:dgea_airbox", "bay:dgea_intake"], [lid]),
        step("Belt and pulley: belt not glazed or cracked.", "part", ["bay:dgea_pulley"], [lid]),
        step("Engine mount and wiring loom: mount rubber whole, loom tidy and clipped.", "part", ["bay:dgea_mount", "bay:dgea_loom"], [lid]),
    ]
    doors = [step(f"Open the {part_label(d).lower()}: hinges and check strap, door card fit, window operation.",
                  "door:" + d[-2:], [d], [d]) for d in ("door_fl", "door_fr", "door_rl", "door_rr") if d in opens]
    doors.append(step("Cabin: seat bolsters, steering wheel wear against the mileage, warning lights at ignition.", "cabin",
                      ["cabin"], [d for d in ("door_fl",) if d in opens]))
    under = [
        step("Open the tailgate: boot floor and spare wheel well dry, no ripples in the floor.", "boot", ["tailgate"], ["tailgate"]),
        step("Turn the car over: fuel tank straps, rear suspension bushes, exhaust hangers and corrosion.", "under",
             ["bay:fuel_tank", "bay:susp_rear", "exhaust"]),
    ]
    out = []
    for title, steps in (("Walk-round inspection", walk), ("Under the bonnet" if not rear_engine else "Under the engine lid", bay),
                         ("Doors and cabin", doors), ("Boot and underside", under)):
        steps = [st for st in steps if st["parts"] or st["view"] in ("front", "rear", "nearside", "offside")]
        if len(steps) >= 2:
            out.append({"title": title, "steps": steps})
    return out


def write(report, out):
    """REPORT: make.build's. Writes the page into OUT; returns its files."""
    t0 = time.time()
    res = report.get("result") or {}
    fin = res.get("finish") or {}
    glb = (report.get("files") or {}).get("glb")
    if not glb or not os.path.exists(glb):
        raise ValueError("no car file in this report: " + str(report.get("error") or "not built"))
    os.makedirs(out, exist_ok=True)
    data = open(glb, "rb").read()
    j = _glb_json(data)
    b64 = base64.b64encode(data).decode()
    files = []
    for k, i in enumerate(range(0, len(b64), PART), 1):
        f = f"car{k}.json"
        json.dump({"part": k, "of": -(-len(b64) // PART), "glb_base64": b64[i:i + PART]},
                  open(os.path.join(out, f), "w"))
        files.append(f)

    asked = report.get("asked") or {}
    st = report.get("standin") or {}
    item = {}
    try:
        import batch
        b = json.load(open(os.path.join(os.path.dirname(glb), "build.json")))
        item = b.get("item") or {}
        mk_, md_ = batch.model_of(item)
    except Exception:
        mk_, md_ = asked.get("make") or "", ""
    name = st.get("car") or _name(mk_, md_)
    year = asked.get("year")
    title = f"{name} {year}" if year and not st else name
    rear = fin.get("layout") == "rear engine"
    names = dict(PART_NAMES, **({"bonnet": "Front lid", "tailgate": "Engine lid"} if rear else {}))
    opens = fin.get("opens") or []
    parts = [[p, names[p]] for p in names if p in opens]
    try:
        rr = json.load(open(os.path.join(os.path.dirname(glb), "rig", "src.report.json")))
        paint_names = (rr.get("paint") or {}).get("renamed") or []
        closed = rr.get("closed_up") or {}
    except Exception:
        paint_names, closed = [], {}
    if fin.get("paint_set"):
        paint_names = list(paint_names) + [fin["paint_set"].get("material")]

    colour = asked.get("colour")
    srgb = (fin.get("paint_set") or {}).get("srgb")
    finish = asked.get("finish") if srgb else None     # "matt grey": the body starts matt, in the paint asked
    if finish and colour:
        colour = f"{finish} {colour}"
    read = ", ".join(str(x) for x in (name, year, colour) if x)
    if report.get("spelling") or asked.get("make_from_model"):
        read += " (the make read from the model)" if asked.get("make_from_model") else f" ({report['spelling']})"
    vw = res.get("validator_web") or res.get("validator") or {}
    secs = report.get("seconds_to_file")
    facts = [
        {"k": "Your request", "v": f"“{asked.get('text') or ''}”", "s": "read as " + read},
        {"k": "Time", "v": f"{secs} s to the file" if secs is not None else "built",
         "s": "the model was ready from an earlier build" if res.get("rig_from_cache") else "first build of this model"},
        {"k": "Opens", "v": f"{len(parts)} parts", "s": ", ".join(n for _, n in parts) or "nothing"},
        {"k": "Paint", "v": colour.capitalize() if colour else "As modelled",
         "s": f"sRGB {' · '.join(map(str, srgb))}" if srgb else "no colour asked for"},
        {"k": "Model", "v": res.get("credit", {}).get("title") or item.get("sourceTitle") or report.get("asset") or "",
         "s": report.get("match") or ""},
        {"k": "File", "v": f"{(res.get('web_bytes') or len(data)) / 1e6:.1f} MB GLB",
         "s": f"meshopt compressed. glTF validator: {vw.get('errors', '?')} errors, {vw.get('warnings', '?')} warnings"},
    ]
    notes = []
    if res.get("missing"):
        notes.append("Not opening: " + ", ".join(PART_NAMES.get(p, p) for p in res["missing"])
                     + ". Fix it in the Studio, or ask for another model.")
    for k in ("doors_note", "body_note", "spec_note", "time_limit"):
        if report.get(k):
            notes.append(str(report[k])[0].upper() + str(report[k])[1:] + ".")
    tr = report.get("trim") or {}
    if tr.get("words_not_matched"):
        notes.append(f"Trim: built the {tr.get('built')} body; “{' '.join(tr['words_not_matched'])}” matched nothing.")
    if st:
        notes.append(f"A stand-in: the catalogue has no {st.get('car')}, so “{st.get('donor_source') or st.get('donor')}” "
                     "was reshaped to its size.")
    rhd = fin.get("right_hand_drive") or {}
    if rhd.get("done"):
        notes.append("Right-hand drive: the model is left-hand drive, so its cabin is mirrored and the steering wheel "
                     f"moved across ({rhd['wheel_moved_m']:.2f} m), its badge the right way round.")
    elif rhd:
        notes.append(f"Right-hand drive asked for, not made: {rhd.get('why')}.")
    if report.get("noncommercial_left_out"):
        notes.append("A closer model exists under a non-commercial licence; it was left out because this car may be sold.")
    if closed:
        notes.append("The model is a 5-door: its rear doors are closed into the body (handles off, shut lines "
                     "covered), so it reads as the 3-door asked for.")
    cr = res.get("credit") or {}
    cab = fin.get("cabin_pack") or {}
    if cab:
        notes.append(f"The model came without a cabin: the seats, dashboard and steering wheel are from the "
                     f"“{cab.get('from')}”, fitted to this body.")
    sheet = (report.get("files") or {}).get("sheet")
    if sheet and os.path.exists(sheet):
        shutil.copyfile(sheet, os.path.join(out, "views.jpg"))
    cat = catalogue(j)
    cfg = {"title": title, "eyebrow": "ExpertCarCheck GLB machine · built " + time.strftime("%-d %b %Y"),
           "sub": f"{name}" + (f", {colour}" if colour else "") + ".", "swatch": f"rgb({srgb[0]}, {srgb[1]}, {srgb[2]})" if srgb else None,
           "facts": facts, "notes": notes, "parts": parts, "files": files, "sheet": bool(sheet and os.path.exists(sheet)),
           "lab": lab_parts(j, paint_names), "key": "car-" + re.sub(r"[^a-z0-9-]", "", str(report.get("asset") or "x").lower()),
           "catalogue": cat, "procedures": procedures(cat, opens, rear),
           "engine": {"lid": "tailgate" if rear else "bonnet"},
           "start": start_finish(asked, finish, srgb),
           "credit": {"title": cr.get("title") or "", "author": cr.get("author"), "licence": cr.get("licence"),
                      "url": cr.get("url"), "commercial": bool(cr.get("commercial")),
                      "cabin": {"title": cab.get("from"), "author": cab.get("author"), "licence": cab.get("licence"),
                                "url": cab.get("url")} if cab else None}}
    page = open(os.path.join(HERE, "page", "car.html")).read()
    page = page.replace("{{TITLE}}", html.escape(title)).replace(
        "{{CONFIG}}", json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/"))
    open(os.path.join(out, "index.html"), "w").write(page)
    return {"dir": os.path.abspath(out), "files": ["index.html"] + files + (["views.jpg"] if cfg["sheet"] else []),
            "seconds": round(time.time() - t0, 1), "title": title, "notes": notes,
            "summary": f"{title}: {facts[4]['v']}, " + ", ".join(n for _, n in parts).lower()
                       + f" open; file in {secs} s"}


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    print(json.dumps(write(json.load(open(sys.argv[1])), sys.argv[2]), indent=1))
