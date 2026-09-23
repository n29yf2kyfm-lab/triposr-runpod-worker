"""Process a whole folder of car GLBs. Resumable, and it never stops on one car.

For every `*.glb` / `*.gltf` in the input folder it writes, into the output
folder:
  <name>.glb          the rigged car (only when it succeeds)
  <name>.report.json  every decision, or the reason it was refused
  <name>.blend        optional: the car with its open/close sliders
and, at the end, `summary.csv` + `summary.json` over every car in the folder.

OVERRIDES: `overrides.json` beside this file, then one in the INPUT folder
(which wins), give per-car rulings geometry cannot make — e.g. the VW Sharan's
sliding doors. Keys are file names without the extension.

A car that already has a report is SKIPPED on the next run, so a batch of a
thousand that is interrupted picks up where it stopped. Delete a report (or
pass redo=True) to process that car again.

Memory: each car's objects are removed after it is written and orphaned
meshes, materials and images are purged, so the thousandth car costs what the
first did.
"""
import bpy, os, json, time, csv, traceback
from . import core, rig

COLS = ['file', 'status', 'reason', 'doors', 'bonnet', 'tailgate', 'wheels',
        'special_doors', 'drive', 'paint', 'tyre_faces_to_rubber', 'seconds']


def _row(name, rep, status, secs):
    p = rep.get('parts', {})
    return {
        'file': name, 'status': status,
        'reason': rep.get('refused') or rep.get('error') or '',
        'doors': sum(1 for k in p if k.startswith('door_')),
        'bonnet': 'yes' if 'panel_bonnet' in p else 'no',
        'tailgate': 'yes' if 'tailgate' in p else 'no',
        'wheels': sum(1 for k in p if k.startswith('wheel_')),
        'special_doors': ' '.join(f"{k}:{v['type']}" for k, v in sorted(rep.get('motion', {}).items())),
        'drive': rep.get('frame', {}).get('drive', ''),
        'paint': (rep.get('paint') or {}).get('material', ''),
        'tyre_faces_to_rubber': rep.get('tyre_faces_to_rubber', ''),
        'seconds': round(secs, 1),
    }


def _status(rep):
    if 'refused' in rep:
        return 'refused'
    if 'error' in rep:
        return 'error'
    return 'partial' if rep.get('missing') else 'ok'


def run(in_dir, out_dir, save_blend=False, redo=False, limit=0, log=print, progress=None):
    os.makedirs(out_dir, exist_ok=True)
    ov = core.load_overrides(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'overrides.json'),
                             os.path.join(in_dir, 'overrides.json'))
    files = sorted(f for f in os.listdir(in_dir) if f.lower().endswith(('.glb', '.gltf')))
    if limit:
        files = files[:limit]
    rows = []
    for i, f in enumerate(files):
        stem = os.path.splitext(f)[0]
        rp = os.path.join(out_dir, stem + '.report.json')
        if progress:
            progress(i, len(files))
        if os.path.exists(rp) and not redo:
            rep = json.load(open(rp))
            rows.append(_row(f, rep, _status(rep), 0))
            log(f'[{i + 1}/{len(files)}] SKIP {f} (already has a report)')
            continue
        t0 = time.time()
        before = set(bpy.data.objects)
        rep = {'src': f, 'rigger': core.VERSION}
        try:
            rep, parts = core.process_file(os.path.join(in_dir, f), os.path.join(out_dir, stem + '.glb'), rp,
                                           ov.get(stem))
            if save_blend:
                rig.add_controls(parts, rep['hinge'], rep.get('motion'), stem, rep)
                bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, stem + '.blend'), copy=True)
            status = _status(rep)
        except core.Refused:
            rep = json.load(open(rp))
            status = 'refused'
        except Exception as e:                       # one broken file never stops the batch
            rep['error'] = f'{type(e).__name__}: {e}'
            rep['trace'] = traceback.format_exc()[-1500:]
            json.dump(rep, open(rp, 'w'), indent=1)
            status = 'error'
        # clear this car out before the next one
        mode_obj = bpy.context.view_layer.objects.active
        if mode_obj is not None and mode_obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        core._remove([o for o in bpy.data.objects if o not in before])
        core.purge_orphans()
        row = _row(f, rep, status, time.time() - t0)
        rows.append(row)
        log(f"[{i + 1}/{len(files)}] {status.upper():8s} {f}  {row['reason'][:90]}")
    with open(os.path.join(out_dir, 'summary.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    counts = {}
    for r in rows:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    json.dump({'rigger': core.VERSION, 'counts': counts, 'cars': rows},
              open(os.path.join(out_dir, 'summary.json'), 'w'), indent=1)
    log(f'DONE {len(rows)} files: ' + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())))
    return counts
