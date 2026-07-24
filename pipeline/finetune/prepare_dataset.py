#!/usr/bin/env python3
"""prepare_dataset.py — stage the curated car library as a TRELLIS.2 training
subset ("AlamCars") for the Alam-3D fine-tune.

The upstream data_toolkit (pinned commit 75fbf01) is metadata-driven: every
step reads <root>/metadata.csv keyed on sha256, resolves the raw asset via
local_path under <root>/raw/, and imports a small datasets/<SUBSET>.py module.
This script produces exactly that contract from our own catalogue:

  <root>/raw/<sha256>.glb        the assets (downloaded from our Supabase)
  <root>/metadata.csv            sha256,file_identifier,local_path,+provenance
  <root>/AlamCars.py             dataset shim -> copy into TRELLIS.2/datasets/

After this, the standard toolkit pipeline runs unchanged on a GPU/CPU pod:
  python data_toolkit/dump_mesh.py    AlamCars --root <root>
  python data_toolkit/dump_pbr.py     AlamCars --root <root>
  python data_toolkit/dual_grid.py    AlamCars --root <root> --resolution 256,512,1024
  python data_toolkit/voxelize_pbr.py AlamCars --root <root>
  python data_toolkit/render_cond.py  AlamCars --root <root> --num_views 16
  python data_toolkit/encode_*_latent.py ...
(The shim's surface is deliberately minimal; validate on the pod before the
long steps — build_metadata/download are NOT needed since we pre-write
metadata.csv and place files locally.)

CPU + network only — no GPU cost. Resumable; re-runs skip existing assets.

Usage:
  python3 pipeline/finetune/prepare_dataset.py --root /workspace/alamcars \
      [--catalogue platform/catalogue/catalogue.v2.json] [--limit N] [--min-kb 150]
"""
import argparse, csv, hashlib, json, os, sys, urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SHIM = '''"""AlamCars — curated ExpertCarCheck car library as a TRELLIS.2 subset.
metadata.csv and raw/ are pre-built by pipeline/finetune/prepare_dataset.py;
there is nothing to crawl or download.
"""
import os
import pandas as pd


def get_metadata(root, **kwargs):
    return pd.read_csv(os.path.join(root, 'metadata.csv'))


def download(metadata, output_dir, **kwargs):
    # assets are already local under raw/ — nothing to download
    return metadata.assign(local_path=metadata['local_path'])
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="dataset root to create")
    ap.add_argument("--catalogue", default=os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json"))
    ap.add_argument("--limit", type=int, default=0, help="stop after N assets (0 = all)")
    ap.add_argument("--min-kb", type=int, default=150, help="skip suspiciously small GLBs")
    a = ap.parse_args()

    raw = os.path.join(a.root, "raw")
    os.makedirs(raw, exist_ok=True)
    cat = [e for e in json.load(open(a.catalogue))
           if e.get("publicationStatus") == "approved" and e.get("desktopGlbUrl")]
    if a.limit:
        cat = cat[:a.limit]

    meta_path = os.path.join(a.root, "metadata.csv")
    done = {}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            for row in csv.DictReader(f):
                done[row["file_identifier"]] = row

    rows = list(done.values())
    added = skipped = failed = 0
    for e in cat:
        aid = e["assetId"]
        if aid in done and os.path.exists(os.path.join(raw, done[aid]["local_path"])):
            skipped += 1
            continue
        try:
            data = urllib.request.urlopen(
                urllib.request.Request(e["desktopGlbUrl"], headers={"User-Agent": "Mozilla/5.0"}),
                timeout=120).read()
        except Exception as ex:
            print(f"  FAIL {aid}: {str(ex)[:80]}"); failed += 1
            continue
        if len(data) < a.min_kb * 1024:
            print(f"  SKIP {aid}: only {len(data)//1024}KB"); failed += 1
            continue
        sha = hashlib.sha256(data).hexdigest()
        local = f"{sha}.glb"
        open(os.path.join(raw, local), "wb").write(data)
        rows.append({"sha256": sha, "file_identifier": aid, "local_path": local,
                     "make": e.get("make"), "model": e.get("model"),
                     "licence": e.get("licence"), "source_url": e.get("sourceUrl")})
        added += 1
        print(f"  ok  {aid} -> {sha[:12]} ({len(data)//1024}KB)")

    cols = ["sha256", "file_identifier", "local_path", "make", "model", "licence", "source_url"]
    with open(meta_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in cols})
    open(os.path.join(a.root, "AlamCars.py"), "w").write(SHIM)

    print(f"\nALAMCARS_DATASET root={a.root} assets={len(rows)} "
          f"(+{added} new, {skipped} kept, {failed} failed)")
    print("next: copy AlamCars.py into TRELLIS.2/datasets/ on the pod, then run "
          "the data_toolkit steps in the header.")


if __name__ == "__main__":
    main()
