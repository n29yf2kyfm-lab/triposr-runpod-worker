#!/usr/bin/env python3
"""build_trainset.py — assemble the Pixal3D training corpus, gated.

WHY THIS EXISTS. The plan is to fine-tune Pixal3D (TRELLIS.2-derived) on car
meshes. Pixal learns 3D from 3D: the training images are RENDERS of meshes at
known camera poses, so the corpus is MESHES, and image datasets — however many
million frames they hold — cannot supervise it.

WHY IT GATES RATHER THAN JUST LISTS. Training on junk teaches junk, and this
project has the receipts: 119 of 1,154 live cars failed on OPAQUE GLAZING alone
and 64 more were flat clay shells, all of them from the same Sketchfab pool the
public mesh corpora are drawn from. The MeshFleet authors measured the same
thing from the other side — adding their lower-quality tier took the training
set from 380 to 1,265 cars and made the model WORSE, on both a longer and a
shorter schedule. So corpus size is not the number to maximise. The number that
matters is how many cars clear the bar this catalogue already enforces.

The gates are the catalogue's own, not new ones invented for training:
  * glass_probe   — verdict "opaque" with certainty "proven" is a hard fail
                    under the owner's 2026-08-11 ruling. "ambiguous" is NOT a
                    fail; it routes to the eye, and has repeatedly saved good
                    cars (a misspelt `Widnwos`, a `Windiow`, an infotainment
                    touchscreen matching /screen/).
  * flat shell    — one baseColorFactor across every untextured material: the
                    clay signature, correct names and no colours.
  * alpha shell   — the global-alpha shell, everything BLEND at 0.25 including
                    carpaint and tyres.
  * quarantine    — publicationStatus quarantined means a human already pulled
                    this car after it went live. REJECTS.json only records what
                    was scrapped at review; the catalogue is the other half of
                    that ledger and nothing was checking it.

Reads the JSON chunk by HTTP Range, so a 40MB car costs a few KB and the whole
catalogue can be gated in minutes without downloading a single mesh.

Run: python3 build_trainset.py <out_manifest.json> [--include-quarantined]
"""
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ingest"))
import glass_probe  # noqa: E402

SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public"
CATALOGUE = f"{SB}/car-renders/catalogue.json"
OUT = sys.argv[1] if len(sys.argv) > 1 else "trainset.json"
KEEP_QUAR = "--include-quarantined" in sys.argv


def load_catalogue():
    with urllib.request.urlopen(CATALOGUE, timeout=120) as r:
        d = json.load(r)
    return d if isinstance(d, list) else d.get("entries", d.get("cars", []))


def gate(entry):
    """Return (keep, reason, detail). Never raises — an unreadable car is a
    SKIP with its reason recorded, never a silent pass. An unreadable file
    scored as 'fine' is how a bad car gets into a training set."""
    url = entry.get("desktopGlbUrl")
    aid = entry.get("assetId")
    if not url:
        return False, "no-glb", {}
    try:
        r = glass_probe.probe(None, url=url)
    except Exception as e:
        return False, "unreadable", {"error": f"{type(e).__name__}: {e}"}
    verdict = r.get("verdict")
    cert = r.get("certainty")
    detail = {"verdict": verdict, "certainty": cert,
              "flat_shell": r.get("flat_shell"),
              "alpha_shell": r.get("alpha_shell"),
              "n_materials": r.get("n_materials")}
    if r.get("flat_shell"):
        return False, "flat-shell", detail
    if r.get("alpha_shell"):
        return False, "alpha-shell", detail
    if verdict == "opaque" and cert == "proven":
        return False, "glazing-opaque-proven", detail
    return True, "pass", detail


def main():
    cat = load_catalogue()
    print(f"catalogue: {len(cat)} entries")
    pool = [e for e in cat
            if KEEP_QUAR or e.get("publicationStatus") == "approved"]
    print(f"after publicationStatus filter: {len(pool)}")

    results = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for i, (entry, out) in enumerate(
                zip(pool, ex.map(gate, pool)), 1):
            keep, reason, detail = out
            results.append({"assetId": entry.get("assetId"),
                            "make": entry.get("make"),
                            "model": entry.get("model"),
                            "url": entry.get("desktopGlbUrl"),
                            "sourceReferenceId": entry.get("sourceReferenceId"),
                            "keep": keep, "reason": reason, **detail})
            if i % 50 == 0:
                print(f"  gated {i}/{len(pool)}", flush=True)

    from collections import Counter
    tally = Counter(r["reason"] for r in results)
    keep = [r for r in results if r["keep"]]
    print("\n=== FUNNEL ===")
    print(f"  catalogue                {len(cat)}")
    print(f"  eligible by status       {len(pool)}")
    for reason, n in tally.most_common():
        print(f"    {reason:24s} {n}")
    print(f"  TRAINABLE                {len(keep)} "
          f"({100 * len(keep) / max(len(pool), 1):.1f}% of eligible)")

    json.dump({"trainable": keep, "all": results}, open(OUT, "w"), indent=1)
    print(f"\nwrote {OUT}")
    print("NOTE: these gates settle MATERIALS, not surfacing. A car can pass "
          "every one of them and still be soft — softness is the voxel-grid "
          "ceiling and no corpus fixes it.")


if __name__ == "__main__":
    main()
