#!/usr/bin/env python3
"""Vehicle in, showcase out: the car with its doors open, glass cleared and an
engine in the bay.

    python3 platform/rigmachine/car.py OUT_DIR --make=Audi --model=RS6 --year=2021 \
        [--fuel=PETROL] [--cc=3996] [--body=estate] [--colour=GREY] [--size=1280x800] [--samples=24]
    python3 platform/rigmachine/car.py OUT_DIR --vehicle='{"make":"Audi","model":"RS6",...}'

The input is what the app ALREADY decodes from a registration (make, model,
year, and DVLA's fuel type, engine size and colour). The registration itself is
never an input, never logged and never stored — the same rule as the resolver.
DVLA's own lookup returns make but not model, so the model has to come from
the app's decode.

1. asks the live resolver logic (platform/resolver/index.ts, unchanged) which
   catalogue car matches, with its honesty disclosure (exact / representative)
2. picks a representative engine: electric drive unit for ELECTRICITY, a V8
   from 3.5 litres up, otherwise an inline four; mounted along the car for the
   makes that do that, across it otherwise. It is a stand-in, labelled as one.
3. runs the rig machine in showcase mode on that car (run.py --showcase)

Writes result.json with the resolver's answer, the engine choice and why, and
everything run.py writes. Exit 0 rigged, 2 refused or no catalogue match, 1 error.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))

# makes whose engines sit LENGTHWAYS in their normal cars; everything else is
# assumed transverse. Representative, not per-model truth.
LONG_MAKES = {'bmw', 'mercedes-benz', 'mercedes', 'jaguar', 'land rover', 'porsche', 'lexus',
              'maserati', 'alfa romeo', 'genesis', 'infiniti', 'rolls-royce', 'bentley', 'aston martin'}
AUDI_TRANSVERSE = {'a1', 'a2', 'a3', 's3', 'rs3', 'q2', 'q3', 'rsq3', 'tt', 'tts', 'ttrs'}


def pick_engine(v):
    fuel = (v.get('fuel') or '').upper()
    cc = int(v.get('cc') or v.get('engineCapacity') or 0)
    make = (v.get('make') or '').lower()
    model = (v.get('model') or '').lower().replace(' ', '')
    if fuel == 'ELECTRICITY':
        return 'ev', 'trans', 'DVLA fuel type is electricity'
    kind, why = ('v8', f'{cc} cc is V8 territory') if cc >= 3500 else ('i4', f'{cc} cc' if cc else 'engine size unknown')
    long_ = make in LONG_MAKES or (make == 'audi' and model not in AUDI_TRANSVERSE) or kind == 'v8'
    return kind, 'long' if long_ else 'trans', why + (', mounted lengthways for this make' if long_ else ', mounted across the car')


def resolve(v):
    body = json.dumps({k: v[k] for k in ('make', 'model', 'year', 'bodyStyle', 'fuel', 'colour', 'generation', 'trim')
                       if v.get(k) not in (None, '')})
    out = subprocess.run(['node', '--no-warnings', '--experimental-strip-types', os.path.join(HERE, 'resolve.mjs'), body],
                         capture_output=True, text=True, timeout=120)
    if out.returncode:
        raise RuntimeError('resolver failed: ' + out.stderr[-400:])
    return json.loads(out.stdout)


def main():
    args = sys.argv[1:]
    pos = [a for a in args if not a.startswith('--')]
    opt = dict(a[2:].split('=', 1) for a in args if a.startswith('--') and '=' in a)
    if len(pos) != 1:
        print(__doc__)
        return 1
    out = pos[0]
    os.makedirs(out, exist_ok=True)
    v = json.loads(opt.pop('vehicle')) if 'vehicle' in opt else {}
    for k, key in (('make', 'make'), ('model', 'model'), ('year', 'year'), ('fuel', 'fuel'), ('cc', 'cc'),
                   ('body', 'bodyStyle'), ('colour', 'colour')):
        if k in opt:
            v[key] = opt.pop(k)
    v.pop('registration', None)                  # never carried forward, even if a caller sends it
    v.pop('reg', None)
    if not v.get('make') or not v.get('model'):
        print('give --make and --model (the app decodes them from the reg)')
        return 1
    res = resolve(v)
    kind, mount, why = pick_engine(v)
    summary = {'vehicle': v, 'resolver': {'match': res.get('match'), 'resolution': res.get('resolution'),
                                          'asset': (res.get('asset') or {}).get('glbUrl')},
               'engine_choice': {'kind': kind, 'mount': mount, 'why': why}}
    glb = (res.get('asset') or {}).get('glbUrl')
    if not glb:
        summary['status'] = 'no-match'
        summary['why'] = (res.get('resolution') or {}).get('disclosure') or 'no catalogue car matches this vehicle'
        json.dump(summary, open(os.path.join(out, 'result.json'), 'w'), indent=1)
        print(json.dumps({'status': 'no-match', 'why': summary['why']}))
        return 2
    extra = [a for a in args if a.startswith(('--size=', '--samples='))]
    # the body style decides two doors or four when doors are cut from a welded body
    # (the matched catalogue car's style first: it is that mesh that gets cut)
    body = (res.get('vehicle') or {}).get('bodyStyle') or v.get('bodyStyle') or ''
    rc = subprocess.call([sys.executable, os.path.join(HERE, 'run.py'), glb, out, '--showcase',
                          f'--engine={kind}', f'--mount={mount}'] + extra, env=dict(os.environ, SB_BODY=body))
    rp = os.path.join(out, 'result.json')
    r = json.load(open(rp)) if os.path.exists(rp) else {'status': 'error'}
    r.update(summary)
    json.dump(r, open(rp, 'w'), indent=1)
    if os.path.exists(os.path.join(out, 'viewer.html')):     # say on the page which car this is, and how sure
        sys.path.insert(0, HERE)
        import run
        run.viewer(out, r)
    return rc


if __name__ == '__main__':
    sys.exit(main())
