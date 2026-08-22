#!/usr/bin/env bash
# Bootstrap run on a rented RunPod GPU: fetch data, merge, train, export ONNX,
# publish, then SHUT THE POD DOWN.
#
# Two hard lessons are encoded here.
#
# 1. SELF-TERMINATION. The EXIT trap stops the pod on failure as well as
#    success. A GPU pod left running after a finished job bills indefinitely,
#    and this project has already paid for that.
#
# 2. THE LOG IS AN ARTEFACT. RunPod's REST API exposes no logs endpoint, so a
#    run that dies without uploading its log is undebuggable — the first
#    attempt here exited after seven minutes and left nothing behind but a
#    charge. The trap now uploads train.log ALWAYS, before stopping the pod, so
#    a failure costs one run instead of a blind retry.
#
# Required env: HF_TOKEN HF_REPO CORPUS_REPO RUNPOD_API_KEY RUNPOD_POD_ID
# Optional: EPOCHS BATCH LIMIT RUN_TAG   (LIMIT = smoke-test sample cap)
set -x
# Deliberately NOT `set -u`: an unset RUNPOD_POD_ID must not abort the very trap
# that stops the pod.

WORK=/workspace
mkdir -p "$WORK" && cd "$WORK"
LOG="$WORK/train.log"
exec > >(tee -a "$LOG") 2>&1
TAG="${RUN_TAG:-run}"

# HEARTBEAT: publish the log WHILE running, not only at exit.
#
# A smoke run hung for 87 minutes and had to be stopped from outside. The EXIT
# trap never fired, so it produced no log at all and the hang is permanently
# undiagnosable — 87 minutes of billing bought nothing but the knowledge that
# something was slow. A run that can only be observed after it ends cannot be
# debugged while it is costing money, and a 14-hour run is 14 hours of that.
#
# Every 5 minutes = 12 commits/hour, comfortably under the Hub's 128/hour
# repository limit even across a 14-hour run with checkpoint uploads on top.
# Failures here are swallowed: the heartbeat must never be able to kill the
# training it exists to observe.
(
  set +x            # this loop must not write to the log it is uploading
  while true; do
    sleep 300
    python - <<'PY' >/dev/null 2>&1
import os, glob
from huggingface_hub import HfApi
tag = os.environ.get("RUN_TAG", "run")
api = HfApi(token=os.environ["HF_TOKEN"])
try:
    api.upload_file(path_or_fileobj="/workspace/train.log",
                    path_in_repo="logs/%s.live.log" % tag,
                    repo_id=os.environ["HF_REPO"])
except Exception:
    pass

# SHIP EACH CHECKPOINT AS SOON AS IT EXISTS.
#
# Publishing only from the EXIT trap loses the model. Stopping a pod gave the
# trap enough time for a 30KB log and not for a 200MB checkpoint: the log
# arrived, the weights did not, and epoch 1 was gone. On a 20-hour run
# interrupted at hour 19 that would be the whole job.
#
# KEY ON mtime, NOT SIZE.
#
# Size alone silently stopped publishing. A .pth holds the same tensors every
# epoch, so it is usually byte-identical in LENGTH while its CONTENTS change
# completely: the guard read "same size, already sent" and skipped every
# epoch after the first that happened to differ. v12b ran to epoch 8 with
# epoch 7's weights on the Hub, and the "stopped at hour 19" disaster this
# block exists to prevent was live the whole time.
#
# mtime changes on every write, so it tracks what size cannot. Checkpoints
# are written per epoch, so this adds a handful of commits against the Hub's
# 128/hour limit.
seen = {}
mark = "/workspace/.uploaded"
if os.path.exists(mark):
    for line in open(mark):
        k, _, v = line.strip().partition("\t")
        seen[k] = v
for pth in sorted(glob.glob("/workspace/runs/**/*.pth", recursive=True)):
    try:
        st = os.stat(pth)
        sz = "%d:%d" % (st.st_size, st.st_mtime_ns)
        if seen.get(pth) == sz:
            continue
        api.upload_file(path_or_fileobj=pth,
                        path_in_repo="%s/%s" % (tag, os.path.basename(pth)),
                        repo_id=os.environ["HF_REPO"])
        seen[pth] = sz
        with open(mark, "w") as f:
            for k, v in seen.items():
                f.write("%s\t%s\n" % (k, v))
    except Exception:
        pass
PY
  done
) &
HEARTBEAT_PID=$!
echo "heartbeat pid $HEARTBEAT_PID -> logs/$TAG.live.log every 5 min"

