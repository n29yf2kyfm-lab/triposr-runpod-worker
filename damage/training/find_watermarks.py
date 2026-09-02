"""Read stock-agency watermarks with OCR instead of guessing from statistics.

An earlier attempt fitted image statistics (edge energy in a bottom strip,
FFT periodicity, local contrast) against one watermarked cluster and one clean
one. All three signals separated in the OPPOSITE direction to design, because
with one cluster per class it was measuring two specific photographs, not
watermarks. That approach is abandoned.

Watermarks are text saying who owns the image. Tesseract can read it. A hit on
a literal agency name is evidence; a statistic that correlates with one is not.

Only two strips are OCR'd, not the whole frame: the bottom eighth, where the
credit line sits, and a central band, where the large diagonal overlay sits.
Full-frame OCR on 170k images is hours of CPU and mostly reads number plates.
"""
import difflib, os, re, sys
from concurrent.futures import ThreadPoolExecutor

AGENCIES = ("shutterstock", "alamy", "istock", "canstock", "dreamstime",
            "123rf", "depositphotos", "getty", "adobestock", "easyfotostock",
            "stockphoto", "bigstock", "fotolia")
_RX = re.compile("|".join(AGENCIES), re.I)

# FUZZY, because a semi-transparent overlay over car paint defeats exact
# matching: "shutterstock.com - 752591965" came back as "shintterstock corm
# 75259". Measured on 192 hand-read images, exact matching scored 36% recall
# and fuzzy 43%, both at 100% precision with zero false positives.
_CREDIT = re.compile(r"\b\w*c[o0]r?m\b[^0-9]{0,12}\d{6,}")


def match(text):
    """Agency names in `text`, tolerant of OCR damage."""
    out = set()
    for w in re.findall(r"[A-Za-z]{4,}", text.lower()):
        for a in AGENCIES:
            if difflib.SequenceMatcher(None, w, a).ratio() >= 0.72:
                out.add(a)
    if _CREDIT.search(text.lower()):
        out.add("credit-line")
    return sorted(out)


def read(path):
    from PIL import Image
    import pytesseract
    try:
        with Image.open(path) as im:
            im = im.convert("L")
            W, H = im.size
            strips = [im.crop((0, int(H * 0.86), W, H)),        # credit line
                      im.crop((0, int(H * 0.35), W, int(H * 0.65)))]  # overlay
            txt = ""
            for s in strips:
                if s.width < 40 or s.height < 8:
                    continue
                # CAP THE WIDTH, do not blindly upscale, and time each call
                # out. On the ~4.7% of this corpus that augmentation reduced
                # to grey static, --psm 6 hunts for text lines across the
                # whole strip and does not converge: individual calls were
                # measured at over three minutes, load average reached 24 on
                # a 4-core box, and a full scan projected to 2,800 hours.
                # UPSCALE. Capping the width to 1600 downscaled the strips of
                # large images, shrank the watermark type, and cut measured
                # recall on a hand-labelled set from 43% to 15% -- tesseract
                # still saw the text but read it as garbage ("Crparmtore
                # turn"), so it matched nothing. The 8s timeout below is what
                # actually fixes the stalls; the width cap only cost accuracy.
                # Only genuinely enormous strips are held back.
                if s.width * 2 <= 4000:
                    s = s.resize((s.width * 2, s.height * 2))
                try:
                    txt += " " + pytesseract.image_to_string(
                        s, config="--psm 6", timeout=8)
                except Exception:
                    pass          # a strip that will not read yields no hit
    except Exception as e:
        return {"file": path, "ok": False, "error": str(e)[:70]}
    hits = match(txt)
    return {"file": path, "ok": True, "hits": hits,
            "text": " ".join(txt.split())[:120]}


def main():
    files = [l.strip() for l in open(sys.argv[1])]
    out = sys.argv[2]
    # RESUME. This scan runs for hours and the container it runs in can be
    # restarted out from under it -- which happened, 1,343 images in. Re-read
    # whatever the output file already holds and skip those paths, so a
    # restart costs the work in flight rather than the work completed.
    import json as _j
    done = set()
    if os.path.exists(out):
        for line in open(out):
            try:
                done.add(_j.loads(line)["file"])
            except Exception:
                pass                       # a torn final line is simply redone
    if done:
        files = [f for f in files if f not in done]
        print(f"resuming: {len(done):,} already scanned, {len(files):,} to go",
              flush=True)
    # Threads, not processes: pytesseract shells out to the tesseract
    # binary, so the GIL is released during the wait -- and nesting that
    # subprocess inside a forked ProcessPoolExecutor deadlocked outright
    # (192 images ran 25 minutes and produced nothing, against 0.4s each
    # when run serially).
    # TWO workers, not six. This box has four cores and each worker shells
    # out to tesseract three times per image; at six the load average
    # reached 37, throughput fell to 13 images/minute, and unrelated
    # commands on the same box began timing out. Oversubscription was
    # costing more than the parallelism gained.
    with ThreadPoolExecutor(max_workers=2) as ex, open(out, "a") as f:
        import json
        for n, r in enumerate(ex.map(read, files, chunksize=8)):
            f.write(json.dumps(r) + "\n")
            if (n + 1) % 500 == 0:
                print(f"  {n+1:,}/{len(files):,}", flush=True)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
