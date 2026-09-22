#!/usr/bin/env python3
"""Turn `glb_parts.py --all` output into the answer to one question:

    HOW MANY CATALOGUE CARS CAN BE TAKEN APART THE WAY THE MK8 GOLF CAN,
    AND WHAT WOULD IT TAKE TO ADD THE REST?

The buckets are ordered by what the NEXT piece of work would be, because
that is the only thing the number is for:

  GOLF STANDARD          works in Strip Bay today, no code change
  GOLF STANDARD (conv 2) works the moment `classify()` learns one more
                         naming convention — a regex change, no geometry
  separable, other naming        has the parts, under a naming nobody has
                         mapped yet. Needs a convention written per family.
  split but UNNAMED      geometry IS split into parts, but every mesh is
                         called `Object_41`. No regex reaches it; it needs
                         a GEOMETRIC classifier (position, size, symmetry).
  FUSED SHELL            a handful of welded meshes. Needs segmentation or
                         a different source. This is the bucket to stop
                         spending on.

It also answers the engine question with a measurement rather than a
quotation — see the note in glb_parts.py.
"""
import json, sys, re
from collections import Counter, defaultdict

rows = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'parts_audit.json'))
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from glb_parts import verdict, NEEDED

ok = [r for r in rows if 'error' not in r]
print(f'{len(rows)} assets audited, {len(rows)-len(ok)} unreadable\n')

print('═══ CAN IT BE TAKEN APART? ═══')
buckets = defaultdict(list)
for r in rows:
    buckets[verdict(r)].append(r)
order = ['GOLF STANDARD', 'GOLF STANDARD (conv 2)', 'separable, other naming',
         'partial', 'split but UNNAMED', 'FUSED SHELL', 'ERROR']
for v in order:
    b = buckets.get(v, [])
    if b:
        print(f'{len(b):>5}  {len(b)/len(rows)*100:>5.1f}%  {v}')

# ── which of the six jobs each car could run ────────────────────────────
print('\n═══ PER JOB, ACROSS THE WHOLE LIBRARY ═══')
print('(strict = the app today; +conv2 = after one regex change)')
for label in NEEDED:
    n1 = sum(1 for r in ok if r['strict'].get(label, '0/1').split('/')[0]
             == r['strict'][label].split('/')[1])
    n2 = sum(1 for r in ok
             if r.get('strict2', {}).get(label, '0/1').split('/')[0]
             == r.get('strict2', {}).get(label, '0/1').split('/')[1])
    both = sum(1 for r in ok if
               r['strict'][label].split('/')[0] == r['strict'][label].split('/')[1]
               or r.get('strict2', {}).get(label, '0/1').split('/')[0]
               == r.get('strict2', {}).get(label, '0/1').split('/')[1])
    print(f'  {label:<9} strict {n1:>4}   conv2 {n2:>4}   either {both:>4}'
          f'   ({NEEDED[label][1]})')

# ── the engine question, measured ───────────────────────────────────────
print('\n═══ ENGINE / SUSPENSION / EXHAUST — asked for, and searched for ═══')
for k in ('engine', 'suspension', 'exhaust'):
    hits = [r for r in ok if k in r.get('broad', {})]
    print(f'  {k:<11} named in {len(hits):>4} of {len(ok)} assets')
    for r in hits[:6]:
        print(f'        {r["assetId"]:<44} {r["broad"][k]} matching names')
    if len(hits) > 6:
        print(f'        … and {len(hits)-6} more')

# ── the cars worth acting on ────────────────────────────────────────────
print('\n═══ READY OR NEARLY READY (best first) ═══')
cand = [r for r in ok if verdict(r) in
        ('GOLF STANDARD', 'GOLF STANDARD (conv 2)', 'separable, other naming')]


def score(r):
    """How many of the six jobs this car could run under EITHER ruleset."""
    n = 0
    for label, (ids, _b) in NEEDED.items():
        for s in (r['strict'].get(label), r.get('strict2', {}).get(label)):
            if s and s.split('/')[0] == s.split('/')[1]:
                n += 1
                break
    return n


cand.sort(key=lambda r: (-score(r), r['assetId']))
for r in cand[:40]:
    got = [l for l in NEEDED
           if r['strict'][l].split('/')[0] == r['strict'][l].split('/')[1]
           or r.get('strict2', {}).get(l, '0/1').split('/')[0]
           == r.get('strict2', {}).get(l, '0/1').split('/')[1]]
    print(f'  {score(r)}/6  {r["assetId"]:<44} {",".join(got)}')
if len(cand) > 40:
    print(f'  … and {len(cand)-40} more in these buckets')

# ── naming families, so the next convention is written from data ────────
print('\n═══ NAMING FAMILIES IN THE "other naming" BUCKET ═══')
print('(first sample name per car, collapsed — write the next ruleset from these)')
fam = Counter()
for r in buckets.get('separable, other naming', []) + buckets.get('partial', []):
    for n in r.get('sampleNames', [])[:3]:
        sig = re.sub(r'\d+', '#', n)[:34]
        fam[sig] += 1
for sig, n in fam.most_common(22):
    print(f'  {n:>4}  {sig}')