# STALL WATCHDOG — IN THE POD, BECAUSE NOTHING ELSE IS RELIABLY AWAKE.
#
# An hourly check from the controlling session was promised and did not
# happen: that scheduler only fires while its session is alive and idle, and
# it simply never ran. A pod then sat hung for two and a half hours. The
# controlling session is not a monitor and must never be treated as one.
#
# The pod is the only thing guaranteed to be running, so the pod watches
# itself: if train.log stops growing for STALL_MINUTES, the run is wedged and
# is killed. Every stage here writes progress — download percentages,
# per-shard extraction, materialise counts every 5,000, training epochs — so
# a log that has not grown in 25 minutes is not a slow stage, it is a dead one.
#
# Killing the main shell fires the EXIT trap, which uploads the log, publishes
# any checkpoint, and stops the pod. A wedged run therefore costs 25 minutes,
# not however long until someone happens to look.
STALL_MINUTES="${STALL_MINUTES:-45}"
MAIN_PID=$$
(
  # set +x IS LOAD-BEARING: with tracing on, this loop's own output lands in
  # train.log and, in the first version, in the very measurement it used to
  # detect a stall — so the log always grew and the watchdog could never fire.
  set +x
  #
  # THE SIGNAL IS GPU UTILISATION, NOT LOG GROWTH.
  #
  # Measuring the log was wrong in both directions. It false-negatived while
  # the loop traced into its own input, and it would have false-POSITIVED here:
  # RF-DETR prints nothing between epochs, and an epoch over 369,762 images is
  # hours long, so a perfectly healthy run looks identical to a wedged one.
  # Killing on silence would have destroyed the run it was meant to protect.
  #
  # A hung DataLoader sits at 0% GPU. Training does not. That distinguishes the
  # two cases directly instead of inferring from a side effect, and the samples
  # are written to the log so the run is observable even while RF-DETR is quiet.
  # TWO PHASES, because the GPU is SUPPOSED to be idle for the first hour.
  # Dependency installs, a 14GB download and rendering 403,193 samples are all
  # CPU and disk work — arming a GPU-idle rule from the start would have killed
  # the run during materialise, at 45 minutes, every single time. Before
  # training begins the log is the right signal (those stages print constantly);
  # once "=== train ===" appears, RF-DETR goes quiet and only the GPU can say
  # whether anything is happening.
  idle=0; lastsz=0; quiet=0
  while true; do
    sleep 300
    if ! grep -q "^=== train ===" "$LOG" 2>/dev/null; then
      now=$(stat -c %s "$LOG" 2>/dev/null || echo 0)
      if [ "$now" = "$lastsz" ]; then
        quiet=$((quiet + 5))
        echo "WATCHDOG: pre-training, log static ${quiet}m" >> "$LOG"
        if [ "$quiet" -ge 30 ]; then
          echo "WATCHDOG: setup wedged ${quiet}m" >> "$LOG"
          for pid in $(pgrep -f "materialise_index.py|train.sh" 2>/dev/null); do
            echo "--- py-spy dump pid $pid ---" >> "$LOG"
            py-spy dump --pid "$pid" >> "$LOG" 2>&1 || true
          done
          free -g >> "$LOG" 2>&1
          echo "WATCHDOG: killing after diagnostics" >> "$LOG"
          kill -TERM "$MAIN_PID" 2>/dev/null; sleep 30
          kill -KILL "$MAIN_PID" 2>/dev/null; exit 1
        fi
      else
        quiet=0; lastsz="$now"
      fi
      continue
    fi
    read -r util mem < <(nvidia-smi --query-gpu=utilization.gpu,memory.used \
      --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ',')
    util="${util:-0}"
    echo "GPU: ${util}% util, ${mem:-?} MiB used" >> "$LOG"
    if [ "$util" -lt 5 ] 2>/dev/null; then
      idle=$((idle + 5))
      if [ "$idle" -ge "$STALL_MINUTES" ]; then
        echo "WATCHDOG: GPU idle ${idle}m — run is wedged" >> "$LOG"
        # DUMP THE STACK BEFORE KILLING. Once the process is dead the reason is
        # gone, and the log then records only that something stopped — which is
        # exactly the useless state three earlier hangs left behind.
        for pid in $(pgrep -f "train_detector.py|materialise_index.py" 2>/dev/null); do
          echo "--- py-spy dump pid $pid ---" >> "$LOG"
          py-spy dump --pid "$pid" >> "$LOG" 2>&1 || \
            echo "(py-spy failed on $pid)" >> "$LOG"
        done
        echo "--- python processes ---" >> "$LOG"
        ps -eo pid,etime,rss,args --no-headers | grep -c python >> "$LOG" 2>&1
        echo "--- memory ---" >> "$LOG"
        free -g >> "$LOG" 2>&1
        echo "WATCHDOG: killing after diagnostics" >> "$LOG"
        kill -TERM "$MAIN_PID" 2>/dev/null
        sleep 30
        kill -KILL "$MAIN_PID" 2>/dev/null
        exit 1
      fi
    else
      idle=0
    fi
  done
) &
WATCHDOG_PID=$!
echo "watchdog pid $WATCHDOG_PID — kills the run after ${STALL_MINUTES}m of GPU idle"


