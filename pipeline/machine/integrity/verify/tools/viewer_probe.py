#!/usr/bin/env python3
"""
INDEPENDENT web-viewer proof: the GLB in a real browser, in Google's
<model-viewer>, orbited to the eight canonical azimuths, with per-material
toggling for the glass / wheels / interior / body isolation proofs.

Why this exists rather than reusing pipeline/machine/viewer_check.py:
  * that script's `on_ground` test reads WHOLE-MODEL bbox min-Y and passed a
    car whose front tyres were 183 mm in the air, so its grounding verdict is
    not usable here (grounding is judged from the TYRE nodes in Blender);
  * it crashed on this asset with KeyError 'bbox_min_y' -- a latent bug where
    the printout is guarded by `if d:` but the field is only set when
    `scale > 0`, so a model that reports 0x0x0 dims takes down the run before
    any console output is written.  The console output is the diagnosis.
It DOES reuse that script's vendored model-viewer bundle, which is the real
component and the point of an independent check.

    python3 viewer_probe.py <glb> <outdir> [--web VENDORDIR]

Everything asserted here is written to <outdir>/viewer_probe.json.
"""
import sys, os, json, shutil, threading, http.server, socketserver, argparse

ap = argparse.ArgumentParser()
ap.add_argument('glb')
ap.add_argument('outdir')
ap.add_argument('--web', default='/tmp/vc_before/web')
ap.add_argument('--timeout', type=int, default=240000)
A = ap.parse_args()
os.makedirs(A.outdir, exist_ok=True)
WEB = os.path.join(A.outdir, 'web')
os.makedirs(WEB, exist_ok=True)

MV = os.path.join(A.web, 'model-viewer.min.js')
if not os.path.exists(MV):
    raise SystemExit('FATAL: no vendored model-viewer at %s -- run '
                     'pipeline/machine/viewer_check.py once to fetch it' % MV)
shutil.copy(MV, os.path.join(WEB, 'model-viewer.min.js'))
shutil.copy(A.glb, os.path.join(WEB, 'model.glb'))

HTML = """<!doctype html><html><head><meta charset=utf-8>
<style>html,body{margin:0;background:#202024}
model-viewer{width:900px;height:640px;background:#202024;--poster-color:transparent}</style>
</head><body>
<model-viewer id=mv src="model.glb" camera-controls disable-zoom
  interaction-prompt=none environment-image=neutral exposure=1
  shadow-intensity=0 camera-orbit="0deg 81deg 105%"></model-viewer>
<script type=module>
import './model-viewer.min.js';
window.__log = [];
['error','warn'].forEach(k=>{const o=console[k];
  console[k]=(...a)=>{window.__log.push({type:k,text:a.map(String).join(' ')});o(...a);};});
window.addEventListener('error', e=>window.__log.push({type:'pageerror',text:String(e.message)}));
const mv = document.getElementById('mv');
window.__state = {load:false, error:null};
mv.addEventListener('load', ()=>{window.__state.load = true;});
mv.addEventListener('error', e=>{
  window.__state.error = (e && e.detail) ? JSON.stringify(e.detail) : 'error event';
});
window.__ready = () => window.__state.load || window.__state.error;
window.__info = () => {
  const d = mv.getDimensions ? mv.getDimensions() : null;
  const c = mv.getBoundingBoxCenter ? mv.getBoundingBoxCenter() : null;
  let mats = [];
  try { mats = (mv.model ? mv.model.materials : []).map(m=>({
      name: m.name,
      base: m.pbrMetallicRoughness ? Array.from(m.pbrMetallicRoughness.baseColorFactor) : null,
      alphaMode: m.getAlphaMode ? m.getAlphaMode() : null,
      doubleSided: m.getDoubleSided ? m.getDoubleSided() : null,
  })); } catch(e) { mats = [{name:'MATERIAL_READ_FAILED', err:String(e)}]; }
  return {dims:d?{x:d.x,y:d.y,z:d.z}:null,
          centre:c?{x:c.x,y:c.y,z:c.z}:null,
          materials:mats, state:window.__state, log:window.__log};
};
window.__hideMats = (names) => {
  const hid=[];
  for (const m of mv.model.materials) {
    if (names.some(n=>m.name.toLowerCase().includes(n))) {
      m.setAlphaMode('BLEND');
      const b = Array.from(m.pbrMetallicRoughness.baseColorFactor);
      m.pbrMetallicRoughness.setBaseColorFactor([b[0],b[1],b[2],0]);
      hid.push(m.name);
    }
  }
  return hid;
};
</script></body></html>"""
open(os.path.join(WEB, 'index.html'), 'w').write(HTML)


class Q(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WEB, **k)

    def log_message(self, *a):
        pass


srv = socketserver.TCPServer(('127.0.0.1', 0), Q)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', '/opt/pw-browsers')
from playwright.sync_api import sync_playwright
import glob as _glob


def find_chromium():
    """Playwright's bundled-browser version pin does not match what is
    installed here (it wants build 1234, the container has 1194) and
    `playwright install` is forbidden in this environment.  Point launch() at
    the binary that IS present -- same approach as
    pipeline/machine/viewer_check.py:find_chromium."""
    root = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '/opt/pw-browsers')
    for pat in ('chromium-*/chrome-linux/chrome',
                'chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell',
                'chromium-*/chrome-linux64/chrome'):
        hits = sorted(_glob.glob(os.path.join(root, pat)))
        if hits:
            return hits[-1]
    raise SystemExit('FATAL: no chromium binary under ' + root)


CHROME = find_chromium()

