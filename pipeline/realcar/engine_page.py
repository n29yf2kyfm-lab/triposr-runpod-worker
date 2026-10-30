#!/usr/bin/env python3
"""engine_page.py: one engine on its own, part by part, as a page. Every valve, spring, keeper, seal, gasket,
bolt and bearing shell is its own piece that comes off and goes back; the parts the owner's catalogue lists
for the engine carry their OEM numbers, and the strip-down runs in workshop order.

    python3 pipeline/realcar/engine_page.py "golf 2008 1.9 tdi" OUT_DIR

OUT_DIR gets index.html (page/engine.html with the engine's figures and catalogue parts in it). The engine is
the catalogue's (engines.look: make, model, year, and the engine named in the request). Its figures are the
maker's published ones where known (KNOWN); any other inline engine is drawn from its litres and cylinders.
The castings are drawn to those figures, not scanned: the catalogue lists parts, not their shapes.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engines  # noqa: E402

TEMPLATE = os.path.join(HERE, "page", "engine.html")

# engines whose own figures are published (metres): bore, stroke, rod length, bore spacing, piston compression
# height; the valvetrain, what turns the injection, and what the catalogue cannot say (the turbo)
KNOWN = {
    ("volkswagen", 1.9, "diesel"): {
        "name": "1.9 TDI", "bore": 0.0795, "stroke": 0.0955, "rod": 0.144, "pitch": 0.088, "pin_to_crown": 0.047,
        "valves": 2, "injection": "pump", "turbo": True, "firing": [1, 3, 4, 2],
        "facts": "1,896 cc, 79.5 mm bore, 95.5 mm stroke, 144 mm rods. Two valves a cylinder on one overhead "
                 "camshaft with hydraulic followers. The toothed belt turns the camshaft, the injection pump and "
                 "the water pump; a chain under the crank turns the oil pump. Direct injection, a glow plug a "
                 "cylinder, a variable-vane turbo. Firing order 1-3-4-2.",
    },
}
FIRING = {3: [1, 2, 3], 4: [1, 3, 4, 2], 5: [1, 2, 4, 5, 3], 6: [1, 5, 3, 6, 2, 4]}


def resolve(request, idx):
    """The make and model words a request names, from the catalogue's makes and models."""
    q = engines.norm(request)
    words = q.split()
    keep = [w for w in words if not re.fullmatch(r"(19|20)\d\d", w) and not engines.asked_engine(w)
            and not re.fullmatch(r"\d", w)]
    makes = idx["vehicles"]
    text = " ".join(keep)
    for alias, mk in sorted(engines.MAKE_ALIAS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(alias)}\b", text) and mk in makes:
            return mk, re.sub(rf"\b{re.escape(alias)}\b", " ", text).strip()
    for mk in sorted(makes, key=len, reverse=True):
        if re.search(rf"\b{re.escape(mk)}\b", text):
            return mk, re.sub(rf"\b{re.escape(mk)}\b", " ", text).strip()
    hits = [(mk, engines.find_model(makes[mk], text)) for mk in makes]
    hits = [(mk, ms) for mk, ms in hits if ms]
    exact = [mk for mk, ms in hits if ms[0] == text]
    if exact or hits:
        return (exact or [hits[0][0]])[0], text
    return None, text


def dims(make, sp):
    """The engine's figures: KNOWN's, else a square engine of its litres and cylinders."""
    known = KNOWN.get((make, round(sp.get("litres") or 0, 1), sp.get("fuel")))
    if known:
        return {**known, "cylinders": sp["cylinders"], "known": True}
    n = sp.get("cylinders") or 4
    per = (sp.get("litres") or 2.0) / n / 1000
    bore = round((4 * per / 3.14159) ** (1 / 3), 4)
    return {"name": engines.describe(sp), "bore": bore, "stroke": bore, "rod": round(bore * 1.75, 4),
            "pitch": round(bore * 1.11, 4), "pin_to_crown": round(bore * 0.58, 4), "valves": 2,
            "injection": "pump" if sp.get("fuel") == "diesel" else "port", "turbo": sp.get("fuel") == "diesel",
            "firing": FIRING.get(n, list(range(1, n + 1))), "cylinders": n, "known": False,
            "facts": f"Drawn from its {sp.get('litres')} litres and {n} cylinders (bore and stroke equal): this "
                     f"engine's own figures are not in the machine."}


def config(request, idx=None):
    idx = idx or engines.index()
    year = next((int(w) for w in engines.norm(request).split() if re.fullmatch(r"(19|20)\d\d", w)), None)
    mk, model = resolve(request, idx)
    if not mk:
        raise SystemExit(f"engine_page: no make or model in the catalogue for {request!r}")
    r = engines.look(mk, model, year, idx=idx, engine=engines.asked_engine(request))
    if not r:
        raise SystemExit(f"engine_page: the catalogue has no engine for {mk} {model} {year or ''}")
    sp = r["spec"]
    if not sp or sp.get("electric"):
        raise SystemExit("engine_page: an electric car has no engine to strip")
    if sp.get("layout") != "inline" or sp.get("fuel") != "diesel":
        raise SystemExit(f"engine_page: this page draws inline diesels so far; this one is a {engines.describe(sp)}")
    m = r["matched"]
    return {"request": request, "make": mk.title() if mk not in ("bmw", "mg", "gmc") else mk.upper(),
            "model": m["models"][0].title() if m["models"] else model.title(), "year": m.get("year"),
            "asked_year": year, "engine": r["engine"], "words": r["words"], "built_words": r.get("built_words"),
            "construction": r.get("construction"), "spec": sp, "dims": dims(mk, sp), "parts": r["parts"],
            "part_count": r["part_count"]}


def write(cfg, out):
    os.makedirs(out, exist_ok=True)
    page = open(TEMPLATE).read()
    data = json.dumps(cfg).replace("</", "<\\/")
    page = page.replace("/*CONFIG*/{}", data, 1)
    title = f"{cfg['make']} {cfg['dims']['name']} engine"
    page = page.replace("<title>Engine</title>", f"<title>{title}</title>", 1)
    path = os.path.join(out, "index.html")
    with open(path, "w") as fh:
        fh.write(page)
    return path


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    cfg = config(sys.argv[1])
    path = write(cfg, sys.argv[2])
    print(json.dumps({"index": path, "engine": cfg["engine"], "words": cfg["words"], "year": cfg["year"],
                      "parts_listed": cfg["part_count"], "figures": cfg["dims"]["name"]}, indent=1))


if __name__ == "__main__":
    main()
