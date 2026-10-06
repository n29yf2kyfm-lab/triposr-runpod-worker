#!/usr/bin/env python3
"""Render every openable catalogue car with all its doors, bonnet and tailgate
open, one front three-quarter still each, for a gallery.

    python3 platform/rigmachine/render_open.py OUT_DIR [--workers=3] [--limit=N]

Which cars: those survey.py found `ok` or `partial` (survey/survey.jsonl).
Body style: the catalogue's own, else the owner-approved proposal
(platform/catalogue/proposals/body_style_approved.csv), else blank.

Writes OUT_DIR/gallery.jsonl, one line per car: assetId, make, model, body,
opens, and a small JPEG as a data URI. Each car's GLB, rig and full-size
render are deleted as soon as its line is written. Resumable.
"""
import base64, concurrent.futures as cf, csv, io, json, os, shutil, subprocess, sys, tempfile, threading, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run import fetch                          # noqa: E402

CAT = 'https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/car-renders/resolver/catalogue.v2.json'
lock = threading.Lock()


def one(e, body, out, survey):
    aid = e['assetId']
    d = tempfile.mkdtemp(prefix='open_')
    row = {'assetId': aid, 'make': e.get('make'), 'model': e.get('model'), 'body': body or '',
           'survey': survey.get('status')}
    try:
        src = os.path.join(d, aid + '.glb')
        fetch(e['desktopGlbUrl'], src)
        subprocess.run([os.environ.get('BLENDER_BIN', 'blender'), '-b', '--factory-startup', '--python',
                        os.path.join(HERE, 'rig_render.py'), '--', src, os.path.join(d, 'out'),
                        '--only=open:fl', '--size=800x500', '--samples=14'], capture_output=True, timeout=1200,
                       env=dict(os.environ, SB_BODY=body or ''))
        rp = os.path.join(d, 'out', 'result.json')
        res = json.load(open(rp)) if os.path.exists(rp) else {'status': 'error', 'error': 'no result'}
        row['status'] = res.get('status')
        row['opens'] = res.get('opens') or []
        stills = res.get('stills') or []
        if stills:
            from PIL import Image
            im = Image.open(os.path.join(d, 'out', stills[0]['file'])).convert('RGB')
            im.thumbnail((560, 350))
            b = io.BytesIO()
            im.save(b, 'JPEG', quality=72, optimize=True)
            row['img'] = 'data:image/jpeg;base64,' + base64.b64encode(b.getvalue()).decode()
        else:
            row['why'] = res.get('refused') or res.get('error') or 'no still'
    except Exception as ex:
        row.update(status='error', why=f'{type(ex).__name__}: {ex}'[:200])
    finally:
        shutil.rmtree(d, ignore_errors=True)       # no GLB or render stays on the box
    with lock:
        with open(os.path.join(out, 'gallery.jsonl'), 'a') as f:
            f.write(json.dumps(row) + '\n')
    return row


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith('--')]
    opt = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    if len(pos) != 1:
        print(__doc__)
        return 1
    out = pos[0]
    os.makedirs(out, exist_ok=True)
    gl = os.path.join(out, 'gallery.jsonl')
    done = {json.loads(l)['assetId'] for l in open(gl)} if os.path.exists(gl) else set()
    survey = {json.loads(l)['assetId']: json.loads(l) for l in open(os.path.join(HERE, 'survey', 'survey.jsonl'))}
    prop = {r['assetId']: r['proposal'] for r in csv.DictReader(open(
        os.path.join(HERE, '..', 'catalogue', 'proposals', 'body_style_approved.csv')))}
    cat = json.loads(urllib.request.urlopen(CAT, timeout=60).read())
    todo = [e for e in cat if survey.get(e['assetId'], {}).get('status') in ('ok', 'partial')
            and e['assetId'] not in done]
    if opt.get('limit'):
        todo = todo[:int(opt['limit'])]
    print(f'OPEN {len(done)} done, {len(todo)} to go', flush=True)
    with cf.ThreadPoolExecutor(int(opt.get('workers', 3))) as ex:
        futs = [ex.submit(one, e, e.get('bodyStyle') or prop.get(e['assetId']), out, survey[e['assetId']]) for e in todo]
        for i, f in enumerate(cf.as_completed(futs), 1):
            r = f.result()
            print(f"OPEN [{i}/{len(todo)}] {r.get('status')!s:8s} {r['assetId']} {len(r.get('opens') or [])} parts", flush=True)
    print('OPEN_DONE', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
