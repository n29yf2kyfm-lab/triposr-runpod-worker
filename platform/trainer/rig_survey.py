#!/usr/bin/env python3
"""Which catalogue cars can be turned into Strip Bay cars CHEAPLY?

    python3 rig_survey.py parts_audit.json rig_survey.json

Reads only the glTF JSON chunk of each approved asset (two range requests)
and sorts every car into the route that would convert it:

  gamerig   a skinned game-vehicle rig with per-door bones
            (door_dside_f / door_pside_r ...). bake_rig.py + rig_canon.py
            convert it with no per-car work — proven on the Audi A6.
  conv3     the driving-sim mod family (door_FL, hood, trunk) the XC90 is
            from. The app reads it directly.
  named     doors named per corner some other way — needs a mapping.
  none      nothing that says "door" per corner.

It also records whether a file needs Draco decoding and its size, because
the app only wires the Meshopt decoder.
"""
import json, re, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from glb_parts import glb_json

rows = [r for r in json.load(open(sys.argv[1])) if 'url' in r]
out = sys.argv[2]

GAMERIG = re.compile(r'^door_(dside|pside)_[fr]', re.I)
CONV3 = re.compile(r'(^|_)door_?(FL|FR|RL|RR)(\b|_|\.|$)')
CORNER = re.compile(r'door.{0,12}(front|rear|fl|fr|rl|rr|lf|rf|lr|rr).{0,3}', re.I)

def one(r):
    try:
        j, _ = glb_json(r["url"])
    except Exception as e:
        return {'assetId': r['assetId'], 'error': str(e)[:80]}
    names = [n.get('name', '') for n in j.get('nodes', [])]
    g = sorted({n for n in names if GAMERIG.match(n)})
    c3 = [n for n in names if CONV3.search(n)]
    cn = [n for n in names if CORNER.search(n)]
    route = ('gamerig' if len(g) >= 4 and j.get('skins') else
             'conv3' if len({re.sub(r'.*door_?', '', n)[:2] for n in c3}) >= 4 else
             'named' if len(cn) >= 4 else 'none')
    return {'assetId': r['assetId'], 'make': r.get('make'), 'model': r.get('model'),
            'url': r['url'], 'route': route, 'skins': len(j.get('skins', [])),
            'draco': 'KHR_draco_mesh_compression' in (j.get('extensionsUsed') or []),
            'doors': g or c3[:6] or cn[:6],
            'hood': [n for n in names if re.search(r'hood|bonnet', n, re.I)][:3],
            'boot': [n for n in names if re.search(r'trunk|boot|tailgate|hatch', n, re.I)][:3],
            'engine': [n for n in names if re.search(r'engine', n, re.I)][:3]}

with ThreadPoolExecutor(4) as ex:
    res = list(ex.map(one, rows))
json.dump(res, open(out, 'w'), indent=1)
from collections import Counter
print(Counter(r.get('route', 'error') for r in res))
