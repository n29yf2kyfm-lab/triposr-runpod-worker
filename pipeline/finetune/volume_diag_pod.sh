#!/bin/bash
# volume_diag_pod.sh — is the alam3d-data network volume out of space?
#
# Three eval pods in a row produced log files whose metadata looked fine
# (non-zero size, fresh mtime) but whose CONTENT read back as all-NUL. That is
# the classic signature of a filesystem that accepted the create + size update
# but had no blocks to put the data in — i.e. a FULL volume — not the pod
# "hanging". This script proves or kills that theory.
#
# Everything here logs to CONTAINER-LOCAL disk and is served from there, so the
# diagnosis itself cannot be swallowed by the thing being diagnosed.
LOCAL=/root/diag
mkdir -p "$LOCAL"
( cd "$LOCAL" && python3 -m http.server 8000 >/dev/null 2>&1 & )
exec > >(tee -a "$LOCAL/stage_b.log") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$LOCAL/status.json"; echo "===== $1 ====="; }

status df
df -h /workspace / 2>&1
echo "--- inodes:"
df -i /workspace 2>&1

status write-test
# create → fsync → drop caches on our side by reopening → read back
T=/workspace/_volume_write_test.$$
python3 - "$T" <<'PY'
import os, sys
p = sys.argv[1]
try:
    with open(p, "wb") as f:
        f.write(b"ALAM3D-WRITE-TEST\n" * 1000)
        f.flush(); os.fsync(f.fileno())
    data = open(p, "rb").read()
    nul = data.count(b"\0")
    print(f"wrote 18000 bytes, read back {len(data)} bytes, NUL bytes={nul}")
    print("VERDICT:", "WRITES-OK" if nul == 0 and len(data) == 18000 else "WRITES-BROKEN")
except Exception as e:
    print("VERDICT: WRITES-BROKEN (exception)", type(e).__name__, e)
finally:
    try: os.remove(p)
    except Exception: pass
PY

status usage
echo "--- top-level usage under /workspace (largest first):"
du -sh /workspace/* 2>/dev/null | sort -rh | head -30
echo
echo "--- alamcars breakdown:"
du -sh /workspace/alamcars/* 2>/dev/null | sort -rh | head -40

status ckpts
echo "--- Stage C / Stage D checkpoints (the eval needs to READ these):"
ls -la /workspace/alam3d_stage_c/ckpts 2>/dev/null | tail -8
ls -la /workspace/alam3d_stage_d/ckpts 2>/dev/null | tail -8
echo "--- read-back test of the newest Stage D ckpt header:"
python3 - <<'PY'
import glob, os
for pat, label in (("/workspace/alam3d_stage_c/ckpts/denoiser_ema*step*.pt", "stage C"),
                   ("/workspace/alam3d_stage_d/ckpts/denoiser_ema*step*.pt", "stage D")):
    ck = sorted(glob.glob(pat))
    if not ck:
        print(f"{label}: NO CHECKPOINT"); continue
    p = ck[-1]
    head = open(p, "rb").read(4096)
    # a torch .pt is a zip archive -> must start PK; all-NUL means the file
    # never actually made it to disk. NB: the NUL literal is bound outside the
    # f-string — a backslash escape inside one is a SyntaxError before 3.12.
    nuls = head.count(b"\x00")
    print(f"{label}: {os.path.basename(p)} {os.path.getsize(p)//1024//1024}MB "
          f"first4k-NULs={nuls}/4096 magic={head[:2]!r}")
PY

status DONE
sleep infinity