finish() {
  code=$?
  set +x
  kill "$HEARTBEAT_PID" 2>/dev/null
  kill "$WATCHDOG_PID" 2>/dev/null
  echo "=== exit code $code ==="
  # Upload the log FIRST — it is the only diagnostic that survives the pod.
  python - <<'PY' || echo "log upload failed"
import os
from huggingface_hub import HfApi
try:
    HfApi(token=os.environ["HF_TOKEN"]).upload_file(
        path_or_fileobj="/workspace/train.log",
        path_in_repo=f"logs/{os.environ.get('RUN_TAG','run')}.log",
        repo_id=os.environ["HF_REPO"], token=os.environ["HF_TOKEN"])
    print("log uploaded")
except Exception as e:
    print("log upload error:", e)
PY
  # Pod id: the env var is NOT reliably injected — on the first full run it was
  # empty, the guard skipped the stop call, and a crashed pod kept billing for
  # six minutes until stopped by hand. Fall back to the hostname (RunPod sets it
  # to the pod id), then to looking ourselves up by name. Failing to stop is the
  # expensive failure, so it gets three chances and three strategies.
  PID="${RUNPOD_POD_ID:-}"
  [ -z "$PID" ] && PID="$(hostname)"
  echo "stopping pod id=$PID"

  # THE IN-POD STOP IS THE ONLY FAILSAFE THAT RUNS UNATTENDED.
  # An external watcher in the controlling session does not count: that process
  # is frozen whenever the session is idle. On the v5 run the script correctly
  # gave up after five minutes, and the pod then billed for SIX HOURS because
  # the only thing that would have stopped it was asleep. So this block has to
  # actually work, and it has to be checked rather than assumed.
  #
  # Previous version looped on `curl ... | grep -q .` — any response at all,
  # including an error body, counted as success, so a failing stop looked fine.
  # Now: runpodctl first (present on RunPod images, uses the pod's own
  # credentials), then the REST API with the HTTP status actually inspected,
  # and terminate as the last resort because a stopped-but-existing pod can
  # still be restarted by the platform.
  if command -v runpodctl >/dev/null 2>&1; then
    echo "runpodctl stop:"; runpodctl stop pod "$PID" || true
  fi
  for attempt in 1 2 3; do
    code=$(curl -s -o /tmp/stop.out -w "%{http_code}" -X POST \
      "https://rest.runpod.io/v1/pods/${PID}/stop" \
      -H "Authorization: Bearer ${RUNPOD_API_KEY}")
    echo "stop attempt $attempt -> HTTP $code $(head -c 160 /tmp/stop.out)"
    [ "$code" = "200" ] || [ "$code" = "204" ] && break
    sleep 5
  done
  code=$(curl -s -o /tmp/term.out -w "%{http_code}" -X DELETE \
    "https://rest.runpod.io/v1/pods/${PID}" \
    -H "Authorization: Bearer ${RUNPOD_API_KEY}")
  echo "terminate -> HTTP $code $(head -c 160 /tmp/term.out)"
  # Last resort: find any pod with this name still running and stop it.
  python - <<'PY' || true
import os, json, urllib.request
key = os.environ.get("RUNPOD_API_KEY", "")
req = urllib.request.Request("https://rest.runpod.io/v1/pods",
                             headers={"Authorization": f"Bearer {key}"})
try:
    pods = json.load(urllib.request.urlopen(req, timeout=20))
    for p in pods if isinstance(pods, list) else []:
        if p.get("name", "").startswith("damage-detector-train") \
                and p.get("desiredStatus") == "RUNNING":
            u = f"https://rest.runpod.io/v1/pods/{p['id']}/stop"
            urllib.request.urlopen(urllib.request.Request(
                u, data=b"", headers={"Authorization": f"Bearer {key}"}),
                timeout=20)
            print("stopped by name:", p["id"])
except Exception as e:
    print("name-based stop failed:", e)
PY
}
trap finish EXIT

# RUN-ONCE GUARD — registered AFTER the trap, deliberately. RunPod restarts the
# container whenever dockerStartCmd exits, so a failing script loops (v4 ran 22
# times). The marker on the container disk survives those restarts and makes a
# second entry refuse to work. It sits below `trap finish EXIT` because the
# audit found it above: on the marker path the script exited before the trap
# existed, so the pod never attempted to stop itself — precisely the unattended
# path where self-stop matters most. Now the marker exit flows through finish()
# and its checked stop/terminate, retrying on every 5-minute restart cycle
# until one lands.
MARKER="$WORK/.attempted-$TAG"
if [ -e "$MARKER" ]; then
  echo "=== $TAG already attempted — refusing to re-run; stopping pod ==="
  sleep 60
  exit 0
fi
date -u > "$MARKER"

