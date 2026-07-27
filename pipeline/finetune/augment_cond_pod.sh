#!/bin/bash
# augment_cond_pod.sh — close the train/inference domain gap for Stage C.
#
# The 2026-07-27 sweep proved the gap is real and is the cause of the v0
# regression: the same checkpoints that wreck a photo-driven GTI generation
# produce a clean car from a Blender render of an unseen vehicle. Stage C did
# not learn bad shapes — it narrowed onto the render domain over 6000 steps,
# and real dealer photos fell outside it.
#
# WHAT TO AUGMENT — decided from what the pipeline actually does, not guesswork.
# preprocess_image runs BiRefNet background removal on the input photo, so the
# background is gone before the model sees anything. Varying backgrounds would
# be wasted work. What survives segmentation, and therefore what actually
# differs between a render and a photo, is:
#   1. tone     — real exposure/white balance/contrast vs one fixed rig
#   2. sensor   — JPEG artefacts, noise, softness from a phone or dealer camera
#   3. edges    — BiRefNet cutouts are feathered and imperfect; render alpha is
#                 mathematically exact, which is a cue the model can overfit to
# Lighting and reflections would need a re-render with varied HDRI (hours of
# Blender); this pass covers 1-3 cheaply and is the bigger share of the gap.
#
# NON-DESTRUCTIVE: writes a new renders_cond_aug/ tree. The originals are the
# only copy of 11GB of Stage A work and are never touched. Augmentation is
# deterministic per (sha, view) so a rerun reproduces the same set exactly.
ROOT=/workspace/alamcars
SRC="$ROOT/renders_cond"
DST="$ROOT/renders_cond_aug"
LOCAL=/root/augcond
mkdir -p "$LOCAL"
( cd "$LOCAL" && python3 -m http.server 8000 >/dev/null 2>&1 & )
exec > >(tee -a "$LOCAL/stage_b.log") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$LOCAL/status.json"; echo "===== $1 ====="; }

status boot
[ -f /etc/rp_environment ] && source /etc/rp_environment
df -h /workspace | tail -1
du -sh "$SRC" 2>/dev/null
pip install -q pillow numpy || true

status quota-check
# an 11GB copy needs headroom; a silent quota error is what truncated Stage D
python3 - <<'PY' || { status FATAL-volume-quota; sleep infinity; }
import os, sys
p = "/workspace/_aug_quota_probe"
try:
    with open(p, "wb") as f:
        f.write(b"X" * 64_000_000); f.flush(); os.fsync(f.fileno())
    ok = open(p, "rb").read(1024) == b"X" * 1024 and os.path.getsize(p) == 64_000_000
finally:
    try: os.remove(p)
    except Exception: pass
print("volume writable:", ok)
sys.exit(0 if ok else 1)
PY

status augment
python3 - <<'PY'
import glob, hashlib, io, os, random, shutil, sys
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

SRC = "/workspace/alamcars/renders_cond"
DST = "/workspace/alamcars/renders_cond_aug"
# fraction of views that get augmented. Not 100%: the model should still see
# clean renders, so the target is a WIDER distribution, not a shifted one.
AUG_FRACTION = 0.65

def jitter(im, rng):
    """tone + sensor character, applied to the RGB only"""
    im = ImageEnhance.Brightness(im).enhance(rng.uniform(0.80, 1.25))
    im = ImageEnhance.Contrast(im).enhance(rng.uniform(0.80, 1.30))
    im = ImageEnhance.Color(im).enhance(rng.uniform(0.75, 1.25))
    # white balance: real photos are rarely neutral (sodium lights, overcast, sun)
    a = np.asarray(im).astype(np.float32)
    a[..., 0] *= rng.uniform(0.94, 1.08)          # R
    a[..., 2] *= rng.uniform(0.94, 1.08)          # B
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if rng.random() < 0.25:                        # slight lens softness only
        # deliberately weak: dealer photos are SHARP. Teaching the model that
        # inputs are blurry would push outputs soft, which is the very defect
        # this retrain exists to remove. Noise/JPEG/tone are the real gap.
        im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0.2, 0.6)))
    if rng.random() < 0.6:                         # sensor noise
        a = np.asarray(im).astype(np.float32)
        a += np.random.default_rng(rng.randrange(1 << 30)).normal(0, rng.uniform(1.5, 5.0), a.shape)
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if rng.random() < 0.7:                         # JPEG artefacts
        b = io.BytesIO()
        im.save(b, format="JPEG", quality=rng.randint(45, 88))
        im = Image.open(io.BytesIO(b.getvalue())).convert("RGB")
    return im

