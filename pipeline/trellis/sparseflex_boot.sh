#!/usr/bin/env bash
# sparseflex_boot.sh — LEG A of the representation-vs-generation experiment.
#
# TripoSF / SparseFlex (VAST-AI, MIT) is NOT a generator. It is a 1024^3
# sparse-voxel mesh-in / mesh-out reconstruction VAE. Feeding it a car that is
# ALREADY SHARP separates two failures this project has conflated for months:
#   * "the model cannot imagine sharp panels"  (generation), versus
#   * "the representation cannot hold them"    (representation).
# If a mesh WITH shut lines comes back WITHOUT them, then every voxel-grid
# generator in this family is capped by its representation and the
# open-source surfacing question is closed. If it comes back sharp, the
# ceiling was always the conditioning.
#
# NO `set -x` ANYWHERE IN THIS FILE, DELIBERATELY. On 2026-08-18 xtrace in a
# bootstrap echoed the Authorization header into a PUBLIC bucket log and
# SB_KEY had to be rotated. Every stage prints its own marker instead.
export DEBIAN_FRONTEND=noninteractive
export PYTHONUNBUFFERED=1
LOG=/workspace/boot.log
mkdir -p /workspace
exec > >(tee -a "$LOG") 2>&1

SB="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE="${ST_PRE:-car-meshes/staging/sharptest}"
RUN="${ST_RUN:-runA}"

report()  { curl -s -X POST -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
              -H "x-upsert: true" -H "Content-Type: text/plain" \
              --data-binary @"$LOG" "$SB/$PRE/${RUN}_log.txt" >/dev/null 2>&1 || true; }
sb_file() { local code
            code=$(curl -s -o /tmp/put.out -w "%{http_code}" -X POST \
              -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
              -H "x-upsert: true" -H "Content-Type: application/octet-stream" \
              --data-binary @"$2" "$SB/$PRE/$1")
            echo "UPLOAD $1 -> HTTP $code ($(stat -c%s "$2") bytes)"
            [ "$code" = "200" ] || cat /tmp/put.out; }
sb_get()  { curl -s -f -o "$2" -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
              "$SB/$PRE/$1"; }
stage()   { echo "=== STAGE:$1 ==="; report; }
die()     { echo "=== FAIL:$1 ==="; report; sleep infinity; }

# ---------------------------------------------------------------- POD FUSE --
# The ONLY ceiling that survives the operator's own death. This container has
# restarted mid-run today, and a 2026-08-13 pod billed unwatched for 7h10m
# ($3.15) after the watcher died. The launcher ALSO deletes the pod; this is
# the belt to that pair of braces.
#
# CLAUDE.md records that the RunPod-INJECTED in-pod key could not delete its
# own pod via REST (the pc41 run), so this uses the ACCOUNT key passed in env
# and tries runpodctl as well. It is never echoed — there is no xtrace here.
FUSE_S="${ST_FUSE_S:-2700}"
(
  sleep "$FUSE_S"
  echo "=== FUSE: ${FUSE_S}s elapsed — self-terminating ==="
  report
  runpodctl remove pod "$RUNPOD_POD_ID" >/dev/null 2>&1 || true
  curl -s -X DELETE -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
       "https://rest.runpod.io/v1/pods/${RUNPOD_POD_ID}" >/dev/null 2>&1 || true
) &
echo "fuse armed: ${FUSE_S}s"

stage boot
nvidia-smi || die NO_GPU
python3 -c "import torch;print('torch',torch.__version__,'cuda',torch.version.cuda,torch.cuda.get_device_name(0),round(torch.cuda.get_device_properties(0).total_memory/2**30,1),'GB')" || die TORCH_BROKEN
TORCH_BEFORE=$(python3 -c "import torch;print(torch.__version__)")
echo "TORCH_BEFORE=$TORCH_BEFORE"
df -h /workspace | tail -1