echo "=== env ==="
nvidia-smi || echo "NO GPU VISIBLE"
python -V; df -h /workspace | tail -1

echo "=== deps ==="
pip install -q --upgrade pip
# One package per line so a failure names itself in the log.
pip install -q huggingface_hub || exit 11
# onnx AND onnxruntime — different packages, and the distinction cost a seven
# hour run: torch.onnx.export needs `onnx` to serialise the graph, while
# `onnxruntime` only executes an already-built model. Having the runtime
# installed made the export look supported right up to the moment it raised
# "Module onnx is not installed!".
pip install -q onnx onnxruntime || exit 12
# py-spy prints the stack of a RUNNING process without stopping it. Three hangs
# in this project cost 87 minutes, 55 minutes and 2.5 hours respectively, and
# every one of them would have been named in seconds by a stack dump: the first
# was stuck importing PIL/_imaging.so, the second in a Pool initializer, the
# third in a DataLoader. A watchdog that says "it stalled" is worth far less
# than one that says WHERE.
pip install -q py-spy || echo "py-spy unavailable (diagnostics degraded)"

# Torch MUST come first and be >= 2.5. The base image ships 2.4.1, and current
# transformers refuses to enable its PyTorch integration below 2.5 — it prints
# "PyTorch was not found", carries on with tokenizers only, and rfdetr then dies
# on `cannot import name BackboneConfigMixin`. That import error names
# transformers and hides the real cause, which is the torch version. Upgrading
# here costs one large download and removes the whole class of confusion.
# Pick the torch build from the DRIVER ON THIS MACHINE, never a fixed index.
# The rented GPU is not a fixed target: v4 landed on driver 570.x / CUDA 12.8,
# v5 on 550.x / CUDA 12.4. A hardcoded cu124 was too old for the first and a
# hardcoded cu126 was too new for the second — same script, opposite failures,
# both reported as "the NVIDIA driver on your system is too old". Reading the
# driver first is the only version of this that survives whichever machine the
# scheduler hands us.
DRV=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
CUDA_MM=$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: *\([0-9]*\)\.\([0-9]*\).*/\1\2/p' | head -1)
echo "driver=$DRV cuda=$CUDA_MM"
case "${CUDA_MM:-124}" in
  12[89]|13*) IDX=cu128 ;;
  126|127)    IDX=cu126 ;;
  12[45])     IDX=cu124 ;;
  12[0123])   IDX=cu121 ;;
  *)          IDX=cu124 ;;
esac
echo "selected torch index: $IDX"
pip install -q --upgrade torch torchvision --index-url "https://download.pytorch.org/whl/$IDX" || exit 13
# The [train,loggers] extras are NOT optional here. Plain `pip install rfdetr`
# gives a package that imports perfectly and then refuses to train
# ("RF-DETR training dependencies are missing" / no module pytorch_lightning),
# which is why the previous smoke test passed and the run still died — 30
# minutes and a full dataset merge later.
# --ignore-installed blinker: the base image carries blinker 1.4 as a
# distutils-installed system package, which pip refuses to uninstall ("cannot
# accurately determine which files belong to it"), so a transitive upgrade
# request aborts the whole install. Ignoring that one package lets pip put its
# own copy alongside instead of failing.
pip install -q --ignore-installed blinker "rfdetr[train,loggers]" || exit 14

# REASSERT THE DRIVER-MATCHED TORCH. rfdetr's dependency resolution upgrades
# torch to whatever PyPI serves by default — on this run 2.6.0+cu124 became
# 2.13.0+cu130, which wants a CUDA 13 driver against the machine's 12.4, and
# the run died at the CUDA check. The check below was already positioned after
# rfdetr precisely because this had happened before; it caught the problem and
# could not repair it, so the repair goes here.
#
# Machine-dependent, which is what makes it nasty: the same install succeeded
# on a Blackwell card with a newer driver minutes earlier, and failed on an
# A6000 at driver 550. Pinning to the driver-derived index makes it
# deterministic on both. --no-deps so nothing else shifts underneath it.
pip install -q --force-reinstall --no-deps torch torchvision \
  --index-url "https://download.pytorch.org/whl/$IDX" || exit 16
python -c "import torch;print('torch after re-pin:', torch.__version__)"

