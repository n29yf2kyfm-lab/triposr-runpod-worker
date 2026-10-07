"""Catalogue car pictures, one per generation, from a free FLUX Space on Hugging Face (ZeroGPU).

    python3 carimg.py list                 # how many generations still need a picture
    python3 carimg.py run [N] [--model schnell|dev] [--out DIR]

FLUX.1-schnell (Apache 2.0) is the default. FLUX.1-dev weights are under a non-commercial
licence; use it only after checking the licence covers the catalogue.
HF_TOKEN is read from the environment (cloud environment settings), never from tracked files.
Without it the anonymous ZeroGPU quota runs out after a picture or two. The run stops cleanly
when the daily quota is used up; run it again later and it carries on where it stopped.
"""
import json, os, re, sys, glob, shutil, collections

HERE = os.path.dirname(os.path.abspath(__file__))
SPACES = {'schnell': 'black-forest-labs/FLUX.1-schnell', 'dev': 'black-forest-labs/FLUX.1-dev'}
BODY = {'sedan': 'saloon', 'avant': 'Avant estate', 'variant': 'Variant estate', 'combi': 'Combi estate',
        'ST': 'ST estate', 'hatchback': 'hatchback', 'coupe': 'coupe', 'cabriolet': 'cabriolet',
        'double cab': 'double-cab pickup', 'single cab': 'single-cab pickup', 'dropside': 'dropside pickup',
        'van': 'panel van', 'kombi': 'minibus', 'caravelle': 'minibus', 'vario': 'estate'}

def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def generations():
    """One entry per (make, generation): earliest year and the commonest body across markets."""
    T = json.load(open(os.path.join(HERE, 'targets.json')))
    g = {}
    for t in T:
        k = (t['make'], t['gen'])
        e = g.setdefault(k, {'make': t['make'], 'gen': t['gen'], 'from': t['from'], 'to': t['to'],
                             'bodies': collections.Counter()})
        e['from'] = min(e['from'], t['from']); e['to'] = max(e['to'], t['to'])
        f = os.path.join(HERE, 'mods', t['code'] + '.json')
        if os.path.exists(f):
            for en in json.load(open(f)).get('engines', []):
                e['bodies'].update(en.get('bodies', []))
    for e in g.values():
        b = e.pop('bodies').most_common(1)
        e['body'] = BODY.get(b[0][0], b[0][0]) if b else ''
        e['file'] = f"{slug(e['make'])}/{slug(e['gen'])}-{e['from']}.webp"
    return sorted(g.values(), key=lambda e: (e['make'], e['gen'], e['from']))

def prompt(e):
    car = ' '.join(x for x in (str(e['from']), e['make'], e['gen'], e['body']) if x)
    return (f"Studio product photo of a {car}, metallic silver, front three-quarter view from the left, "
            "whole car in frame, centered, plain pure white background, soft even lighting, soft shadow "
            "under the car, sharp detail, catalogue style, no text, no watermark")

def main():
    a = sys.argv[1:]
    out = a[a.index('--out') + 1] if '--out' in a else os.path.join(HERE, 'cars_img')
    model = a[a.index('--model') + 1] if '--model' in a else 'schnell'
    G = generations()
    todo = [e for e in G if not os.path.exists(os.path.join(out, e['file']))]
    if not a or a[0] == 'list':
        print(f'{len(G)} generations, {len(G) - len(todo)} with a picture, {len(todo)} to do'); return
    n = int(a[1]) if len(a) > 1 and a[1].isdigit() else len(todo)
    from gradio_client import Client
    c = Client(SPACES[model], token=os.environ.get('HF_TOKEN') or None, verbose=False)
    idx_f = os.path.join(out, 'index.json')
    idx = json.load(open(idx_f)) if os.path.exists(idx_f) else {}
    made = 0
    for e in todo[:n]:
        p = prompt(e)
        kw = dict(prompt=p, seed=7, randomize_seed=False, width=1024, height=640, api_name='/infer')
        kw['num_inference_steps'] = 4 if model == 'schnell' else 28
        if model == 'dev': kw['guidance_scale'] = 3.5
        try:
            r = c.predict(**kw)
        except Exception as x:
            msg = str(x)
            if 'quota' in msg.lower() or 'runs limit' in msg.lower():
                print('daily ZeroGPU quota used up; run again later.'); break
            print('failed', e['make'], e['gen'], msg[:200]); continue
        dst = os.path.join(out, e['file']); os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(r[0] if isinstance(r, (list, tuple)) else r, dst)
        idx[e['file']] = {'make': e['make'], 'generation': e['gen'], 'from': e['from'], 'to': e['to'],
                          'model': SPACES[model], 'prompt': p, 'seed': 7}
        made += 1
        json.dump(idx, open(idx_f, 'w'), indent=1, sort_keys=True)
        print(f"{made}/{n} {e['file']}", flush=True)
    print(f'made {made}; {len(todo) - made} still to do')

if __name__ == '__main__':
    main()
