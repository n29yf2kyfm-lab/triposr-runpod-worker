#!/usr/bin/env python3
"""gap_diag.py — WHY is each kept shape absent from training?

Run on the training volume (stage_a_backfill_pod.sh fetches it to /tmp).
Joins the human cull verdict against what is physically on the volume and in
the merged metadata, classifies every keep, and uploads the report. Run twice:

    gap_diag.py before   -> writes/uploads the report, always exits 0
    gap_diag.py after    -> same, then exits 1 unless the trainable-keep
                            count IMPROVED on the before-report (or was
                            already complete) — the pod's DONE gate.

"Trainable" here is a PROXY for what the trainer admits: a keep with a mesh
dump, conditioning renders, a shape latent and an ss latent, and (where a
token-count column exists) a token count within the trainer's max_tokens cap.
The trainer's own "Total instances" line remains the ground truth; this proxy
exists so the gap can be attributed per-shape and per-cause.
"""
import glob
import json
import os
import sys
import time
import urllib.request

import pandas as pd

ROOT = "/workspace/alamcars"
SUPA = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
VERDICT_URL = f"{SUPA}/car-meshes/audit/train/CULL_VERDICT.json"
MAX_TOKENS = 32768          # trainer config: dataset.args.max_tokens
SB_KEY = os.environ.get("SB_KEY", "")


def sb_get(url):
    rq = urllib.request.Request(url + f"?cb={int(time.time())}")
    for h, v in (("apikey", SB_KEY), ("Authorization", "Bearer " + SB_KEY)):
        if SB_KEY:
            rq.add_header(h, v)
    return urllib.request.urlopen(rq, timeout=120).read()


def sb_put(path, data):
    if not SB_KEY:
        print(f"  upload skipped (no SB_KEY): {path}")
        return
    rq = urllib.request.Request(f"{SUPA}/{path}", data=data, method="POST")
    for h, v in (("apikey", SB_KEY), ("Authorization", "Bearer " + SB_KEY),
                 ("Content-Type", "application/json"), ("x-upsert", "true")):
        rq.add_header(h, v)
    try:
        urllib.request.urlopen(rq, timeout=120).read()
        print(f"  uploaded {path}")
    except Exception as e:
        print(f"  UPLOAD FAILED {path}: {type(e).__name__} {str(e)[:80]}")


def file_index(subdir):
    """sha256 set from the FIRST-sorted latent-name dir only — the same one
    the stage scripts' pick() hands the trainer. Indexing the union of all
    dirs counts latents the trainer never opens (council reviewer 1, #4)."""
    dirs = sorted(glob.glob(f"{ROOT}/{subdir}/*/"))
    out = set()
    if not dirs:
        return out
    if len(dirs) > 1:
        print(f"  note: {len(dirs)} {subdir} dirs; indexing only {dirs[0]}")
    for p in glob.glob(dirs[0] + "*"):
        if os.path.isfile(p):
            out.add(os.path.basename(p).split(".")[0])
    return out


def truthy(v):
    return str(v).lower() in ("true", "1", "1.0")


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "before"
    verdict = json.loads(sb_get(VERDICT_URL))
    keeps = [r["sha256"] for r in verdict if r.get("verdict") == "keep"]
    print(f"cull verdict: {len(verdict)} rows, {len(keeps)} keeps")

    m = pd.read_csv(f"{ROOT}/metadata.csv")
    m = m.set_index("sha256", drop=False)
    shape_lat = file_index("shape_latents")
    ss_lat = file_index("ss_latents")
    print(f"volume: {len(shape_lat)} shape latents, {len(ss_lat)} ss latents, "
          f"{len(m)} metadata rows")

    # token-count column, if any encoder recorded one. Name varies by toolkit
    # version, so find it rather than assert it.
    tok_cols = [c for c in m.columns if "token" in c.lower()]
    print(f"token columns found: {tok_cols or 'none'}")
    # flag columns are DISCOVERED and printed, not silently assumed: if the
    # toolkit names them differently, every keep would misclassify as
    # no_mesh_dump and the whole report would lie about the gap's cause.
    flag_cols = [c for c in m.columns
                 if any(k in c.lower() for k in ("dump", "render", "encod", "voxel"))]
    print(f"flag columns found: {flag_cols or 'NONE'}")
    if not any("dump" in c.lower() for c in m.columns):
        print("FATAL: no mesh-dump flag column in metadata — cause attribution "
              "would be fiction. Refusing to report."); sys.exit(1)

    causes = {}
    for sha in keeps:
        if sha not in m.index:
            causes[sha] = "no_metadata_row"
            continue
        row = m.loc[sha]
        if not truthy(row.get("mesh_dumped", row.get("dumped", False))):
            causes[sha] = "no_mesh_dump"
        elif not truthy(row.get("cond_rendered", False)):
            causes[sha] = "no_cond_render"
        elif sha not in shape_lat:
            causes[sha] = "no_shape_latent"
        elif sha not in ss_lat:
            causes[sha] = "no_ss_latent"
        else:
            over = False
            for c in tok_cols:
                try:
                    if float(row[c]) > MAX_TOKENS:
                        over = True
                except (TypeError, ValueError):
                    pass
            causes[sha] = "over_token_cap" if over else "trainable"

    counts = {}
    for c in causes.values():
        counts[c] = counts.get(c, 0) + 1
    trainable = counts.get("trainable", 0)
    print(f"--- gap report ({phase}) ---")
    for c in sorted(counts, key=counts.get, reverse=True):
        print(f"  {c:<18} {counts[c]}")
    print(f"  trainable keeps: {trainable} of {len(keeps)}")
    print("  NOTE: 'trainable' is a file/flag proxy; the trainer's own "
          "'Total instances' banner is the ground truth")

    report = {"phase": phase, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "keeps": len(keeps), "counts": counts, "trainable": trainable,
              "max_tokens": MAX_TOKENS, "token_columns": tok_cols,
              "causes": causes}
    local = f"{ROOT}/gap_report_{phase}.json"
    with open(local, "w") as f:
        json.dump(report, f, indent=1)
    sb_put(f"car-meshes/audit/train/gap_report_{phase}.json",
           json.dumps(report, indent=1).encode())

    if phase == "after":
        try:
            before = json.load(open(f"{ROOT}/gap_report_before.json"))
        except Exception:
            print("FATAL: no before-report to compare against"); sys.exit(1)
        b = before.get("trainable", 0)
        if trainable >= len(keeps):
            print(f"complete: all {len(keeps)} keeps trainable"); return
        if trainable > b:
            print(f"progress: trainable keeps {b} -> {trainable}"); return
        # A residual gap made ENTIRELY of causes re-running cannot fix is a
        # correct diagnosis, not a failure — the pod's own header says token-
        # capped shapes never become trainable. FATALing on that made "did
        # everything right" indistinguishable from "did nothing" in
        # status.json (council reviewer 1, #6).
        unfixable = counts.get("over_token_cap", 0)
        if trainable + unfixable >= len(keeps):
            print(f"complete-with-permanent-gap: {trainable} trainable, "
                  f"{unfixable} over the token cap (unfixable by re-running). "
                  f"Nothing left for a backfill to do."); return
        print(f"FATAL: no progress — trainable keeps {b} -> {trainable}, and "
              f"{len(keeps) - trainable - unfixable} keeps remain in fixable "
              f"causes. The backfill ran but fixed nothing; see the causes above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
