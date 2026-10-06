#!/usr/bin/env python3
"""Generate ONE AI illustration per part type for the OEM catalogue.

    python3 platform/catalogue/oem/illustrate.py [--limit=N] [--only=key,key] [--force=key,key]

Reads parts.json, groups part types into illustration keys (every bolt shares
one bolt picture), and for each key without an image asks fal.ai's FLUX
schnell model for a plain studio product shot, saved as a 512 px WebP in
illustrations/<key>.webp. Resumable: existing images are kept.

These are ILLUSTRATIONS of the kind of part, not photographs of the part
with that OEM number, and every page that shows one must say so. FAL_KEY is
read from the environment or /root/.alam3d_env; it is never written anywhere.
"""
import io, json, os, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'illustrations')
MODEL = 'https://fal.run/fal-ai/flux/schnell'

# generic hardware shares one picture per kind
GENERIC = [(r'\bbolt\b|\bscrew\b|\bstud\b', 'bolt'), (r'\bnut\b', 'nut'),
           (r'\bwasher\b(?!.*(nozzle|fluid|pump|reservoir|hose))', 'washer'),
           (r'\bclip\b|\bclamp\b|\bretainer\b', 'clip'), (r'o ring', 'o-ring'), (r'\bgasket\b', 'gasket'),
           (r'\bseal\b', 'seal'), (r'\bbracket\b|\bholder\b|\bhanger\b', 'bracket'), (r'\bcap\b', 'cap'),
           (r'\bbulb\b', 'bulb'), (r'\bhose\b', 'hose'), (r'\bpipe\b|\bline\b|\btube\b', 'pipe')]
SPELL = {'a c': 'A/C', 'abs': 'ABS', 'ecm': 'engine control module'}
# keys whose plain name drew the wrong part (checked by eye on a contact sheet)
DESCRIBE = {
    'balance-shaft': 'single engine balance shaft lying flat, cast iron, with two large half-moon counterweights, no wheels, no joints',
    'crankshaft': 'bare inline-four engine crankshaft lying flat, forged steel, zig-zag crank throws with flat counterweights between polished journals, no CV joints',
    'engine-camshaft': 'bare engine camshaft lying flat, one long polished steel rod with eight egg-shaped cam lobes along it, no springs',
    'camshaft': 'bare engine camshaft lying flat, one long polished steel rod with eight egg-shaped cam lobes along it, no springs',
    'alternator-pulley-hardware': 'small set of alternator pulley fasteners: one nut, one washer and a plastic dust cap',
    'engine-cover-emblem': 'small plain round blank grey plastic badge with no symbol',
    'valve-lifters': 'three small cylindrical steel hydraulic valve lifters (tappets), shiny metal cups',
    'timing-cover': 'black moulded plastic engine timing belt cover, a long flat curved shroud with bolt holes',
    'valve-keeper': 'pair of tiny half-cone steel valve keepers (collets) next to a valve spring retainer',
}
# FLUX schnell drew these wrong three times over (drive axles for both shafts,
# a belt for the cover). No picture is better than a wrong one: never generated.
NO_IMAGE = {'balance-shaft', 'crankshaft', 'timing-cover'}


def illustration_key(part_type):
    for rx, k in GENERIC:
        if re.search(rx, part_type):
            return k
    return re.sub(r'[^a-z0-9]+', '-', part_type).strip('-')


def prompt(key):
    words = DESCRIBE.get(key) or key.replace('-', ' ')
    for a, b in SPELL.items():
        words = re.sub(rf'\b{a}\b', b, words)
    return (f'Studio product photograph of a single new genuine automotive {words}, car part, '
            'isolated on a plain light grey background, soft even lighting, sharp focus, '
            'three-quarter view, no text, no logo, no packaging, no hands')


def fal_key():
    k = os.environ.get('FAL_KEY')
    if not k and os.path.exists('/root/.alam3d_env'):
        for line in open('/root/.alam3d_env'):
            if line.startswith('FAL_KEY='):
                k = line.split('=', 1)[1].strip().strip('"\'')
    return k


def generate(key, token):
    body = json.dumps({'prompt': prompt(key), 'image_size': {'width': 512, 'height': 512},
                       'num_inference_steps': 4, 'num_images': 1, 'enable_safety_checker': True}).encode()
    rq = urllib.request.Request(MODEL, data=body, method='POST',
                                headers={'Authorization': 'Key ' + token, 'Content-Type': 'application/json'})
    res = json.load(urllib.request.urlopen(rq, timeout=120))
    url = res['images'][0]['url']
    raw = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=60).read()
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert('RGB')
    im.save(os.path.join(OUT, key + '.webp'), 'WEBP', quality=80, method=6)


def main():
    opt = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    token = fal_key()
    if not token:
        sys.exit('FAL_KEY is not set and is not in /root/.alam3d_env')
    os.makedirs(OUT, exist_ok=True)
    parts = json.load(open(os.path.join(HERE, 'parts.json')))
    keys = sorted({illustration_key(p['part_type']) for p in parts})
    if opt.get('only'):
        keys = [k for k in keys if k in opt['only'].split(',')]
    force = set(opt.get('force', '').split(',')) - {''}
    todo = [k for k in keys if k not in NO_IMAGE and (k in force or not os.path.exists(os.path.join(OUT, k + '.webp')))][:int(opt.get('limit', 10 ** 6))]
    print(f'ILLUSTRATE {len(keys)} part types, {len(keys) - len(todo)} done, {len(todo)} to make', flush=True)
    for i, k in enumerate(todo, 1):
        for attempt in range(3):
            try:
                generate(k, token)
                print(f'ILLUSTRATE [{i}/{len(todo)}] {k}', flush=True)
                break
            except Exception as ex:
                print(f'ILLUSTRATE retry {k}: {type(ex).__name__}: {str(ex)[:120]}', flush=True)
                time.sleep(2 ** (attempt + 1))
    print('ILLUSTRATE_DONE', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