def soften_alpha(al, rng):
    """BiRefNet cutouts are feathered and slightly wrong; render alpha is exact.
    Blur and re-threshold so the model stops relying on a perfect silhouette."""
    al = al.filter(ImageFilter.GaussianBlur(rng.uniform(0.6, 2.0)))
    a = np.asarray(al).astype(np.float32)
    t = rng.uniform(96, 160)                       # re-threshold off-centre
    a = np.clip((a - t) * rng.uniform(2.5, 6.0) + 128, 0, 255)
    return Image.fromarray(a.astype(np.uint8))

dirs = [d for d in sorted(glob.glob(SRC + "/*")) if os.path.isdir(d)]
print(f"{len(dirs)} shape dirs to process", flush=True)
os.makedirs(DST, exist_ok=True)
n_img = n_aug = n_copy = n_err = 0

for i, d in enumerate(dirs):
    sha = os.path.basename(d)
    out = os.path.join(DST, sha)
    os.makedirs(out, exist_ok=True)
    for f in sorted(glob.glob(d + "/*")):
        base = os.path.basename(f)
        dst = os.path.join(out, base)
        if not base.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            try: shutil.copy2(f, dst)          # carry metadata files across
            except Exception: pass
            continue
        n_img += 1
        # deterministic per (sha, view): a rerun reproduces this exact dataset
        seed = int(hashlib.sha256((sha + base).encode()).hexdigest()[:12], 16)
        rng = random.Random(seed)
        if rng.random() > AUG_FRACTION:
            try:
                shutil.copy2(f, dst); n_copy += 1
            except Exception as e:
                n_err += 1
            continue
        try:
            im = Image.open(f)
            alpha = im.getchannel("A") if im.mode in ("RGBA", "LA") else None
            rgb = jitter(im.convert("RGB"), rng)
            if alpha is not None:
                rgb = rgb.convert("RGBA")
                rgb.putalpha(soften_alpha(alpha, rng))
            rgb.save(dst)
            n_aug += 1
        except Exception as e:
            n_err += 1
            if n_err < 5:
                print(f"  err {sha[:8]}/{base}: {str(e)[:50]}", flush=True)
            try: shutil.copy2(f, dst)
            except Exception: pass
    if (i + 1) % 100 == 0:
        print(f"  {i+1}/{len(dirs)} dirs | {n_aug} augmented, {n_copy} clean, {n_err} err", flush=True)

print(f"\nDONE: {n_img} images | {n_aug} augmented | {n_copy} left clean | {n_err} errors", flush=True)
print(f"aug fraction actual: {n_aug/max(1,n_img):.2f} (target {AUG_FRACTION})", flush=True)
PY

status verify
python3 - <<'PY'
import glob, os
SRC="/workspace/alamcars/renders_cond"; DST="/workspace/alamcars/renders_cond_aug"
s=[os.path.basename(d) for d in glob.glob(SRC+"/*") if os.path.isdir(d)]
t=[os.path.basename(d) for d in glob.glob(DST+"/*") if os.path.isdir(d)]
print(f"shape dirs: src={len(s)} dst={len(t)} missing={len(set(s)-set(t))}")
bad=[d for d in t if len(glob.glob(f"{DST}/{d}/*"))==0]
print(f"empty dst dirs: {len(bad)}")
import random
for d in random.Random(0).sample(t, min(3,len(t))):
    a=len(glob.glob(f"{SRC}/{d}/*")); b=len(glob.glob(f"{DST}/{d}/*"))
    print(f"  {d[:10]}: src {a} views -> dst {b} views")
PY
du -sh "$DST" 2>/dev/null

status sample-out
# copy a few before/after pairs to LOCAL disk so they can be eyeballed over :8000
python3 - <<'PY'
import glob, os, shutil
SRC="/workspace/alamcars/renders_cond"; DST="/workspace/alamcars/renders_cond_aug"
os.makedirs("/root/augcond/samples", exist_ok=True)
dirs=sorted(glob.glob(DST+"/*"))[:6]
for i,d in enumerate(dirs):
    sha=os.path.basename(d)
    fs=sorted(glob.glob(d+"/*.png"))[:1] or sorted(glob.glob(d+"/*.jpg"))[:1]
    if not fs: continue
    b=os.path.basename(fs[0])
    try:
        shutil.copy2(f"{SRC}/{sha}/{b}", f"/root/augcond/samples/{i}_before_{b}")
        shutil.copy2(fs[0],              f"/root/augcond/samples/{i}_after_{b}")
    except Exception as e:
        print("sample skip", str(e)[:40])
print("samples:", len(os.listdir("/root/augcond/samples")))
PY

status DONE
sleep infinity
