"""Fetch 7zap modifications straight through String's REST API (no MCP size limit).
Key is read from the STRING_API_KEY environment variable (set in the cloud environment's settings)
or /root/.alam3d_env, never from tracked files.
    python3 direct.py skipped | todo [N] [--workers 6]"""
import json, os, sys, time, concurrent.futures as cf, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mods
ENV = '/root/.alam3d_env'
KEY = os.environ.get('STRING_API_KEY') or (next((l.split('=', 1)[1].strip().strip('"\'') for l in open(ENV) if l.startswith('STRING_API_KEY=')), None) if os.path.exists(ENV) else None)

def fetch(t):
    body = json.dumps({'url': t['url'], 'format': 'raw', 'solveCaptcha': False,
                       'headers': {'Accept': 'application/json'}}).encode()
    req = urllib.request.Request('https://request.usestring.ai/v1/fetch', data=body, method='POST',
        headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                raw = r.read().decode('utf-8', 'replace')
            ds = mods._mods_from_str(raw)
            if not ds: return t['code'], 'no payload: ' + raw[:120]
            for d in ds:
                c = mods.compact(d)
                json.dump(c, open(os.path.join(mods.OUT, c['code'] + '.json'), 'w'), ensure_ascii=False)
            return t['code'], 'ok %d variants' % len(ds[0]['modifications'])
        except Exception as e:
            err = str(e)[:120]; time.sleep(3 * (attempt + 1))
    return t['code'], 'error ' + err

if __name__ == '__main__':
    if not KEY: sys.exit('no STRING_API_KEY in the environment or ' + ENV)
    dn = mods.done()
    skip = {w for w in open(os.path.join(mods.HERE, 'skip.txt')).read().split() if w.startswith('gen_')}
    if sys.argv[1] == 'skipped': todo = [t for t in mods.T if t['code'] in skip and t['code'] not in dn]
    else: todo = [t for t in mods.T if t['code'] not in dn][:int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else None]
    w = int(sys.argv[sys.argv.index('--workers') + 1]) if '--workers' in sys.argv else 6
    print('fetching', len(todo), 'with', w, 'workers', flush=True)
    with cf.ThreadPoolExecutor(w) as ex:
        for code, res in ex.map(fetch, todo): print(code, res, flush=True)