stage fetch_input
# Fetch through the AUTHED endpoint, never the public URL: the public CDN has
# served STALE objects to a pod before (2026-08-18 Hi3DGen run).
sb_get INPUT.glb /workspace/INPUT.glb || die FETCH_INPUT
ls -l /workspace/INPUT.glb
echo "sha256 $(sha256sum /workspace/INPUT.glb | cut -d' ' -f1)"
[ "$(sha256sum /workspace/INPUT.glb | cut -d' ' -f1)" = "$ST_INPUT_SHA" ] \
  || die INPUT_SHA_MISMATCH
echo "input sha matches the pre-registered baseline"

stage clone
cd /workspace
git clone --depth 1 https://github.com/VAST-AI-Research/TripoSF.git || die CLONE
cd TripoSF && ls

stage apt
apt-get -qq update >/dev/null 2>&1
# open3d needs libGL + libgomp even for headless voxelisation (pymeshlab's
# libOpenGL lesson, same class).
apt-get -qq install -y libgl1 libgomp1 libglib2.0-0 >/dev/null 2>&1
echo "apt ok"

stage deps
# TORCH GUARD, documented trap: anything that MOVES torch breaks every
# extension compiled against it. Install with the version pinned out of the
# resolver's reach, then ASSERT.
# SPLIT, because one bad package takes the whole `pip install` line with it.
# Attempt 1 put open3d on the same line as trimesh/omegaconf/safetensors and
# open3d aborted the command, so NONE of them installed and the failure
# surfaced two lines later as "No module named 'open3d'" — a misleading name
# for a resolver error.
pip install -q --no-cache-dir "numpy<2" trimesh==4.5.3 omegaconf==2.3.0 \
    safetensors easydict jaxtyping 2>&1 | tail -5 || die PIP_SMALL
python3 -c "import trimesh,numpy,omegaconf,safetensors,easydict,jaxtyping;print('base ok tm',trimesh.__version__,'np',numpy.__version__)" || die BASE_IMPORT

# open3d 0.18 pulls dash -> flask -> blinker, and this image carries a
# DISTUTILS-installed blinker 1.4 from apt that pip refuses to uninstall:
#   "error: uninstall-distutils-installed-package ... Cannot uninstall
#    blinker 1.4 ... would lead to only a partial uninstall"
# `--ignore-installed` makes pip write fresh copies into site-packages instead
# of trying to remove the apt one. Measured: this is the exact and only reason
# attempt 1 died.
pip install -q --no-cache-dir --ignore-installed "numpy<2" open3d==0.18.0 2>&1 | tail -8
python3 -c "import open3d;print('o3d',open3d.__version__)" >/tmp/o3d.txt 2>&1
O3DRC=$?; cat /tmp/o3d.txt
if [ "$O3DRC" != "0" ]; then
  echo "open3d import failed — retrying without its dependency tree"
  pip install -q --no-cache-dir --no-deps --ignore-installed open3d==0.18.0 2>&1 | tail -5
  python3 -c "import numpy;assert numpy.__version__[0]=='1',numpy.__version__;print('numpy pinned',numpy.__version__)" || die NUMPY2
  python3 -c "import open3d;print('o3d(no-deps)',open3d.__version__)" || die O3D_IMPORT
fi
# Prove the THREE open3d entry points TripoSF's preprocessing actually calls,
# not merely that the package imports. A gate nobody tested is a gate that does
# not exist.
python3 - <<'PY' || die O3D_API
import numpy as np, open3d as o3d
m = o3d.geometry.TriangleMesh(
    o3d.utility.Vector3dVector(np.array([[-.3,-.3,-.3],[.3,-.3,-.3],[0,.3,.2]])),
    o3d.utility.Vector3iVector(np.array([[0,1,2]])))
g = o3d.geometry.VoxelGrid.create_from_triangle_mesh_within_bounds(
    m, voxel_size=1/64., min_bound=[-.5]*3, max_bound=[.5]*3)
p = o3d.geometry.VoxelGrid.create_from_point_cloud_within_bounds(
    o3d.geometry.PointCloud(o3d.utility.Vector3dVector(np.random.rand(64,3)-.5)),
    voxel_size=1/64., min_bound=[-.5]*3, max_bound=[.5]*3)
