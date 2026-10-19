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


def _name(make, model):
    mk = "-".join(CAPS.get(w, w.capitalize()) for w in str(make or "").split("-"))
    md = " ".join(CAPS.get(w.lower(), w if any(c.isdigit() for c in w) or w.isupper() else w.capitalize())
                  for w in str(model or "").replace(str(make or ""), "").split())
    return f"{mk} {md}".strip()


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
    every = {m.get("name") or "" for m in mats}
    wheels = {"names": rims, "where": "wheel"} if rims else \
        {"names": sorted(m for m in every if m and RIM.search(m) and not TYRE.search(m)), "where": "any"}
    calipers = {"names": sorted(m for m in every if m and CALIPER.search(m) and not NOT_CALIPER.search(m)), "where": "any"}
    body = {"names": sorted(set(paint_names) & every), "where": "body"}
    return {"wheels": wheels, "calipers": calipers, "body": body}


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
    except Exception:
        paint_names = []
    if fin.get("paint_set"):
        paint_names = list(paint_names) + [fin["paint_set"].get("material")]

    colour = asked.get("colour")
    srgb = (fin.get("paint_set") or {}).get("srgb")
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
    for k in ("doors_note", "spec_note", "time_limit"):
        if report.get(k):
            notes.append(str(report[k])[0].upper() + str(report[k])[1:] + ".")
    tr = report.get("trim") or {}
    if tr.get("words_not_matched"):
        notes.append(f"Trim: built the {tr.get('built')} body; “{' '.join(tr['words_not_matched'])}” matched nothing.")
    if st:
        notes.append(f"A stand-in: the catalogue has no {st.get('car')}, so “{st.get('donor_source') or st.get('donor')}” "
                     "was reshaped to its size.")
    if report.get("noncommercial_left_out"):
        notes.append("A closer model exists under a non-commercial licence; it was left out because this car may be sold.")
    cr = res.get("credit") or {}
    sheet = (report.get("files") or {}).get("sheet")
    if sheet and os.path.exists(sheet):
        shutil.copyfile(sheet, os.path.join(out, "views.jpg"))
    cfg = {"title": title, "eyebrow": "ExpertCarCheck GLB machine · built " + time.strftime("%-d %b %Y"),
           "sub": f"{name}" + (f", {colour}" if colour else "") + ".", "swatch": f"rgb({srgb[0]}, {srgb[1]}, {srgb[2]})" if srgb else None,
           "facts": facts, "notes": notes, "parts": parts, "files": files, "sheet": bool(sheet and os.path.exists(sheet)),
           "lab": lab_parts(j, paint_names), "key": "car-" + re.sub(r"[^a-z0-9-]", "", str(report.get("asset") or "x").lower()),
           "credit": {"title": cr.get("title") or "", "author": cr.get("author"), "licence": cr.get("licence"),
                      "url": cr.get("url"), "commercial": bool(cr.get("commercial"))}}
    page = open(os.path.join(HERE, "page", "car.html")).read()
    page = page.replace("{{TITLE}}", html.escape(title)).replace(
        "{{CONFIG}}", json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/"))
    open(os.path.join(out, "index.html"), "w").write(page)
    return {"dir": os.path.abspath(out), "files": ["index.html"] + files + (["views.jpg"] if cfg["sheet"] else []),
            "seconds": round(time.time() - t0, 1)}


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    print(json.dumps(write(json.load(open(sys.argv[1])), sys.argv[2]), indent=1))
