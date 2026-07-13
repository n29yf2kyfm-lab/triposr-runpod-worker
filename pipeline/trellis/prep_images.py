"""prep_images.py — STAGE 1-2: prepare clean reference images for TRELLIS.2.

Produces upright, background-removed, neutral-padded square images. Feeds them
to TRELLIS.2 as RGBA cutouts (the handler skips its own bg-removal when alpha
is present -> cleaner shape).

Deps (all free): pillow, rembg (u2net/BiRefNet, MIT/Apache), numpy.
  pip install pillow rembg onnxruntime numpy

Run:
  python pipeline/trellis/prep_images.py --in refs/ --out pipeline/build/prepped \
      --model birefnet-general

HONEST LIMITATIONS (stage 1-2):
  • Glossy car paint mirrors the sky -> the matte-cutout models leak reflections
    into "foreground". BiRefNet-general is the best free option but still errs on
    chrome/glass. Manual mask cleanup in GIMP/Krita is sometimes needed.
  • TRELLIS.2 shape quality tracks the CLEANEST 3/4 view. Side-profile and
    cluttered/partial shots produce worse geometry — cull them here, don't feed
    them.
  • Best inputs: studio/clean-background 3/4 front and 3/4 rear, car filling
    ~80% of frame, even light, minimal reflection. Phone snaps in car parks are
    marginal.
"""
import os, sys, glob, argparse
from PIL import Image, ImageOps
import numpy as np

def prep_one(path, out_dir, session, pad=0.12, size=1024):
    import rembg
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    # auto-upright: cars are wider than tall; rotate portrait phone shots
    if im.height > im.width:
        im = im.rotate(-90, expand=True)
    im.thumbnail((1600, 1600))
    cut = rembg.remove(im, session=session,
                       alpha_matting=True, alpha_matting_foreground_threshold=250,
                       alpha_matting_background_threshold=20)  # RGBA
    a = np.array(cut)[:, :, 3]
    cov = (a > 12).mean()
    ys, xs = np.where(a > 12)
    if len(xs) < 100:
        return None, cov
    # tight crop to the car + symmetric pad, then letterbox to a square canvas
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    cut = cut.crop((x0, y0, x1, y1))
    w, h = cut.size; side = int(max(w, h) * (1 + 2 * pad))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(cut, ((side - w) // 2, (side - h) // 2))
    canvas = canvas.resize((size, size), Image.LANCZOS)
    name = os.path.splitext(os.path.basename(path))[0]
    outp = os.path.join(out_dir, name + "_prepped.png")
    canvas.save(outp)
    return outp, cov

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="birefnet-general")   # or u2net
    ap.add_argument("--min-cov", type=float, default=0.18)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    import rembg
    sess = rembg.new_session(a.model)
    paths = sorted(sum([glob.glob(os.path.join(a.inp, e)) for e in ("*.jpg","*.jpeg","*.png")], []))
    kept = []
    for p in paths:
        outp, cov = prep_one(p, a.out, sess)
        flag = "KEEP" if (outp and cov >= a.min_cov) else "CULL"
        print(f"{flag}  cov={cov:.2f}  {os.path.basename(p)} -> {os.path.basename(outp) if outp else '-'}")
        if flag == "KEEP":
            kept.append(outp)
    print(f"\nprepped {len(kept)}/{len(paths)} usable images -> {a.out}")
    if not kept:
        print("NONE usable — inputs too reflective/cluttered/partial. Reshoot on a "
              "plain background, even light, car filling the frame.")