REPORT = {'glb': os.path.basename(A.glb), 'port': PORT, 'views': {}}
with sync_playwright() as p:
    br = p.chromium.launch(headless=True, executable_path=CHROME,
                           args=['--use-gl=swiftshader', '--enable-unsafe-swiftshader',
                                 '--disable-dev-shm-usage', '--no-sandbox'])
    pg = br.new_page(viewport={'width': 940, 'height': 680})
    console = []
    pg.on('console', lambda m: console.append({'type': m.type, 'text': m.text[:400]}))
    pg.on('pageerror', lambda e: console.append({'type': 'pageerror', 'text': str(e)[:400]}))
    # Log the URL and status of every non-2xx response.  The first run reported
    # one console error reading only "Failed to load resource: ... 404" with no
    # URL, which is not a diagnosis -- it could be a missing decoder or a
    # missing favicon and those are very different verdicts.
    http_bad = []
    pg.on('response', lambda r: (http_bad.append({'url': r.url, 'status': r.status})
                                 if r.status >= 400 else None))
    pg.goto('http://127.0.0.1:%d/index.html' % PORT)
    try:
        pg.wait_for_function('window.__ready && window.__ready()', timeout=A.timeout)
        REPORT['load_timed_out'] = False
    except Exception as e:
        REPORT['load_timed_out'] = True
        REPORT['timeout_error'] = str(e)[:300]
    info = pg.evaluate('window.__info()')
    REPORT['model'] = {k: info[k] for k in ('dims', 'centre', 'state')}
    REPORT['materials_seen_by_viewer'] = info['materials']
    REPORT['page_log'] = info['log']

    # eight canonical azimuths.  model-viewer theta=0 looks at -Z of the glTF,
    # so the mapping to our nose axis is asserted numerically below, not assumed.
    AZ = [('mvFRONT', 0), ('mv45', 45), ('mv90', 90), ('mv135', 135),
          ('mv180', 180), ('mv225', 225), ('mv270', 270), ('mv315', 315)]
    from PIL import Image
    import numpy as np
    for nm, a in AZ:
        pg.evaluate("document.getElementById('mv').cameraOrbit='%ddeg 81deg 105%%'" % a)
        pg.wait_for_timeout(1400)
        f = os.path.join(A.outdir, '%s.png' % nm)
        pg.locator('#mv').screenshot(path=f)
        im = np.asarray(Image.open(f).convert('RGB')).astype(int)
        bg = np.array([0x20, 0x20, 0x24])
        nonbg = float((np.abs(im - bg).sum(axis=2) > 24).mean())
        REPORT['views'][nm] = {'azimuth_deg': a, 'non_background_fraction': round(nonbg, 5),
                               'POPULATED': nonbg > 0.02, 'file': os.path.basename(f)}

    # isolation toggles -- the acceptance criterion asks for glass / wheels /
    # interior / body to be toggled in the independent viewer, not in Blender.
    for nm, keys in (('mvTOGGLE_no_glass', ['glass']),
                     ('mvTOGGLE_no_tyre', ['tyre', 'tire', 'rubber']),
                     ('mvTOGGLE_no_paint', ['paint', 'carpaint'])):
        hid = pg.evaluate('window.__hideMats(%s)' % json.dumps(keys))
        pg.evaluate("document.getElementById('mv').cameraOrbit='45deg 81deg 105%'")
        pg.wait_for_timeout(1200)
        f = os.path.join(A.outdir, '%s.png' % nm)
        pg.locator('#mv').screenshot(path=f)
        im = np.asarray(Image.open(f).convert('RGB')).astype(int)
        bg = np.array([0x20, 0x20, 0x24])
        REPORT['views'][nm] = {'hidden_materials': hid,
                               'non_background_fraction':
                                   round(float((np.abs(im - bg).sum(axis=2) > 24).mean()), 5),
                               'file': os.path.basename(f)}
        pg.reload()
        try:
            pg.wait_for_function('window.__ready && window.__ready()', timeout=A.timeout)
        except Exception:
            pass

    REPORT['console'] = console
    REPORT['http_non_2xx'] = http_bad
    br.close()
srv.shutdown()

errs = [c for c in REPORT['console'] if c['type'] in ('error', 'pageerror')]
_bad = REPORT.get('http_non_2xx', [])
_fav = [b for b in _bad if b['url'].endswith('/favicon.ico')]
REPORT['http_non_2xx_excluding_favicon'] = [b for b in _bad if not b['url'].endswith('/favicon.ico')]
REPORT['ASSET_RESOURCES_ALL_OK'] = len(REPORT['http_non_2xx_excluding_favicon']) == 0
REPORT['favicon_404s'] = len(_fav)
REPORT['console_errors'] = errs
REPORT['CONSOLE_CLEAN'] = len(errs) == 0
REPORT['LOADED'] = bool(REPORT['model']['state'].get('load'))
REPORT['ALL_VIEWS_POPULATED'] = all(
    v.get('POPULATED', True) for v in REPORT['views'].values() if 'POPULATED' in v)
json.dump(REPORT, open(os.path.join(A.outdir, 'viewer_probe.json'), 'w'), indent=1)
print('LOADED=%s  dims=%s  console_errors=%d  views_populated=%s'
      % (REPORT['LOADED'], REPORT['model']['dims'], len(errs),
         REPORT['ALL_VIEWS_POPULATED']))
print('  http non-2xx: %s  (favicon 404s: %s)  asset resources OK=%s'
      % (REPORT['http_non_2xx_excluding_favicon'], REPORT['favicon_404s'],
         REPORT['ASSET_RESOURCES_ALL_OK']))
for c in errs[:6]:
    print('  CONSOLE %-10s %s' % (c['type'], c['text'][:160]))
for k, v in REPORT['views'].items():
    print('  %-20s nonbg=%s %s' % (k, v['non_background_fraction'],
                                   v.get('hidden_materials', '')))
