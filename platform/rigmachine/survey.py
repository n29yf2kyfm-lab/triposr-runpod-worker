#!/usr/bin/env python3
"""Measure which catalogue cars can open: rig every approved car, record why
not when it cannot. Read-only against the catalogue; nothing is published.

    python3 platform/rigmachine/survey.py OUT_DIR [--workers=3] [--limit=N] [--ids=FILE]

For each approved v2 catalogue entry: download its GLB into a private temp
folder, run the Strip Bay Rigger on it headless, append one line to
OUT_DIR/survey.jsonl, delete the GLB. Resumable: an assetId already in the
file is skipped, so an interrupted run carries on. Writes OUT_DIR/summary.json
(counts by status and by refusal reason) at the end.
"""
import collections, concurrent.futures as cf, json, os, shutil, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run import fetch                          # noqa: E402  (length-checked download)

CAT = 'https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/car-renders/resolver/catalogue.v2.json'
CLI = os.path.join(HERE, '..', 'trainer', 'blender_addon', 'strip_bay_rigger', 'cli.py')
lock = threading.Lock()


def one(e, out):
    aid = e['assetId']
    d = tempfile.mkdtemp(prefix='survey_')
    row = {'assetId': aid, 'make': e.get('make'), 'model': e.get('model')}
    t0 = time.time()
    try:
        src = os.path.join(d, 'in')
        os.makedirs(src)
        fetch(e['desktopGlbUrl'], os.path.join(src, aid + '.glb'))
        subprocess.run([os.environ.get('BLENDER_BIN', 'blender'), '-b', '--factory-startup', '--python', CLI,
                        '--', src, os.path.join(d, 'out')], capture_output=True, timeout=900)
        rp = os.path.join(d, 'out', aid + '.report.json')
        rep = json.load(open(rp)) if os.path.exists(rp) else {'error': 'no report (Blender crashed or timed out)'}
        p = rep.get('parts', {})
        row.update(status='refused' if 'refused' in rep else 'error' if 'error' in rep else
                   'partial' if rep.get('missing') else 'ok',
                   reason=rep.get('refused') or rep.get('error') or '',
                   doors=sum(1 for k in p if k.startswith('door_')), bonnet='panel_bonnet' in p,
                   tailgate='tailgate' in p, split=bool(rep.get('split_pairs')),
                   missing=rep.get('missing') or [], implausible=rep.get('implausible') or [],
                   cut=(rep.get('door_cutter') or {}).get('result', ''),
                   cut_refused=(rep.get('door_cutter') or {}).get('refused_doors') or {})
    except Exception as ex:
        row.update(status='error', reason=f'{type(ex).__name__}: {ex}'[:200])
    finally:
        shutil.rmtree(d, ignore_errors=True)       # no GLB stays on the box
    row['seconds'] = round(time.time() - t0, 1)
    with lock:
        with open(os.path.join(out, 'survey.jsonl'), 'a') as f:
            f.write(json.dumps(row) + '\n')
    return row


def reason_class(r):
    r = r.lower()
    for k in ('no wheels named', 'wheels do not fill', 'door part', 'nose', 'upside down', 'deforming rig',
              'no geometry', 'cannot size', 'disagree', 'download', 'crashed'):
        if k in r:
            return k
    return r[:40] or '(none)'


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith('--')]
    opt = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    if len(pos) != 1:
        print(__doc__)
        return 1
    out = pos[0]
    os.makedirs(out, exist_ok=True)
    jl = os.path.join(out, 'survey.jsonl')
    done = {json.loads(l)['assetId'] for l in open(jl)} if os.path.exists(jl) else set()
    cat = json.loads(subprocess.run(['curl', '-sS', CAT], capture_output=True, text=True, check=True).stdout)
    todo = [e for e in cat if e.get('publicationStatus') == 'approved' and e.get('desktopGlbUrl')
            and e['assetId'] not in done]
    if opt.get('ids'):                             # a file of assetIds, one per line
        want = {l.strip() for l in open(opt['ids']) if l.strip()}
        todo = [e for e in todo if e['assetId'] in want]
    if opt.get('limit'):
        todo = todo[:int(opt['limit'])]
    print(f'SURVEY {len(done)} already done, {len(todo)} to go', flush=True)
    with cf.ThreadPoolExecutor(int(opt.get('workers', 3))) as ex:
        for i, r in enumerate(ex.map(lambda e: one(e, out), todo), 1):
            print(f'SURVEY [{i}/{len(todo)}] {r["status"]:8s} {r["assetId"]} {r.get("reason", "")[:70]}', flush=True)
    rows = [json.loads(l) for l in open(jl)]
    st = collections.Counter(r['status'] for r in rows)
    why = collections.Counter(reason_class(r['reason']) for r in rows if r['status'] in ('refused', 'error'))
    json.dump({'cars': len(rows), 'status': st, 'refusal_reasons': why.most_common(),
               'opens_something': sum(1 for r in rows if r['status'] in ('ok', 'partial'))},
              open(os.path.join(out, 'summary.json'), 'w'), indent=1)
    print('SURVEY_DONE', dict(st), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
