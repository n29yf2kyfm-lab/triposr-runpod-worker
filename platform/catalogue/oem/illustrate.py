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
import glob, io, json, os, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'illustrations')
MODEL = 'https://fal.run/fal-ai/flux/schnell'

# generic hardware shares one picture per kind
GENERIC = [(r'\bwarranty\b|\binstructions\b|\bbooklet\b|\bowners? manual\b|\bmanual ed\b|\bservice book', 'printed-booklet'),
           (r'\bbolt\b|\bscrew\b|\bstud\b', 'bolt'), (r'\bnut\b', 'nut'),
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
    'suspension-control-arm-bushing': 'round rubber-and-steel suspension bushing: a short steel sleeve inside a thick black rubber cylinder inside an outer steel ring',
    'spindle': 'cast iron front suspension steering knuckle with wheel spindle, strut mounting ears and ball joint boss',
    'disc-brake-pad': 'pair of disc brake pads, each a steel backing plate with a thick grey friction block, no rotor',
    'headlight-hardware': 'small set of headlamp mounting screws, plastic clips and a bracket',
    'exhaust-heat-shield': 'pressed aluminium exhaust heat shield, a thin dimpled curved metal sheet with mounting holes, no pipe',
    # second contact-sheet pass (2019 Golf electrical/body): brand logos, wrong objects
    'grille-emblem': 'plain round blank chrome badge disc with a smooth empty face, no letters, no symbol, no logo',
    'hatch-emblem': 'plain round blank chrome badge disc with a smooth empty face, no letters, no symbol, no logo',
    'clutch-flywheel': 'engine dual-mass flywheel, a heavy flat steel disc with a toothed starter ring gear around its edge and bolt holes in the centre, not a road wheel',
    'boot': 'black ribbed rubber CV joint boot, a concertina bellows cone with two clamp grooves',
    '12-volt-accessory-power-outlet': 'car 12 volt cigarette-lighter style power socket, a round black cylindrical socket with a single centre contact',
    '12-volt-accessory-power-outlet-housing': 'black plastic housing for a car 12 volt cigarette-lighter style round socket',
    '12-volt-accessory-power-outlet-cover': 'small round black hinged plastic cap for a car 12 volt cigarette-lighter style socket',
    'door-interior-reflector': 'small thin red rectangular plastic reflector strip for the edge of a car door trim panel',
    'door-check-cover': 'small black plastic cover cap for a car door check strap',
    'fender-mtg-bkt': 'small stamped steel mounting bracket for a car front wing, a bent flat plate with bolt holes',
    'floor-jack': 'compact car scissor jack from a spare-wheel kit, folded steel diamond frame with a threaded rod',
    'interior-view-mirror-cover': 'small black plastic cover that clips over a rear-view mirror mount on a windscreen',
    'interior-view-mirror-cover-access-cover': 'small black plastic cover that clips over a rear-view mirror mount on a windscreen',
    # third contact-sheet pass: small stops drawn as car bumpers, wheels drawn for non-wheels
    'lift-gate-glass-bumper': 'small black rubber stop buffer, a short cylindrical rubber stud with a mounting peg',
    'lift-gate-stop-bumper': 'small black rubber stop buffer, a short cylindrical rubber stud with a mounting peg',
    'overslam-bumper': 'small black rubber stop buffer, a short cylindrical rubber stud with a mounting peg',
    'tank-strap': 'long flat steel fuel tank strap, a bent galvanised metal band with a bolt hole at each end',
    'slave-cylinder': 'clutch slave cylinder, a small cylindrical hydraulic actuator with a push rod and bleed nipple, no reservoir',
    'wheel-housing-access-cover': 'small black moulded plastic oval access cover panel with clips',
    'wheel-housing-panel': 'black moulded plastic wheel arch liner, a curved half-round shell, no wheel',
    'tow-eye': 'screw-in steel towing eye, a short threaded rod with a closed round ring at one end, no wheel',
    'splash-guard': 'black rubber mud flap, a flat moulded rubber panel with mounting holes',
    'splash-guards-black': 'black rubber mud flap, a flat moulded rubber panel with mounting holes',
    # fourth contact-sheet pass (Audi/Porsche sitemaps): manuals drawn as cars, a sneaker for a brake shoe
    'printed-booklet': 'closed plain printed paper booklet with a blank cover, lying flat, no car, no text',
    'shoe': 'drum brake shoe, a curved steel crescent with a thick friction lining on its outer face, no footwear',
    'central-computer': 'plain black rectangular automotive electronic control unit box with a connector socket, no text, no letters',
    'data-plate-for-tyre-pressure': 'small flat printed rectangular sticker label with a blank table grid, no screen, no digits',
}
# FLUX schnell drew these wrong three times over (drive axles for both shafts,
# a belt for the cover, a bracket for the spindle; 'repair' names no part). No picture is better than a wrong one: never generated.
NO_IMAGE = {'balance-shaft', 'crankshaft', 'timing-cover', 'spindle', 'repair', 'brest-rel', 'floor-jack', 'interior-view-mirror-cover', 'interior-view-mirror-cover-access-cover',
            'lift-gate-packing', 'member', 'protect-plate', 'spare-tire-label', 'tire-information-label',
            'vehicle-lifting-jack-handle-black', 'tire-repair', 'wheel-housing-panel', 'slave-cylinder', 'air-bag-information-label', 'foam-part'}


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
    from collections import Counter
    sys.path.insert(0, HERE)
    from build_catalogue import part_type
    # every part type in the catalogue, most common first, so the pictures
    # that cover the most parts are made first (the full list runs to tens of
    # thousands of types once every Group brand's sitemap is in)
    count = Counter(illustration_key(p['part_type']) for p in json.load(open(os.path.join(HERE, 'parts.json'))))
    for f in glob.glob(os.path.join(HERE, 'more', '*_*.json')):
        count.update(illustration_key(part_type(w.replace('-', ' '))) for _, w, *_ in json.load(open(f)))
    keys = [k for k, _ in count.most_common()]
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
