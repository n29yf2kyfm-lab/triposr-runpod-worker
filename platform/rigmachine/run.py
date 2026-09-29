#!/usr/bin/env python3
"""The on-demand machine: send a car GLB, get it back opening.

    python3 platform/rigmachine/run.py CAR.glb|https://…/car.glb OUT_DIR [--size=1280x800] [--samples=24]

1. fetches the GLB when given a URL
2. rigs it and renders every state in Blender (rig_render.py)
3. lays the stills out on one sheet, captioned, and writes a viewer page

OUT_DIR ends up holding:
  <car>.glb, <car>.report.json   the rigged car and the rigger's report
  <car>_<state>_<view>.png       the stills
  sheet.jpg                      every still on one image, captioned
  result.json                    status, parts that open, timings
  viewer.html                    drag to spin, tap buttons to open parts
                                 (serve OUT_DIR over http; it loads <car>.glb)

Exit code 0 when the car was rigged, 2 when the rigger refused it (the reason
is in result.json), 1 on an error.
"""
import json, os, shutil, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    args = sys.argv[1:]
    pos = [a for a in args if not a.startswith('--')]
    flags = [a for a in args if a.startswith('--')]
    if len(pos) != 2:
        print(__doc__)
        return 1
    src, out = pos
    os.makedirs(out, exist_ok=True)
    if src.startswith(('http://', 'https://')):
        name = os.path.basename(src.split('?')[0]) or 'car.glb'
        os.makedirs(os.path.join(out, '_src'), exist_ok=True)
        local = os.path.join(out, '_src', name)       # a folder, so the car keeps its own name
        req = urllib.request.Request(src, headers={'User-Agent': 'rigmachine/1.0'})
        with urllib.request.urlopen(req, timeout=300) as r, open(local, 'wb') as f:
            shutil.copyfileobj(r, f)
        src = local
    blender = os.environ.get('BLENDER_BIN', 'blender')
    cmd = [blender, '-b', '--factory-startup', '--python', os.path.join(HERE, 'rig_render.py'), '--', src, out] + flags
    log = open(os.path.join(out, 'blender.log'), 'w')
    rc = subprocess.call(cmd, stdout=log, stderr=subprocess.STDOUT)
    if os.path.dirname(src) == os.path.join(out, '_src'):
        shutil.rmtree(os.path.dirname(src))   # the source is the caller's; keep only what we made
    rp = os.path.join(out, 'result.json')
    if not os.path.exists(rp):                 # Blender died before writing a verdict
        print(f'RIGMACHINE error: Blender exited {rc} without a result; see {out}/blender.log')
        return 1
    res = json.load(open(rp))
    if res['status'] in ('ok', 'partial'):
        web(out, res)
        sheet(out, res)
        viewer(out, res)
    print(json.dumps({k: res.get(k) for k in ('car', 'status', 'opens', 'missing', 'refused', 'error')}))
    return {'ok': 0, 'partial': 0, 'refused': 2}.get(res['status'], 1)


LABEL = {'shut': 'Shut', 'doors': 'Doors open', 'ends': 'Bonnet and tailgate up', 'open': 'Everything open'}
VIEW = {'fl': 'front left', 'rr': 'rear right'}


def label(state, opens):
    if state != 'ends':
        return LABEL.get(state, state)
    return {('bonnet',): 'Bonnet up', ('tailgate',): 'Tailgate up'}.get(tuple(opens), LABEL['ends'])


def sheet(out, res):
    from PIL import Image, ImageDraw, ImageFont
    states = []
    for s in res['stills']:
        if s['state'] not in states:
            states.append(s['state'])
    views = list(dict.fromkeys(s['view'] for s in res['stills']))
    first = Image.open(os.path.join(out, res['stills'][0]['file']))
    w, h = first.size
    tw, th = w // 2, h // 2
    cap = 30
    im = Image.new('RGB', (tw * len(views), (th + cap) * len(states)), (24, 25, 27))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
    except OSError:
        font = ImageFont.load_default()
    by = {(s['state'], s['view']): s for s in res['stills']}
    for i, st in enumerate(states):
        for j, v in enumerate(views):
            s = by.get((st, v))
            if not s:
                continue
            t = Image.open(os.path.join(out, s['file'])).convert('RGB').resize((tw, th), Image.LANCZOS)
            im.paste(t, (j * tw, i * (th + cap) + cap))
            d.text((j * tw + 10, i * (th + cap) + 6), f"{label(st, s['opens'])} · {VIEW.get(v, v)}",
                   fill=(235, 235, 235), font=font)
    im.save(os.path.join(out, 'sheet.jpg'), quality=88)


def web(out, res):
    """A meshopt-compressed copy for the browser. Node names (SB_<part>__<n>)
    survive; nothing is joined. Skipped, with the reason, if gltf-transform is
    missing — the viewer then loads the full file."""
    src = os.path.join(out, res['car'] + '.glb')
    dst = os.path.join(out, res['car'] + '.web.glb')
    tool = shutil.which('gltf-transform')
    if not tool:
        res['web_glb'] = None
        res['web_glb_why'] = 'gltf-transform not installed'
        return
    rc = subprocess.call([tool, 'meshopt', src, dst], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    if rc or not os.path.exists(dst):
        res['web_glb'] = None
        res['web_glb_why'] = f'gltf-transform exited {rc}'
        return
    res['web_glb'] = os.path.basename(dst)
    res['web_glb_mb'] = round(os.path.getsize(dst) / 1e6, 2)
    res['glb_mb'] = round(os.path.getsize(src) / 1e6, 2)
    json.dump(res, open(os.path.join(out, 'result.json'), 'w'), indent=1)


def viewer(out, res):
    page = open(os.path.join(HERE, 'viewer.html')).read()
    page = page.replace('__GLB__', res.get('web_glb') or res['car'] + '.glb').replace('__CAR__', res['car'])
    open(os.path.join(out, 'viewer.html'), 'w').write(page)


if __name__ == '__main__':
    sys.exit(main())