# PILLOW MUST BE REINSTALLED AND PROVEN TO IMPORT.
#
# Two runs were lost to this. The image ships a Pillow whose compiled
# extension does not match its Python package:
#   ImportError: PIL/_imaging...so: undefined symbol: ImagingJpeg2KEncode
# and something in the torch/rfdetr install chain leaves it that way. The
# failure is invisible where it happens: materialise_index's Pool workers all
# die inside their initialiser, imap_unordered then blocks forever, and the pod
# sits at 100% idle burning money with no error on stdout. One smoke run hung
# 87 minutes on exactly this and had to be killed from outside.
#
# --no-cache-dir because a cached wheel is how the mismatch survives a
# reinstall. The import is then EXERCISED, not just attempted: `import PIL`
# alone succeeds on the broken install, because the extension is only loaded
# when Image is used.
pip install -q --force-reinstall --no-cache-dir Pillow || exit 17
python - <<'PY' || exit 18
from PIL import Image
import io
im = Image.new("RGB", (32, 32), (1, 2, 3))
b = io.BytesIO()
im.save(b, "JPEG")           # exercises the encoder the mismatch hides in
b.seek(0)
assert Image.open(b).size == (32, 32)
print("Pillow OK:", Image.__version__ if hasattr(Image, "__version__")
      else __import__("PIL").__version__)
PY
# So the smoke test now checks the TRAINING path, not just the import: the
# gate must fail on the same thing the real run would.
# CUDA is verified AFTER rfdetr, never before. v4 printed "torch 2.6.0+cu124
# cuda True" during its dependency check and then died at the first training
# call with "NVIDIA driver is too old (found version 12080)" — because
# installing rfdetr pulled its own torch build on top, and the machine's driver
# (570.x / CUDA 12.8) could not run it. Checking before the last install
# validated a torch that no longer existed by the time training started.
#
# So the gate below runs last, and does real GPU work rather than reading
# version strings: is_available() alone returned True on the build that then
# failed to initialise.
python - <<'PY' || exit 15
import torch, onnx, rfdetr, pytorch_lightning
from rfdetr import RFDETRBase
assert hasattr(RFDETRBase, "train"), "RFDETRBase has no train()"
print("torch", torch.__version__, "| lightning", pytorch_lightning.__version__,
      "| onnx", onnx.__version__)
assert torch.cuda.is_available(), "CUDA not available"
# Force a real allocation + kernel launch + bf16 probe: exactly the calls that
# blew up mid-run last time.
x = torch.randn(64, 64, device="cuda")
y = (x @ x).sum().item()
torch.cuda.is_bf16_supported()
torch.cuda.synchronize()
print("CUDA OK:", torch.cuda.get_device_name(0), "| matmul", round(y, 3))
PY

echo "=== fetch scripts ==="
python - <<'PY' || exit 20
import os
from huggingface_hub import hf_hub_download
# materialise_index needs augment, which needs watermark_aug. Fetching a
# partial set would fail at import time AFTER the pod is already billing.
for f in ("train_detector.py", "materialise_index.py", "augment.py",
          "watermark_aug.py"):
    try:
        p = hf_hub_download(repo_id=os.environ["HF_REPO"], filename=f,
                            token=os.environ["HF_TOKEN"], local_dir="/workspace")
        print("got", p)
    except Exception as e:
        print("MISSING", f, e)
PY

# THE CORPUS IS FETCHED, NOT REBUILT.
#
# This step used to re-download 41 Roboflow projects and re-merge them on the
# pod. That path silently discarded every correction made to the data: the
# 30,404 off-domain images (steel fences, copper pipe, aircraft skin) came
# back, the class balancing did not happen, near-duplicate grouping did not
# happen, and the six-class corpus was fed to a ten-class mapper whose
# labels.txt then disagreed with the weights — every prediction mislabelled
# while the run looked healthy. It also spent the first hour of a paid GPU
# downloading data that already existed.
#
# So the cleaned corpus and its index ship as a dataset repo, and the pod only
# renders them.
# Images arrive as ~30 tar shards, not 167,157 loose files. A per-file
# transfer of that many small objects stalled dead against HTTP 429 at 6%.
# GPU PREFLIGHT — one real convolution, before any data is fetched.
#
# The first panel run died with "cuDNN error: CUDNN_STATUS_NOT_INITIALIZED" at
# the first training batch. Everything before it had worked: deps installed,
# the dataset downloaded and extracted, 1,002 files verified. The fault was the
# machine, not the run — and it was discovered only after all of that had been
# paid for.
#
# nvidia-smi does NOT catch this. It reports a healthy GPU on a host whose
# cuDNN cannot initialise, because it never asks cuDNN for anything. So the
# check has to be an actual convolution on the actual device: it is the
# cheapest possible instance of the exact operation that failed, it runs in
# under a second, and a failure here means "relaunch onto another machine"
# rather than "debug the pipeline".
echo "=== gpu preflight ==="
python - <<'PYGPU' || exit 14
import os
import sys
import time
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda,
      "cudnn", torch.backends.cudnn.version())
if not torch.cuda.is_available():
    print("PREFLIGHT FAIL: no CUDA device visible")
    sys.exit(1)
print("device:", torch.cuda.get_device_name(0))
free, total = torch.cuda.mem_get_info()
print(f"vram: {free/2**30:.1f} GiB free of {total/2**30:.1f} GiB")
print("cudnn available:", torch.backends.cudnn.is_available(),
      "enabled:", torch.backends.cudnn.enabled)

