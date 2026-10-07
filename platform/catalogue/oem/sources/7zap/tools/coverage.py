import json, os, glob, collections, sys
HERE = os.path.dirname(os.path.abspath(__file__))
T = json.load(open(os.path.join(HERE, 'targets.json')))
done = {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob(os.path.join(HERE, 'mods', '*.json'))}
skip = {w for w in open(os.path.join(HERE, 'skip.txt')).read().split() if w.startswith('gen_')}
by = 'market' if '--market' in sys.argv else 'make'
rows = collections.OrderedDict()
for t in sorted(T, key=lambda t: (t['market'] != 'Europe', t[by])) if by == 'market' else T:
    r = rows.setdefault(t[by], collections.Counter())
    r['generations'] += 1
    if t['code'] in done:
        r['fetched'] += 1
        d = done[t['code']]
        r['engines'] += len(d['engines'])
        r['variants'] += d['modifications']
        if any(e['trims'] for e in d['engines']): r['with trim names'] += 1
    elif t['code'] in skip: r['too big'] += 1
    else: r['to do'] += 1
cols = ['generations', 'fetched', 'too big', 'to do', 'engines', 'variants', 'with trim names']
print(by.ljust(12) + ''.join(c.rjust(16) for c in cols))
tot = collections.Counter()
for m, r in rows.items():
    tot.update(r); print(m.ljust(12) + ''.join(str(r[c]).rjust(16) for c in cols))
print('TOTAL'.ljust(12) + ''.join(str(tot[c]).rjust(16) for c in cols))
if '--skipped' in sys.argv:
    for t in T:
        if t['code'] in skip and t['code'] not in done: print(' -', t['make'], t['gen'], f"({t['from']}-{t['to']})")
