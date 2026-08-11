#!/usr/bin/env python3
"""Build AUDIT_GN.json -- per-car verdicts for the LIVE catalogue, makes G-N.

METHOD (and what each step is and is NOT evidence for)
-----------------------------------------------------
GLAZING  glass_probe.py against the SHIPPED desktopGlbUrl, re-validated first
         against PORSCHE_GLASS.json (106/107, sole miss in the safe direction --
         identical to the score CLAUDE.md records, so the probe is unchanged).
         verdict opaque + certainty proven  -> nominated
         verdict faded / ambiguous / opaque-inferred, and every alpha_shell and
         flat_shell flag -> NOT a verdict, routed to a magenta-backlight render
         of the same shipped GLB (pipeline/qc/backlight_render.py) and decided
         by eye.  CLAUDE.md: "ambiguous must NEVER be scrapped on the probe
         alone".  Every opaque-proven nomination was ALSO confirmed by backlight
         before being written here -- a probe nominates, it does not convict.
DAMAGE   and SOFT BODY: the published poster at full resolution where one exists,
         otherwise the backlight render.  The poster is an honest witness for
         shape, panels and missing parts; it is NOT a witness for glazing (the
         render worker forces transmission=1.0 onto glass-named materials) and
         it is NOT a witness for tyre colour (documented render artefact).
TYRES    not judged.  CLAUDE.md: the glTF tyre probe scored recall 0/8 and the
         white-tyre effect is a per-corner render artefact.
"""
import json, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAT = os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json")
OUT = os.path.join(REPO, "pipeline", "ingest", "AUDIT_GN.json")
DEC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AUDIT_GN_decisions.json")


def main():
    cat = [e for e in json.load(open(CAT))
           if e.get("publicationStatus") == "approved"
           and e["make"][:1].lower() in "ghijklmn"]
    dec = json.load(open(DEC)) if os.path.exists(DEC) else {}
    rows = []
    for e in sorted(cat, key=lambda x: (x["make"].lower(), x["assetId"])):
        a = e["assetId"]
        d = dec.get(a, {})
        rows.append({
            "assetId": a,
            "make": e["make"],
            "model": e.get("model"),
            "verdict": d.get("verdict", "pass"),
            "reasons": d.get("reasons", []),
            "evidence": d.get("evidence", ""),
            "colourVariants": len(e.get("colourVariants") or {}),
            "hasEightColours": len(e.get("colourVariants") or {}) >= 8,
            "yearStart": e.get("yearStart"),
            "hasYear": e.get("yearStart") is not None,
        })
    json.dump(rows, open(OUT, "w"), indent=1)
    scrap = [r for r in rows if r["verdict"] == "scrap"]
    print(f"{len(rows)} cars: {len(rows)-len(scrap)} pass, {len(scrap)} scrap")
    p = [r for r in rows if r["verdict"] == "pass"]
    print(f"passes missing 8 colours: {sum(1 for r in p if not r['hasEightColours'])}")
    print(f"passes missing yearStart: {sum(1 for r in p if not r['hasYear'])}")


if __name__ == "__main__":
    main()