m.compute_triangle_normals()
print("o3d API ok: mesh voxels", len(g.get_voxels()),
      "point voxels", len(p.get_voxels()),
      "tri normals", np.asarray(m.triangle_normals).shape)
PY

# torch-scatter must match the torch BUILD STRING exactly; derive it rather
# than assuming +cu121 (the image is a cuda12.4.1 build).
PYG_URL="https://data.pyg.org/whl/torch-${TORCH_BEFORE}.html"
echo "torch-scatter index: $PYG_URL"
pip install -q --no-cache-dir torch-scatter -f "$PYG_URL" 2>&1 | tail -5
python3 -c "import torch_scatter;print('torch_scatter ok',torch_scatter.__version__)" \
  || { echo "pyg index miss — trying +cu121 page"
       pip install -q --no-cache-dir torch-scatter -f "https://data.pyg.org/whl/torch-$(python3 -c 'import torch;print(torch.__version__.split("+")[0])')+cu121.html" 2>&1 | tail -5
       python3 -c "import torch_scatter;print('torch_scatter ok (cu121)')" || die TORCH_SCATTER; }

pip install -q --no-cache-dir spconv-cu121 2>&1 | tail -3 || die PIP_SPCONV
python3 -c "import spconv.pytorch as spc;print('spconv ok')" || die SPCONV_IMPORT

TORCH_AFTER=$(python3 -c "import torch;print(torch.__version__)")
echo "TORCH_AFTER=$TORCH_AFTER"
[ "$TORCH_BEFORE" = "$TORCH_AFTER" ] || { echo "deps MOVED torch — repinning"
  pip install -q --no-cache-dir --force-reinstall "torch==$TORCH_BEFORE" 2>&1 | tail -3; }
python3 -c "import torch;assert torch.cuda.is_available();print('cuda ok',torch.__version__)" || die TORCH_CLOBBERED

stage attention
# TripoSF is TRELLIS-derived: sparse attention accepts ONLY 'xformers' or
# 'flash_attn' and RAISES on anything else (modules/sparse/__init__.py). Our
# config is attn_mode=swin, so the reachable calls are exactly
# flash_attn_qkvpacked_func and flash_attn_varlen_qkvpacked_func.
#
# Try the real xformers first. If its wheel does not match this torch, fall
# back to a SHIM that provides those two functions on torch SDPA — exact
# attention either way, and the shim SELF-TESTS numerically below before any
# GPU minute is spent on inference. flash-attn is never built from source
# (30+ minutes, the recorded lesson).
ATTN_OK=""
pip install -q --no-cache-dir --no-deps xformers==0.0.27.post2 2>&1 | tail -3
# `if cmd | tail` tests TAIL's status, which is ALWAYS 0 — the documented
# PIPESTATUS trap, which is easy to write by accident even while quoting it.
# Redirect to a file and test the real exit code.
python3 -c "
import torch, xformers, xformers.ops as xops
q=torch.randn(1,8,4,16,device='cuda',dtype=torch.float16)
o=xops.memory_efficient_attention(q,q,q)
assert o.shape==q.shape
print('xformers ok', xformers.__version__)
" >/tmp/xf.txt 2>&1
XFRC=$?
tail -3 /tmp/xf.txt
[ "$XFRC" = "0" ] && ATTN_OK="xformers"

if [ -z "$ATTN_OK" ]; then
  echo "xformers unusable on this torch — installing the SDPA shim"
  pip uninstall -q -y xformers 2>&1 | tail -2
  mkdir -p /workspace/shim/flash_attn
  cat > /workspace/shim/flash_attn/__init__.py <<'PYSHIM'
"""Minimal exact-attention stand-in for flash_attn, on torch SDPA.

Only the two entry points TripoSF's swin path can reach are provided. SDPA and
FlashAttention both compute EXACT softmax attention, so this is a packing
change, not an approximation — and the packing is unit-tested against a naive
reference before it is used (see the self-test in sparseflex_boot.sh).
"""
import torch
import torch.nn.functional as F

__version__ = "sdpa-shim-1"


