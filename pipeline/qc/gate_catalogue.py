#!/usr/bin/env python3
"""gate_catalogue.py — pre-serve / CI enforcement gate for the catalogue.

Guarantees a broken colour-swap can never reach the live catalogue. Pure JSON
validation: no rendering, no network, no secrets — safe to run in CI on every
push and as a serve-time precondition.

Rule enforced (per approved entry):
  * offers colourVariants  -> MUST carry recolourAudit.status == "pass" whose
    variantsHash matches the CURRENT variants (a re-bake changes the hash and
    invalidates a stale pass). A missing, failed, or stale stamp is a violation.
  * single-neutral (no colourVariants) -> nothing to prove, always allowed.

The render verdict + stamp are produced by
  python3 pipeline/qc/recolour_audit.py <assetId> --stamp
Exit 0 = catalogue may ship. Exit 1 = violations found (listed).

Usage:
  python3 pipeline/qc/gate_catalogue.py [--catalogue PATH]
"""
import sys, os, json, hashlib, argparse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def variants_hash(cv):
    payload = json.dumps(sorted((cv or {}).items()), separators=(",", ":"))
    return hashlib.sha1(payload.encode()).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", default=os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json"))
    a = ap.parse_args()
    cat = json.load(open(a.catalogue))
    approved = [e for e in cat if e.get("publicationStatus") == "approved"]
    with_swaps = [e for e in approved if e.get("colourVariants")]

    missing, failed, stale = [], [], []
    for e in with_swaps:
        aid = e["assetId"]; st = e.get("recolourAudit")
        if not st:
            missing.append(aid)
        elif st.get("status") != "pass":
            failed.append(aid)
        elif st.get("variantsHash") != variants_hash(e.get("colourVariants")):
            stale.append(aid)

    passed = len(with_swaps) - len(missing) - len(failed) - len(stale)
    print(f"CATALOGUE GATE  approved={len(approved)}  colour-swap={len(with_swaps)}  "
          f"pass-stamped={passed}")
    for label, rows in (("NO STAMP (never audited)", missing),
                        ("FAILED audit", failed),
                        ("STALE stamp (variants changed since audit)", stale)):
        if rows:
            print(f"  {len(rows)} {label}:")
            for aid in sorted(rows):
                print(f"    - {aid}")

    if missing or failed or stale:
        print("GATE: FAIL — the above must be re-audited (--stamp) or demoted to "
              "single-neutral before this catalogue can ship.")
        sys.exit(1)
    print("GATE: PASS — every shipped colour-swap is render-verified.")
    sys.exit(0)

main()
