"""Ingest saved String results of 7zap's modifications API; print next targets.
    python3 mods.py ingest | next N | status"""
import glob, json, os, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__))
TR = '/root/.claude/projects/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/tool-results'
OUT = os.path.join(HERE, 'mods'); os.makedirs(OUT, exist_ok=True)
T = json.load(open(os.path.join(HERE, 'targets.json')))

def compact(d):
    eng = collections.defaultdict(lambda: {'years': set(), 'bodies': set(), 'gearboxes': set(), 'trims': set()})
    other = collections.Counter()
    for m in d['modifications']:
        p = {x['name']: x['value'] for x in m['params']}
        e = eng[p.get('engine') or '?']
        if p.get('year'): e['years'].add(p['year'])
        if p.get('body'): e['bodies'].add(p['body'])
        if p.get('transmission'): e['gearboxes'].add(p['transmission'])
        if p.get('trim'): e['trims'].add(p['trim'])
        for k in p:
            if k not in ('engine', 'year', 'body', 'transmission', 'trim'): other[k] += 1
    return {'code': d['generation']['code'], 'generation': d['generation']['name'],
            'series': d['generation'].get('series'), 'region': d['generation']['region']['name'],
            'modifications': len(d['modifications']), 'otherParams': dict(other),
            'engines': [{'engine': k, 'years': sorted(v['years']), 'bodies': sorted(v['bodies']),
                         'gearboxes': sorted(v['gearboxes']), 'trims': sorted(v['trims'])} for k, v in sorted(eng.items())]}

PROJ = '/root/.claude/projects/-home-user-triposr-runpod-worker'

def _mods_from_str(s):
    """Find a 7zap modifications payload in any text: String raw/json envelope,
    markdown (JSON as-is or in a code block) or a Firecrawl result."""
    out = []
    try:
        j = json.loads(s)
    except Exception:
        j = None
    if j is not None:
        stack = [j]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                if 'modifications' in x and x.get('generation'): out.append(x); continue
                stack.extend(x.values())
            elif isinstance(x, list): stack.extend(x)
            elif isinstance(x, str) and '"modifications"' in x: out.extend(_mods_from_str(x))
        if out: return out
    i = s.find('{"loggedIn"')
    if i < 0: i = s.find('{"series"')
    if i >= 0:
        k = s.rfind('}')
        while k > i:
            try:
                d = json.loads(s[i:k + 1])
                if isinstance(d, dict) and 'modifications' in d: return [d]
                break
            except Exception:
                k = s.rfind('}', i, k)
    return out

def ingest():
    n = 0; dn = done()
    def keep(d):
        nonlocal n
        if not isinstance(d, dict) or not d.get('generation'): return
        code = d['generation']['code']
        if code in dn: return
        cc = compact(d)
        json.dump(cc, open(os.path.join(OUT, code + '.json'), 'w'), ensure_ascii=False)
        dn.add(code); n += 1
    # big replies are saved as files (main session and helper agents alike)
    for f in glob.glob(os.path.join(PROJ, '**', 'tool-results', '*.txt'), recursive=True):
        try: s = open(f).read()
        except Exception: continue
        if '"modifications' not in s and '\\"modifications' not in s: continue
        ds = _mods_from_str(s)
        for d in ds: keep(d)
        if ds: os.remove(f)
    # small replies arrive inline: read them from every transcript (incl. agents)
    for tx in glob.glob(os.path.join(PROJ, '**', '*.jsonl'), recursive=True):
        for line in open(tx, errors='ignore'):
            if 'modifications' not in line or 'tool_result' not in line: continue
            try: rec = json.loads(line)
            except Exception: continue
            content = (rec.get('message') or {}).get('content')
            if not isinstance(content, list): continue
            for c in content:
                if not isinstance(c, dict) or c.get('type') != 'tool_result': continue
                parts = c.get('content')
                texts = [p.get('text', '') for p in parts if isinstance(p, dict)] if isinstance(parts, list) else [parts or '']
                for t in texts:
                    if 'modifications' in t:
                        for d in _mods_from_str(t): keep(d)
    print('ingested', n)

def done():
    return {os.path.basename(f)[:-5] for f in glob.glob(os.path.join(OUT, '*.json'))}

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'ingest': ingest()
    if cmd in ('next', 'status'):
        dn = done(); sk = {w for w in open(os.path.join(HERE,'skip.txt')).read().split() if w.startswith('gen_')} if os.path.exists(os.path.join(HERE,'skip.txt')) else set()
        todo = [t for t in T if t['code'] not in dn and t['code'] not in sk]
        print('skipped (too large for the connector)', len(sk))
        print('done', len(T) - len(todo), 'todo', len(todo))
        if cmd == 'next':
            for t in todo[:int(sys.argv[2])]: print(t['make'], '|', t['gen'], '|', t['url'])