def _sdpa(q, k, v, softmax_scale=None):
    # q,k,v: [B, N, H, C] -> SDPA wants [B, H, N, C]
    q, k, v = (t.transpose(1, 2) for t in (q, k, v))
    o = F.scaled_dot_product_attention(q, k, v, scale=softmax_scale)
    return o.transpose(1, 2)


def flash_attn_qkvpacked_func(qkv, dropout_p=0.0, softmax_scale=None,
                              causal=False, **kw):
    assert not causal and dropout_p == 0.0, "shim covers inference only"
    q, k, v = qkv.unbind(dim=2)               # each [B, N, H, C]
    return _sdpa(q, k, v, softmax_scale)


def flash_attn_varlen_qkvpacked_func(qkv, cu_seqlens, max_seqlen,
                                     dropout_p=0.0, softmax_scale=None,
                                     causal=False, **kw):
    """qkv: [M, 3, H, C] packed across variable-length sequences.

    cu_seqlens is the cumulative offsets tensor, length S+1. Each segment is
    attended independently, which is exactly what the block-diagonal mask in
    the xformers branch does.
    """
    assert not causal and dropout_p == 0.0, "shim covers inference only"
    cs = cu_seqlens.tolist() if torch.is_tensor(cu_seqlens) else list(cu_seqlens)
    outs = []
    for a, b in zip(cs[:-1], cs[1:]):
        if b <= a:
            continue
        seg = qkv[a:b]                        # [n, 3, H, C]
        q, k, v = seg.unbind(dim=1)           # each [n, H, C]
        o = _sdpa(q[None], k[None], v[None], softmax_scale)[0]
        outs.append(o)
    return torch.cat(outs, dim=0)             # [M, H, C]
PYSHIM
  export PYTHONPATH="/workspace/shim:$PYTHONPATH"
  ATTN_OK="flash_attn(shim)"
  # SELF-TEST. A safety mechanism that has not been observed to fire is not a
  # safety mechanism (council audit 2026-08-12). Both entry points are checked
  # against a naive reference, on GPU, in fp16, before inference.
  python3 - <<'PY' || die SHIM_SELFTEST
import torch, flash_attn
torch.manual_seed(0)
def ref(q,k,v):
    s=(q.float()@k.float().transpose(-1,-2))/ (q.shape[-1]**0.5)
    return (s.softmax(-1)@v.float())
B,N,H,C=2,37,4,32
qkv=torch.randn(B,N,3,H,C,device='cuda',dtype=torch.float16)
out=flash_attn.flash_attn_qkvpacked_func(qkv)
q,k,v=[t.transpose(1,2) for t in qkv.unbind(2)]
exp=ref(q,k,v).transpose(1,2)
e1=(out.float()-exp).abs().max().item()
lens=[11,5,23]; cu=torch.tensor([0,11,16,39],device='cuda',dtype=torch.int32)
p=torch.randn(39,3,H,C,device='cuda',dtype=torch.float16)
o2=flash_attn.flash_attn_varlen_qkvpacked_func(p,cu,max(lens))
chunks=[]
for a,b in zip([0,11,16],[11,16,39]):
    q2,k2,v2=[t[None].transpose(1,2) for t in p[a:b].unbind(1)]
    chunks.append(ref(q2,k2,v2).transpose(1,2)[0])
e2=(o2.float()-torch.cat(chunks,0)).abs().max().item()
print(f"SHIM SELFTEST packed_max_err={e1:.5f} varlen_max_err={e2:.5f} shape={tuple(out.shape)}/{tuple(o2.shape)}")
assert e1 < 2e-2 and e2 < 2e-2, "shim disagrees with the reference"
print("SHIM SELFTEST PASS")
PY
fi
echo "ATTENTION BACKEND = $ATTN_OK"
export ATTN_BACKEND=flash_attn
[ "$ATTN_OK" = "xformers" ] && export ATTN_BACKEND=xformers
export SPARSE_BACKEND=spconv
export SPCONV_ALGO=native

