"""On-demand entry point: a RunPod serverless job that rigs and renders one car.

Job input, either a decoded vehicle (the showcase: doors open, glass cleared,
engine in the bay) or a GLB link:
    {"vehicle": {"make": "Audi", "model": "RS6", "year": 2021, "fuel": "PETROL", "cc": 3996, "colour": "GREY"}}
    {"glb_url": "https://…/car.glb", "showcase": true, "engine": "v8", "mount": "long"}
plus optional "size": "1280x800", "samples": 24. A registration is never an
input; one sent by mistake is dropped before anything runs.

It runs run.py (rig in Blender, render every state, build the sheet and the
viewer page), then uploads everything to the public bucket under
    car-meshes/rigmachine/<car>/<run id>/
and returns result.json plus the public URL of every file. Without SB_KEY it
still runs and returns the result, and says the files were not uploaded.

The worker image needs Blender 4.5 on PATH (or BLENDER_BIN) and Pillow — the
render worker image already has both. Deploying it as its own endpoint is the
owner's call: it costs GPU/CPU time per car and must not be hot-pinned onto
the shared render worker mid-wave (see CLAUDE.md, warm workers).
"""
import json, os, shutil, subprocess, sys, tempfile, time, urllib.request, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SB_URL = os.environ.get('SB_URL', 'https://tfkvthprsntexrcuqpyd.supabase.co')
BUCKET = 'car-meshes'
TYPES = {'.glb': 'model/gltf-binary', '.json': 'application/json', '.png': 'image/png',
         '.jpg': 'image/jpeg', '.html': 'text/html'}


def upload(path, key, sb_key):
    """PUT one file; Supabase storage wants BOTH headers or it 403s."""
    req = urllib.request.Request(f'{SB_URL}/storage/v1/object/{BUCKET}/{key}', data=open(path, 'rb').read(),
                                 method='POST', headers={
                                     'apikey': sb_key, 'Authorization': f'Bearer {sb_key}', 'x-upsert': 'true',
                                     'Content-Type': TYPES.get(os.path.splitext(path)[1], 'application/octet-stream')})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.status


def handler(job):
    inp = job.get('input') or {}
    url, vehicle = inp.get('glb_url'), inp.get('vehicle')
    size = [f"--size={inp.get('size', '1280x800')}", f"--samples={int(inp.get('samples', 24))}"]
    out = tempfile.mkdtemp(prefix='rig_')
    t0 = time.time()
    if vehicle:
        # the app's decode (make, model, year, fuel, cc, colour) — never the reg
        vehicle = {k: v for k, v in vehicle.items() if k.lower() not in ('reg', 'registration', 'vrm')}
        cmd = [sys.executable, os.path.join(HERE, 'car.py'), out, '--vehicle=' + json.dumps(vehicle)] + size
    elif url and url.startswith(('http://', 'https://')):
        cmd = [sys.executable, os.path.join(HERE, 'run.py'), url, out] + size
        if inp.get('showcase'):
            cmd += ['--showcase', f"--engine={inp.get('engine', 'i4')}", f"--mount={inp.get('mount', 'trans')}"]
    else:
        shutil.rmtree(out, ignore_errors=True)
        return {'error': 'give vehicle {make, model, year, ...} or glb_url (a public http(s) link to a .glb)'}
    rc = subprocess.call(cmd)
    rp = os.path.join(out, 'result.json')
    if not os.path.exists(rp):
        shutil.rmtree(out, ignore_errors=True)
        return {'error': f'the machine exited {rc} without a result'}
    res = json.load(open(rp))
    res['seconds'] = round(time.time() - t0, 1)
    res.setdefault('car', (res.get('resolver') or {}).get('resolution', {}).get('assetId') or 'no-match')
    sb_key = os.environ.get('SB_KEY')
    if not sb_key:
        res['uploaded'] = False
        res['why_not_uploaded'] = 'SB_KEY is not set on this worker'
        shutil.rmtree(out, ignore_errors=True)   # nothing kept on the box it cannot upload
        return res
    run_id = time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    prefix = f"rigmachine/{res['car']}/{run_id}"
    files = {}
    for f in sorted(os.listdir(out)):
        if f == 'blender.log':
            continue
        upload(os.path.join(out, f), f'{prefix}/{f}', sb_key)
        files[f] = f'{SB_URL}/storage/v1/object/public/{BUCKET}/{prefix}/{f}'
    res.update(uploaded=True, files=files)
    shutil.rmtree(out, ignore_errors=True)       # uploaded, so the local copy goes
    return res


if __name__ == '__main__':
    import runpod                                  # only on the worker
    runpod.serverless.start({'handler': handler})
