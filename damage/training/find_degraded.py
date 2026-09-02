"""Per-image colourfulness and roughness for the whole corpus.

Calibrated on the 192 hand-read images: 8 of the 9 files marked "degraded"
have mean chroma 0.0 (a greyscale copy left behind by a source project's
augmentation), and the ninth, the one that is genuinely grey static, has a
pixel-to-pixel roughness of 39 against a maximum of 31.7 across everything
else. Both signals are computed at 160px, so this is ~5ms per image.
"""
import json, os, sys
import numpy as np
from PIL import Image
from concurrent.futures import ProcessPoolExecutor

def feats(p):
    try:
        im = Image.open(p)
        im.draft("RGB", (160, 160))      # decode the JPEG at 1/4 scale: 4-8x faster
        im = im.convert("RGB").resize((160, 160))
        a = np.asarray(im).astype(np.float32)
        chroma = float(np.mean(np.max(a, 2) - np.min(a, 2)))
        g = a.mean(2)
        rough = float(np.mean(np.abs(g[1:, 1:] - g[:-1, :-1])))
        return {"file": p, "chroma": round(chroma, 2), "rough": round(rough, 2)}
    except Exception as e:
        return {"file": p, "error": str(e)[:60]}

if __name__ == "__main__":
    paths = [l.strip() for l in open(sys.argv[1])]
    with ProcessPoolExecutor(3) as ex, open(sys.argv[2], "w") as f:
        for n, r in enumerate(ex.map(feats, paths, chunksize=64)):
            f.write(json.dumps(r) + "\n")
            if (n + 1) % 20000 == 0:
                print(f"  {n+1:,}/{len(paths):,}", flush=True)
    print("done")