stage preflight_all
# ATTEMPT 3 reached the weights stage after 12 paid minutes and died on a module
# that had never been installed. Every module and file operation the REMAINING
# stages depend on is now proven HERE, in one cheap check, before another paid
# minute is spent. This is the project's own "prove the gate fires" rule turned
# on my own script's dependencies — three of four failures so far have been my
# install list, not the model.
python3 - <<'PFA' || die PREFLIGHT_IMPORTS
import importlib, sys
need = ["torch", "numpy", "trimesh", "open3d", "omegaconf", "safetensors",
        "easydict", "jaxtyping", "torch_scatter", "spconv.pytorch", "xformers.ops"]
miss = []
for m in need:
    try:
        importlib.import_module(m)
    except Exception as e:
        miss.append("%s: %s: %s" % (m, type(e).__name__, e))
print("preflight imports:", len(need) - len(miss), "/", len(need), "ok")
if miss:
    print("MISSING:")
    for x in miss:
        print("  ", x)
    sys.exit(1)
PFA
python3 - <<'PFB' || die PREFLIGHT_IO
import trimesh, os
m = trimesh.creation.box((1, 2, 3))
m.export("/tmp/pf.obj")
trimesh.Scene({"t": m}).export("/tmp/pf.glb")
import open3d as o3d
r = o3d.io.read_triangle_mesh("/tmp/pf.obj")
assert len(r.triangles) > 0, "open3d could not read a trimesh-written obj"
print("preflight io ok: obj", os.path.getsize("/tmp/pf.obj"),
      "glb", os.path.getsize("/tmp/pf.glb"), "o3d tris", len(r.triangles))
PFB

stage weights
mkdir -p /workspace/TripoSF/ckpts
CKPT=/workspace/TripoSF/ckpts/pretrained_TripoSFVAE_256i1024o.safetensors
# ATTEMPT 3 DIED HERE ON `No module named huggingface_hub`. The right fix is
# not to install it — it is to STOP NEEDING IT. The weights are ONE public file
# at a known URL that the launcher already preflights to HTTP 206, so curl with
# resume is strictly simpler and has one less thing that can be absent.
# The byte count is ASSERTED: a truncated download would otherwise surface much
# later as a confusing safetensors parse error rather than as a failed fetch.
WURL="https://huggingface.co/VAST-AI/TripoSF/resolve/main/vae/pretrained_TripoSFVAE_256i1024o.safetensors"
WANT=715361228
for a in 1 2 3 4 5; do
  curl -sSL -C - -H "Authorization: Bearer ${HF_TOKEN}" "$WURL" -o "$CKPT" && break
  echo "weights attempt $a failed; retrying"; sleep $((5*a))
done
GOT=$(stat -c%s "$CKPT" 2>/dev/null || echo 0)
echo "weights bytes=$GOT want=$WANT"
[ "$GOT" = "$WANT" ] || die WEIGHTS_SIZE_${GOT}
python3 -c "
from safetensors.torch import load_file
sd = load_file('$CKPT')
print('safetensors ok:', len(sd), 'tensors')
" || die WEIGHTS_UNREADABLE
ls -l /workspace/TripoSF/ckpts

stage import_check
cd /workspace/TripoSF
python3 -c "
import triposf.modules.sparse as sp
from triposf.models.triposf_vae.encoder import TripoSFVAEEncoder
from triposf.models.triposf_vae.decoder import TripoSFVAEDecoder
print('triposf imports ok')
" || die TRIPOSF_IMPORT

stage infer
cd /workspace/TripoSF
mkdir -p /workspace/out
# `cmd | tail` makes $? the status of TAIL — a crashed run once read as
# SUCCESS here. PIPESTATUS reads the real code while still trimming output.
python3 inference.py --mesh-path /workspace/INPUT.glb \
        --output-dir /workspace/out \
        --config configs/TripoSFVAE_1024.yaml 2>&1 | tail -40
RC=${PIPESTATUS[0]}
echo "INFERENCE RC=$RC"
[ "$RC" = "0" ] || die INFER_RC_$RC
ls -l /workspace/out
# RC=0 with no artefact is the documented silent-failure class.
[ -f /workspace/out/INPUT_reconstruction.obj ] || die NO_RECON_OBJ