# RETRY, because the first diagnosis was wrong. Two DIFFERENT machines with
# DIFFERENT drivers (CUDA 12.8/torch 2.11 and CUDA 12.4/torch 2.6) failed
# identically, so "bad host, relaunch" was not the explanation. cuDNN's handle
# creation is also the first real GPU allocation of the run, which makes it the
# place a transient shortage or a slow device init surfaces — both worth
# retrying before writing the machine off.
ok = False
for attempt in (1, 2, 3):
    try:
        x = torch.randn(1, 3, 64, 64, device="cuda")
        w = torch.randn(8, 3, 3, 3, device="cuda")
        y = torch.nn.functional.conv2d(x, w)
        torch.cuda.synchronize()
        print(f"cudnn conv OK on attempt {attempt}", tuple(y.shape))
        ok = True
        break
    except Exception as e:
        print(f"  attempt {attempt}: {type(e).__name__}: {str(e)[:120]}")
        torch.cuda.empty_cache()
        time.sleep(5)

if not ok:
    # WARN, DO NOT EXIT. This check was fatal and that was the wrong call.
    #
    # Three consecutive runs were refused on three different machines and two
    # different card types, one with 44.2 GiB of 44.4 GiB free — so neither a
    # bad host nor memory. Yet the two runs immediately before them trained
    # fine on this same script. When a gate rejects everything, the gate itself
    # is the most likely fault, and a preflight that wrongly refuses costs the
    # entire run while one that wrongly passes costs about a pound of GPU time
    # before the first batch fails. The asymmetry runs the other way from how
    # this was written.
    #
    # So: report loudly, then continue and let real training be the judge. The
    # watchdog and the first training batch will kill it within minutes if
    # cuDNN genuinely cannot work.
    try:
        torch.backends.cudnn.enabled = False
        y = torch.nn.functional.conv2d(
            torch.randn(1, 3, 64, 64, device="cuda"),
            torch.randn(8, 3, 3, 3, device="cuda"))
        torch.cuda.synchronize()
        print("PREFLIGHT WARNING: cuDNN handle failed here but the GPU itself "
              "works (conv succeeded with cudnn disabled).")
    except Exception as e2:
        print(f"PREFLIGHT WARNING: the GPU could not convolve at all: "
              f"{type(e2).__name__}: {str(e2)[:120]}")
    # Diagnostics for the real cause, printed once so the next failure is
    # cheaper to read than this one was.
    import glob as _g
    print("torch libs:", [os.path.basename(x) for x in
                          _g.glob(os.path.join(os.path.dirname(torch.__file__),
                                               "lib", "*cudnn*"))][:6])
    print("nvidia pkgs:", [os.path.basename(x) for x in
                           _g.glob("/usr/local/lib/python3*/dist-packages/"
                                   "nvidia/cudnn/lib/*")][:6])
    print("LD_LIBRARY_PATH:", os.environ.get("LD_LIBRARY_PATH", "(unset)"))
    print("CONTINUING ANYWAY — training itself is the real test.")
PYGPU

# PANEL MODE. The panel dataset is 998 images and 692MB — three orders of
# magnitude smaller than the damage corpus — so none of the shard machinery
# below applies to it. It ships as ONE tar already in RF-DETR's train/valid/test
# layout, which means no index, no materialise step, and no class mapping on the
# pod at all. Everything else in this script is shared deliberately: the
# driver-matched torch pin, the Pillow round-trip proof, the EXIT trap that
# stops the pod, the heartbeat that publishes checkpoints, and the export path
# that survives the wall-clock cap were each paid for by a failed run, and a
# separate script for panels would have had to learn all of them again.
if [ "${DATASET_MODE:-damage}" = "panels" ]; then
  echo "=== fetch panel dataset ==="
  python - <<'PYPANEL' || exit 30
import os, tarfile
from huggingface_hub import hf_hub_download
p = hf_hub_download(repo_id=os.environ["CORPUS_REPO"], filename="panels.tar",
                    repo_type="dataset", token=os.environ["HF_TOKEN"],
                    local_dir="/workspace")
with tarfile.open(p) as tf:
    tf.extractall("/workspace/prepared")
os.remove(p)
n = sum(len(fs) for _, _, fs in os.walk("/workspace/prepared"))
print(f"{n} files extracted")
# The damage run's equivalent assert caught a truncated download before it
# reached the GPU. Same guard, sized for this dataset.
assert n > 900, f"only {n} files extracted — download looks truncated"
PYPANEL
  # The tar carries labels.txt at its root alongside train/valid/test, which is
  # exactly the layout train_detector.py expects from materialise_index.
  du -sh prepared || true
  head -c 300 prepared/labels.txt; echo
