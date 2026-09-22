#!/usr/bin/env python3
"""Write the app's FLEET_GEN block from sb_convert.py reports.

    python3 fleet_gen.py golf-bay.html rep_dir accepted.txt

accepted.txt lists `<assetId> <display name>` — only cars that passed the
render check go in. Names are MAKE AND MODEL ONLY, plus a generation code
where the catalogue id itself carries one; nothing is invented (CLAUDE.md,
accuracy rule). Everything else in an entry comes from the car's own report,
so the manual text can never claim a bonnet, an engine or a drive side the
file does not have.
"""
import json, sys, re

html, repdir, acc = sys.argv[1:4]
entries = []
for line in open(acc):
    line = line.strip()
    if not line or line.startswith('#'): continue
    nopaint = line.endswith('|nopaint')
    line = line.replace('|nopaint', '').strip()
    aid, name = line.split(' ', 1)
    r = json.load(open(f'{repdir}/{aid}.json'))
    key = re.sub(r'[^a-z0-9]', '', aid.replace('-v1', '').replace('-v2', ''))[:24]
    p = r['parts']
    man = [f"<b>Converted from a game-style model.</b> The parts are the file's own pieces, renamed and "
           f"turned to face the same way as every other car here. Doors and wheels were given their "
           f"corners by where they sit, not by what the file called them."]
    missing = r.get('missing', [])
    if missing:
        nice = {'panel_bonnet': 'bonnet', 'tailgate': 'boot lid or tailgate'}
        man.append('<b>Does not open here:</b> ' + ' and '.join(nice[m] for m in missing)
                   + ' — the file has it welded into the body, and the converter refuses to guess a cut line.')
    if r.get('lifted'):
        man.append('<b>Lifted out of the paint:</b> ' + ', '.join(
            {'panel_bonnet': 'the bonnet', 'tailgate': 'the boot lid'}[k] + f' ({v:,} faces)'
            for k, v in r['lifted'].items()) + ' sat as loose pieces inside the body mesh and were taken out whole.')
    man.append('<b>There is modelled engine geometry under the bonnet.</b>' if 'engine' in p
               else '<b>No engine in this file.</b> Open the bonnet and the bay is empty.')
    d = r['frame'].get('drive')
    if d: man.append(f"<b>{'Left' if d == 'LHD' else 'Right'}-hand drive</b>, measured from where the steering wheel sits.")
    man.append('The engine, starter, brake and door-internals bays are built around the Golf and do not run on this car.')
    entries.append((key, {
        'name': name, 'short': name.split(' ')[-1], 'url': f'{aid}.glb.wasm', 'conv': 4,
        'hinge': r['hinge'], **({'paint': False} if nopaint else {}),
        'note': f"Real geometry from {aid} · converted by sb_convert.py · hinges DERIVED from the file",
        'manual': man}))

block = 'const FLEET_GEN = {\n' + ',\n'.join(
    f'  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}' for k, v in entries) + '\n};\n'
s = open(html).read()
a = s.index('/* FLEET_GEN:END */')
b = s.index('const FLEET_GEN = ')
s = s[:b] + block + s[a:]
open(html, 'w').write(s)
print(f'{len(entries)} cars written into FLEET_GEN')