stage package
python3 - <<'PY' || die PACKAGE
import trimesh, numpy as np, os, gzip, shutil
for tag, src in (("gt", "/workspace/out/INPUT_gt.obj"),
                 ("recon", "/workspace/out/INPUT_reconstruction.obj")):
    m = trimesh.load(src, process=False)
    print(tag, "verts", len(m.vertices), "faces", len(m.faces),
          "extents", np.round(m.bounding_box.extents, 4).tolist())
    out = f"/workspace/out/{tag}.glb"
    trimesh.Scene({tag: m}).export(out)
    print(tag, "glb bytes", os.path.getsize(out))
PY
ls -l /workspace/out

stage measure
# crease_density.py is fetched from the bucket so the SAME code measures both
# sides of the comparison; a second implementation would be a second variable.
sb_get crease_density.py /workspace/crease_density.py || echo "MEASURE TOOL MISSING"
sb_get crease2.py /workspace/crease2.py || echo "CREASE2 MISSING"
python3 /workspace/crease_density.py /workspace/out/INPUT_gt.obj /workspace/out/INPUT_reconstruction.obj 2>&1 | tee /workspace/out/crease.txt
[ -f /workspace/crease2.py ] && python3 /workspace/crease2.py /workspace/out/INPUT_gt.obj /workspace/out/INPUT_reconstruction.obj 2>&1 | tee -a /workspace/out/crease.txt
cat /workspace/out/crease.txt
sb_file "${RUN}_crease.txt" /workspace/out/crease.txt

stage upload
# Supabase 413s above ~50MB on BOTH endpoints (measured on Gate 6). Chunk with
# a MANIFEST rather than discovering the limit with the primary artefact —
# rollback #6 destroyed a 68MB GLB whose evidence survived and whose file
# did not. THE ARTEFACT GOES UP BEFORE THE REPORT ABOUT IT.
cd /workspace/out
for f in recon.glb gt.glb; do
  [ -f "$f" ] || continue
  SZ=$(stat -c%s "$f")
  if [ "$SZ" -lt 45000000 ]; then
    sb_file "${RUN}_${f}" "$f"
  else
    echo "$f is $SZ bytes — splitting"
    split -b 45000000 -d -a 2 "$f" "part_${f}."
    N=0
    for p in part_${f}.*; do sb_file "${RUN}_${p}" "$p"; N=$((N+1)); done
    echo "{\"file\":\"$f\",\"bytes\":$SZ,\"parts\":$N,\"prefix\":\"${RUN}_part_${f}.\",\"sha256\":\"$(sha256sum $f | cut -d' ' -f1)\"}" > "man_${f}.json"
    cat "man_${f}.json"
    sb_file "${RUN}_man_${f}.json" "man_${f}.json"
  fi
done
ls -l /workspace/out

stage verify_uploaded
# Verify by asking the BUCKET, not by trusting the upload status.
python3 - <<'PY'
import os, json, urllib.request
sb = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/list/car-meshes"
key = os.environ["SB_KEY"]
pre = os.environ.get("ST_PRE", "car-meshes/staging/sharptest").split("car-meshes/")[-1]
req = urllib.request.Request(sb, data=json.dumps({"prefix": pre + "/", "limit": 200}).encode(),
                             headers={"apikey": key, "Authorization": f"Bearer {key}",
                                      "Content-Type": "application/json"})
for x in json.load(urllib.request.urlopen(req, timeout=60)):
    print("BUCKET", x["name"], (x.get("metadata") or {}).get("size"))
PY

echo "=== SPARSEFLEX_OK ==="
report
# Do not idle on success: end the billable work as soon as the evidence is up.
# The launcher deletes the pod; the fuse deletes it if the launcher is gone;
# this is the third path and it is the fastest.
runpodctl remove pod "$RUNPOD_POD_ID" >/dev/null 2>&1 || true
curl -s -X DELETE -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
     "https://rest.runpod.io/v1/pods/${RUNPOD_POD_ID}" >/dev/null 2>&1 || true
sleep infinity