else
echo "=== fetch corpus + index ==="
python - <<'PY' || exit 30
import os, time, tarfile, concurrent.futures as cf
from huggingface_hub import snapshot_download, list_repo_files
repo, tok = os.environ["CORPUS_REPO"], os.environ["HF_TOKEN"]
# allow_patterns, not the whole repo: a failed per-file upload left 9,999
# loose images/ objects behind, and deleting them costs commits against a
# 128/hour limit that the same failure had already exhausted. Skipping them
# on download is free and leaves the repo honest about its own history.
# max_workers=4, not 16: the smoke run drove the Hub's xet-read-token
# endpoint into HTTP 429 and died on the download. Twenty-seven 500MB files
# are bandwidth-bound anyway, so the extra concurrency bought nothing and
# cost the run.
def fetch():
    return snapshot_download(repo_id=repo, repo_type="dataset", token=tok,
                      local_dir="/workspace/corpus", max_workers=4,
                             allow_patterns=["shards/*", "idx/*",
                                             "merged640/_annotations.coco.json"])

# A rate-limited download must wait, not die: the corpus is the one thing the
# run cannot proceed without, and the pod is already billing by this point.
for attempt in range(6):
    try:
        p = fetch()
        break
    except Exception as e:
        wait = min(900, 60 * 2 ** attempt)
        print(f"fetch retry {attempt+1}/6 in {wait}s: {type(e).__name__} "
              f"{str(e)[:160]}", flush=True)
        time.sleep(wait)
else:
    raise SystemExit("corpus fetch failed after 6 attempts")
print("corpus at", p)

root_dir = "/workspace/corpus/merged640"
img_dir = os.path.join(root_dir, "images")
os.makedirs(img_dir, exist_ok=True)
shards = sorted(f for f in os.listdir("/workspace/corpus/shards")
                if f.endswith(".tar"))
# TWO SHARD FAMILIES, DISTINGUISHED BY NAME. See publish_corpus.
#   images_NNNN.tar  bare filenames  -> merged640/images/
#   src_NNNN.tar     root-relative   -> merged640/   (e.g. cardd/images/x.jpg)
# The corpus stopped being one flat folder when CarDD arrived, and the index
# records "cardd/images/x.jpg". Extracting that family flat would put the file
# where nothing looks for it, and materialise_index would fail image by image
# after the whole download had been paid for.
def untar(name):
    dest = img_dir if name.startswith("images_") else root_dir
    with tarfile.open(os.path.join("/workspace/corpus/shards", name)) as tf:
        tf.extractall(dest)
    return name
with cf.ThreadPoolExecutor(8) as ex:
    for n in ex.map(untar, shards):
        print("extracted", n, flush=True)
n = len(os.listdir(img_dir))
extra = sum(len(fs) for _d, _sd, fs in os.walk(root_dir)) - n
print(f"{n} images extracted from {len(shards)} shards "
      f"({extra} more under extra sources)")
# The materialise step would otherwise fail image by image, long after the
# download is paid for.
assert n > 100000, f"only {n} images extracted"
# ASSERT THE EXTRA SOURCES TOO. `extra` was printed and never checked, so a
# repo with no src_*.tar passed this gate and materialise_index then dropped
# every CarDD sample into its silent `dropped` counter -- the download paid
# for, the data absent, and nothing said so. The index knows how many it
# expects, so compare against it rather than against a magic number.
import json as _json
# An index path that does NOT start with "images/" belongs to an extra source
# (e.g. "cardd/images/x.jpg"), so this counts exactly what src_*.tar must have
# delivered.
_want = sum(1 for _ln in open("/workspace/corpus/idx/images.jsonl")
            if not _json.loads(_ln)["file"].startswith("images/"))
if _want:
    assert extra >= _want, (
        f"index expects {_want} images from extra sources but only {extra} "
        f"were extracted -- src_*.tar shards are missing from the corpus repo")
    print(f"extra sources OK: {extra} files for {_want} indexed images")
# Reclaim the tars: the pod holds corpus + extracted images + materialised
# samples at once, and the tars are dead weight once unpacked.
for s in shards:
    os.remove(os.path.join("/workspace/corpus/shards", s))
PY
du -sh corpus || true

# Renders index.jsonl into the COCO directory RF-DETR trains on, applying each
# sample's augmentation recipe and its class-independent watermark flag. LIMIT
# is how the smoke run stays short: same code path, fewer samples, so a failure
# costs minutes instead of the whole budget.
echo "=== materialise the index ==="
python -u materialise_index.py --index corpus/idx --corpus corpus/merged640 \
  --out prepared --workers "$(nproc)" ${LIMIT:+--limit $LIMIT} || exit 31
du -sh prepared || true
head -c 200 prepared/labels.txt; echo

fi

