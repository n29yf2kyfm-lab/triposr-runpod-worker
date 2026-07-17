"""Build the LoRA dataset from Wikimedia Commons (licence-recorded).

For each manifest search term: query Commons, download JPEG results >=
min_width, centre-crop-resize to 1024, write caption (term-derived, in the
worker's vehicle-prompt vocabulary) into metadata.jsonl, and record the
file's licence + author into licences.csv for attribution.

Usage: python fetch_dataset.py manifest.json out_dir/
"""
import csv, io, json, os, re, sys, time
import requests
from PIL import Image

API = "https://commons.wikimedia.org/w/api.php"
# Wikimedia UA policy: descriptive agent + contact. Downloads without this
# (or from rate-limited datacenter IPs) get HTML error pages, which the
# v6 run decoded as "cannot identify image file" x hundreds -> 2 images.
UA = {"User-Agent": "ExpertCarCheckDatasetBot/1.1 "
                    "(https://github.com/n29yf2kyfm-lab/triposr-runpod-worker; "
                    "contact: ddmrnnnjc6@privaterelay.appleid.com) requests"}


def dl_image(url):
    """Download with status/content-type checks and 429-aware backoff."""
    for attempt in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=60)
        except Exception as e:
            print(f"  http error {e}; retry")
            time.sleep(3 * (attempt + 1))
            continue
        ct = r.headers.get("content-type", "")
        if r.status_code == 200 and ct.startswith("image/"):
            return r.content
        wait = int(r.headers.get("retry-after") or 0) or (3 * 2 ** attempt)
        print(f"  http {r.status_code} ct={ct[:20]}, backoff {wait}s")
        time.sleep(min(wait, 120))
    return None

def commons_search(term, limit):
    r = requests.get(API, params={
        "action": "query", "generator": "search",
        "gsrsearch": f"{term} filetype:bitmap", "gsrnamespace": 6,
        "gsrlimit": limit * 2, "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "format": "json"},
        headers=UA, timeout=30)
    r.raise_for_status()
    return (r.json().get("query", {}).get("pages", {}) or {}).values()

def caption_for(term):
    m = re.match(r"(.+?)\s+(\d{4})(.*)", term)
    if m:
        name, year, extra = m.group(1), m.group(2), m.group(3).strip()
        bits = [f"a {year} {name}"]
        if extra: bits.append(extra)
    else:
        bits = [f"a {term}"]
    bits += ["photorealistic dslr photograph", "eye-level view"]
    return ", ".join(bits)

def main(manifest_path, out_dir):
    mf = json.load(open(manifest_path))
    os.makedirs(out_dir, exist_ok=True)
    global white_background
    white_background = make_white_background()
    meta = open(os.path.join(out_dir, "metadata.jsonl"), "w")
    lic_f = open(os.path.join(out_dir, "licences.csv"), "w")
    lic = csv.writer(lic_f)
    lic.writerow(["file", "source_url", "licence", "artist"])
    n = 0
    for term in mf["search_terms"]:
        got = 0
        try:
            pages = commons_search(term, mf["images_per_term"])
        except Exception as e:
            print(f"  search failed {term}: {e}"); continue
        for p in pages:
            if got >= mf["images_per_term"]: break
            ii = (p.get("imageinfo") or [{}])[0]
            if ii.get("mime") != "image/jpeg" or ii.get("width", 0) < mf["min_width"]:
                continue
            try:
                img = dl_image(ii["url"])
                if img is None:
                    print("  skip: download failed after retries")
                    continue
                im = Image.open(io.BytesIO(img)).convert("RGB")
                s = 1024 / min(im.size)
                im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
                l, t = (im.width - 1024) // 2, (im.height - 1024) // 2
                im = im.crop((l, t, l + 1024, t + 1024))
                im = white_background(im)
                fn = f"{n:05d}.jpg"
                im.save(os.path.join(out_dir, fn), quality=92)
                meta.write(json.dumps({"file_name": fn, "text": caption_for(term)}) + "\n")
                em = ii.get("extmetadata") or {}
                lic.writerow([fn, ii.get("descriptionurl", ii["url"]),
                              (em.get("LicenseShortName") or {}).get("value", "?"),
                              re.sub(r"<[^>]+>", "", (em.get("Artist") or {}).get("value", "?"))[:120]])
                n += 1; got += 1
            except Exception as e:
                print(f"  skip: {e}")
            time.sleep(1.2)  # be polite to Commons (datacenter IPs get limited)
        print(f"{term}: {got}")
    meta.close()
    lic_f.close()
    print(f"TOTAL {n} images")

def make_white_background():
    """Composite each training photo onto white so the dataset matches the
    worker's generation style (single car, plain background — user request).
    Uses rembg when available (pod v2 installs it); otherwise a no-op so the
    fetch never fails on a missing extra."""
    if os.environ.get("WHITE_BG", "1") != "1":
        return lambda im: im
    try:
        from rembg import remove, new_session
        session = new_session("u2net")

        def _wb(im):
            try:
                cut = remove(im, session=session)  # RGBA
                from PIL import Image as _I
                bg = _I.new("RGB", cut.size, (255, 255, 255))
                bg.paste(cut, mask=cut.getchannel("A"))
                return bg
            except Exception:
                return im
        print("white-background: rembg active")
        return _wb
    except Exception:
        print("white-background: rembg unavailable, keeping originals")
        return lambda im: im


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
