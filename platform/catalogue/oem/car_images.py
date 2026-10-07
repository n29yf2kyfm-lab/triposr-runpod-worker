#!/usr/bin/env python3
"""One AI-generated picture per car model generation, for the Cars view.

    python3 platform/catalogue/oem/car_images.py [--limit=N] [--only=slug,slug]

Reads sources/models/models.json (built from Wikipedia) and, for each
generation without a picture, makes a clean studio render in one house style:
a white car, front three-quarter view, isolated on a plain white background
(the layout the owner asked for). Where the generation's Wikipedia infobox has
a photo, FLUX Kontext restages THAT car (so the generation is right: a text
prompt drew a Mk7.5 face when asked for a Golf Mk8); otherwise FLUX 1.1 pro
draws it from text. cars/index.json records which method made each picture. Saved as a 512 px WebP in
cars/<slug>.webp. Resumable.

These are AI ILLUSTRATIONS of the model, not photographs, and can get
details wrong; every page that shows one must say so. FAL_KEY is read from the
environment or /root/.alam3d_env and never written anywhere.
"""
import io, json, os, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'cars')
# A long run can write into PIC_STAGE/cars instead, outside the repo, so the working
# tree stays clean; pic_sync.py moves finished pictures into cars/ and commits them.
NEW = os.path.join(os.environ['PIC_STAGE'], 'cars') if os.environ.get('PIC_STAGE') else OUT


def have(name):
    return os.path.exists(os.path.join(OUT, name)) or os.path.exists(os.path.join(NEW, name))
sys.path.insert(0, HERE)
from illustrate import fal_key   # noqa: E402


def slug(row):
    return re.sub(r'[^a-z0-9]+', '-', f"{row['brand']} {row['generation']} {row['years'][0]}".lower()).strip('-')


EDIT = ('Make this exact car a clean studio product photograph: keep its exact body shape, headlights, grille, '
        'bumpers and wheels, repaint the body white, show it from the front-left corner at a 45 degree angle with the '
        'whole car in frame, isolated on a pure white seamless background, soft studio lighting, soft contact shadow, '
        'remove the number plate, the surroundings and any people')
UA = {'User-Agent': 'VWGroupPartsCatalogue/1.0 (research; one request at a time)'}


def prompt(row):
    """Text-only fallback, for a generation whose article has no photo."""
    return (f"Studio product photograph of a white {row['years'][0]} {row['generation']}, the real production car "
            "exactly as sold, seen from the front-left corner at a 45 degree angle so both the front and the left side "
            "are visible, whole car in frame with margin, isolated on a pure white seamless background, soft even "
            "studio lighting, soft contact shadow, everything in sharp focus, no text, no number plate, no people")


def reference(row):
    """The generation's own infobox photo from Wikimedia Commons, 1024 px, as a data URI (or None)."""
    import base64, urllib.parse
    if not row.get('image'):
        return None
    # Direct thumbnail URL on upload.wikimedia.org, built from Wikimedia's own
    # path scheme (md5 of the file name), so no API or redirect call is spent
    import hashlib
    name = row['image'].strip().replace(' ', '_')
    name = name[0].upper() + name[1:]
    h = hashlib.md5(name.encode()).hexdigest()
    q = urllib.parse.quote(name)
    u = f'https://upload.wikimedia.org/wikipedia/commons/thumb/{h[0]}/{h[:2]}/{q}/960px-{q}' + ('.png' if name.lower().endswith('.svg') else '')
    for i in range(5):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()
            time.sleep(2)
            return 'data:image/jpeg;base64,' + base64.b64encode(raw).decode()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(int(e.headers.get('Retry-After') or 15) + 2)
    return None


def fal(endpoint, body, token):
    rq = urllib.request.Request('https://fal.run/' + endpoint, data=json.dumps(body).encode(), method='POST',
                                headers={'Authorization': 'Key ' + token, 'Content-Type': 'application/json'})
    res = json.load(urllib.request.urlopen(rq, timeout=240))
    return urllib.request.urlopen(urllib.request.Request(res['images'][0]['url'], headers={'User-Agent': 'Mozilla/5.0'}), timeout=60).read()


def generate(row, token, model=None):
    """Photo-guided when the article has a photo (FLUX Kontext keeps the real
    generation's shape and only restages it), text-only (FLUX 1.1 pro) when not.
    Returns the method used, which the index records."""
    ref = reference(row)
    if ref:
        raw, how = fal('fal-ai/flux-pro/kontext', {'prompt': EDIT, 'image_url': ref}, token), 'photo-guided'
    else:
        raw, how = fal('fal-ai/flux-pro/v1.1', {'prompt': prompt(row), 'image_size': {'width': 768, 'height': 512}}, token), 'text-only'
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert('RGB')
    im.thumbnail((640, 640))
    im.save(os.path.join(NEW, slug(row) + '.webp'), 'WEBP', quality=80, method=6)
    return how


def main():
    opt = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    token = fal_key() or sys.exit('FAL_KEY is not set')
    os.makedirs(NEW, exist_ok=True)
    rows = json.load(open(os.path.join(HERE, 'sources', 'models', 'models.json')))
    if opt.get('only'):
        rows = [r for r in rows if slug(r) in opt['only'].split(',')]
    todo = [r for r in rows if opt.get('only') or not have(slug(r) + '.webp')]
    todo = todo[:int(opt.get('limit', 10 ** 6))]
    ip = os.path.join(NEW, 'index.json')
    if not os.path.exists(ip) and os.path.exists(os.path.join(OUT, 'index.json')):
        __import__('shutil').copyfile(os.path.join(OUT, 'index.json'), ip)
    index = json.load(open(ip)) if os.path.exists(ip) else {}
    print(f'CARS {len(rows)} generations, {len(todo)} to draw', flush=True)
    import threading
    from concurrent.futures import ThreadPoolExecutor
    lock, done = threading.Lock(), [0]

    def one(r):
        for attempt in range(3):
            try:
                how = generate(r, token)
                with lock:
                    index[slug(r)] = {'method': how, 'reference': r.get('image') or None, 'wikipedia_title': r['wikipedia_title']}
                    json.dump(index, open(ip, 'w'), indent=0)
                    done[0] += 1
                    print(f'CARS [{done[0]}/{len(todo)}] {slug(r)} ({how})', flush=True)
                return
            except Exception as ex:
                print(f'CARS retry {slug(r)}: {type(ex).__name__}: {str(ex)[:120]}', flush=True)
                time.sleep(2 ** (attempt + 1))

    with ThreadPoolExecutor(int(opt.get('workers', 4))) as pool:
        list(pool.map(one, todo))
    print('CARS_DONE', flush=True)


if __name__ == '__main__':
    main()