echo "=== train ==="
# HARD WALL-CLOCK CAP. train() runs to completion and this script has no other
# way to bound it, so a throughput estimate that is wrong by 2x turns a 14-hour
# budget into a 28-hour bill. `timeout` returns 124 and execution continues to
# the publish step below, which already handles a non-zero training result —
# a partially trained checkpoint is worth vastly more than nothing.
timeout "${MAX_HOURS:-13}h" python -u train_detector.py --data prepared --out runs \
  --epochs "${EPOCHS:-15}" --batch-size "${BATCH:-8}" \
  --grad-accum "${GRAD_ACCUM:-4}" \
  --num-workers "${NUM_WORKERS:-4}" \
  --model "${MODEL:-base}" --resolution "${RESOLUTION:-560}"
TRAIN_RC=$?
[ "$TRAIN_RC" = "124" ] && echo "TRAINING HIT THE ${MAX_HOURS:-13}h CAP — publishing what exists"
echo "train_detector rc=$TRAIN_RC"

# PUBLISH THE CHECKPOINT BEFORE ANYTHING ELSE CAN FAIL.
#
# The v6 run trained for seven hours, reached mAP50:95 0.439, wrote
# checkpoint_best_regular.pth — and then lost all of it, because ONNX export
# raised on a missing `onnx` package and the publish step sat AFTER the export
# in the same failure path. The pod's disk was ephemeral, so the weights died
# with it and the whole run had to be repeated.
#
# The weights are the expensive artefact; the ONNX file is a five-second
# derivative of them. So the checkpoint ships first, unconditionally, even when
# training itself returned non-zero — a partially trained checkpoint is worth
# vastly more than nothing.
echo "=== publish checkpoint (before export) ==="
python - <<'PY' || echo "checkpoint publish failed (continuing)"
import os, glob
from huggingface_hub import HfApi
api = HfApi(token=os.environ["HF_TOKEN"])
repo, tag = os.environ["HF_REPO"], os.environ.get("RUN_TAG", "run")
n = 0
for p in sorted(glob.glob("runs/**/*.pth", recursive=True)):
    mb = os.path.getsize(p) / 1e6
    print(f"uploading {p} ({mb:.0f} MB)")
    api.upload_file(path_or_fileobj=p,
                    path_in_repo=f"detector/{tag}/{os.path.basename(p)}",
                    repo_id=repo, token=os.environ["HF_TOKEN"])
    n += 1
for p in glob.glob("prepared/labels.txt"):
    api.upload_file(path_or_fileobj=p, path_in_repo=f"detector/{tag}/labels.txt",
                    repo_id=repo, token=os.environ["HF_TOKEN"])
print("checkpoints uploaded:", n)
PY
# EXPORT FROM THE CHECKPOINT WHEN TRAINING DID NOT EXIT CLEANLY.
#
# The 3-class run hit the wall-clock cap, so TRAIN_RC was 124, so this line
# used to `exit 40` and the run produced no ONNX at all — six epochs of a paid
# GPU delivered weights that the CPU worker could not load. Hitting the cap is
# the EXPECTED way a long run ends, not a failure: the cap is what stops the
# bill. Training's own in-process export dies with it (its DataLoader workers
# take the signal too), so the export is re-run here as a fresh process
# against the checkpoint that was just published.
if [ "$TRAIN_RC" != "0" ]; then
  BEST=""
  for cand in runs/checkpoint_best_ema.pth runs/checkpoint_best_regular.pth \
              runs/checkpoint.pth; do
    [ -f "$cand" ] && BEST="$cand" && break
  done
  if [ -z "$BEST" ]; then
    BEST=$(ls -1t runs/**/*.pth runs/*.pth 2>/dev/null | head -1)
  fi
  if [ -n "$BEST" ]; then
    echo "=== training rc=$TRAIN_RC; exporting from $BEST ==="
    python -u train_detector.py --data prepared --out runs --skip-train \
      --weights "$BEST" --model "${MODEL:-base}" \
      --resolution "${RESOLUTION:-560}" || echo "export failed (continuing)"
  else
    echo "no checkpoint to export from"
    exit 40
  fi
fi

echo "=== publish ==="
python - <<'PY' || exit 50
import os, glob
from huggingface_hub import HfApi
api = HfApi(token=os.environ["HF_TOKEN"])
repo, tag = os.environ["HF_REPO"], os.environ.get("RUN_TAG", "run")
sent = 0
for pat in ("runs/**/*.onnx", "runs/**/*.pth", "runs/**/deploy.json",
            "prepared/labels.txt", "runs/**/results.json"):
    for p in glob.glob(pat, recursive=True):
        api.upload_file(path_or_fileobj=p,
                        path_in_repo=f"detector/{tag}/{os.path.basename(p)}",
                        repo_id=repo, token=os.environ["HF_TOKEN"])
        print("uploaded", p, os.path.getsize(p))
        sent += 1
print("uploaded_files:", sent)
assert sent, "nothing uploaded"
PY

echo "=== DONE ==="
