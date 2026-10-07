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

def ingest():
    n = 0
    for f in glob.glob(os.path.join(TR, 'mcp-string-web_access_fetch-*.txt')):
        try:
            j = json.load(open(f)); d = json.loads(j['body'])
        except Exception:
            continue
        if not isinstance(d, dict) or 'modifications' not in d or not d.get('generation'):
            continue
        c = compact(d)
        json.dump(c, open(os.path.join(OUT, c['code'] + '.json'), 'w'), ensure_ascii=False)
        os.remove(f); n += 1
    # small replies arrive inline: read them from the session transcript
    TX = '/root/.claude/projects/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506.jsonl'
    dn = done()
    for line in open(TX):
        if 'modifications' not in line or 'statusCode' not in line: continue
        try: rec = json.loads(line)
        except Exception: continue
        content = (rec.get('message') or {}).get('content')
        if not isinstance(content, list): continue
        for c in content:
            if not isinstance(c, dict) or c.get('type') != 'tool_result': continue
            parts = c.get('content')
            texts = [p.get('text', '') for p in parts if isinstance(p, dict)] if isinstance(parts, list) else [parts or '']
            for t in texts:
                try: d = json.loads(json.loads(t)['body'])
                except Exception: continue
                if not isinstance(d, dict) or 'modifications' not in d or not d.get('generation'): continue
                if d['generation']['code'] in dn: continue
                cc = compact(d)
                json.dump(cc, open(os.path.join(OUT, cc['code'] + '.json'), 'w'), ensure_ascii=False)
                dn.add(cc['code']); n += 1
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
