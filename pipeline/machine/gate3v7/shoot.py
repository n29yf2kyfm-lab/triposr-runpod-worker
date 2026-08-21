#!/usr/bin/env python3
"""shoot.py -- GATE 3 v7 render driver. Wraps gate3v6/render_job.py.

Why a wrapper: the container's Blender dies AFTER printing "Blender quit" when
a render fails (no OpenImageDenoiser), so an exit code is not evidence.  This
driver deletes every target frame first, runs Blender, then waits on
render_job's own DONE marker and asserts each expected PNG exists and is
non-trivial.  It NEVER uses pgrep/pkill -- the harness wrapper's command line
contains the pattern, so a pgrep wait loop matches itself.

Run: python3 shoot.py <job.json> [--timeout 3600]
"""
import json
import os
import subprocess
import sys
import time

G6 = "/home/user/triposr-runpod-worker/pipeline/machine/gate3v6"

job_path = sys.argv[1]
timeout = 3600
if "--timeout" in sys.argv:
    timeout = int(sys.argv[sys.argv.index("--timeout") + 1])

job = json.load(open(job_path))
outdir = job["outdir"]
name = job.get("name", "job")
os.makedirs(outdir, exist_ok=True)
marker = job.get("done_marker", os.path.join(outdir, "_DONE_%s" % name))

# stale-frame guard: every output this job claims to write is removed first,
# so a frame surviving from a previous run can never be read as a fresh one.
targets = [os.path.join(outdir, "%s.png" % v["id"]) for v in job["views"]]
for p in targets + [marker]:
    if os.path.exists(p):
        os.remove(p)

log = os.path.join(outdir, "_blender_%s.log" % name)
t0 = time.time()
with open(log, "w") as fh:
    proc = subprocess.run(
        ["blender", "-b", "--python", os.path.join(G6, "render_job.py"),
         "--", job_path],
        stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)

dt = time.time() - t0
ok = os.path.exists(marker)
print(f"blender rc={proc.returncode} {dt:.0f}s  marker={'YES' if ok else 'NO'}  log={log}")

missing = [p for p in targets if not os.path.exists(p) or os.path.getsize(p) < 2000]
if missing:
    print("MISSING/TRIVIAL FRAMES:")
    for p in missing:
        print("   ", p, os.path.getsize(p) if os.path.exists(p) else "absent")
if not ok or missing:
    print("---- last 40 log lines ----")
    print("".join(open(log).readlines()[-40:]))
    sys.exit(1)

meta = json.load(open(os.path.join(outdir, "_meta_%s.json" % name)))
for vid, m in meta["views"].items():
    ms = m.get("measured", {})
    print(f"  {vid:26s} {m['pass']:8s} az{m['az']:>4} "
          f"occ {m.get('proj_bbox_occ_x',0):.3f}x{m.get('proj_bbox_occ_y',0):.3f} "
          f"clip {ms.get('clipped_frac', float('nan')):.5f} "
          f"bg {ms.get('bg_srgb_measured','?')} exp {m['view_transform']} "
          f"{m['seconds']}s")
print("SHOOT_OK", name)
