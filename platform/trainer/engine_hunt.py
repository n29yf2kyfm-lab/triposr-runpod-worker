#!/usr/bin/env python3
"""Does any catalogue car actually ship an ENGINE? Measured, not quoted.

CLAUDE.md states that engine, starter, battery, suspension and exhaust are
absent from the car files entirely, which is why Strip Bay builds its
engine in code. That was measured across the 163 meshes of ONE car — the
reference Golf — and has since been repeated as a property of the library.
This checks it against the library.

THE FIRST ATTEMPT SAID 171 OF 766 AND WAS WRONG, in a way worth recording
because the failure is generic. A loose word sweep matched:

    CayenneTurboGT…    the MODEL NAME, not a turbocharger
    Cylinder.001       BLENDER'S DEFAULT PRIMITIVE, on a GT-R with no
                       engine at all — 406 "hits" from cylinders that are
                       wheels, pillars and exhaust tips
    …2022Engine        one material suffix repeated across 1,400 meshes,
                       which inflates a hit COUNT without adding a part

So the count is worthless and the NAMES are the evidence. This script
demands a strong token, excludes the traps, and prints what it matched so
a human can overrule it. Two cars survived the first manual read —
`peugeot-207-pw1-v3` (engine_a, ENG_BAY, ENG_METAL) and
`bmw-m6-2004-bm2-v1` (engine_a_SUB0_engine_carb, cooler_intercooler) —
and those are the shape of a true positive.
"""
import json, re, sys
from collections import Counter
import glb_parts as G

# STRONG tokens only. Each one had to survive the question "what else in a
# car model could legitimately be called this?"
STRONG = re.compile(
    r'(?:^|[_\-. ])eng(?:ine)?(?:[_\-. ]|$)'      # engine, eng_, ENG_BAY
    r'|engine_?bay|engine_?block|enginebay'
    r'|cylinder_?head|cylinderhead'
    r'|crank(?:shaft|case)|camshaft'
    r'|intake_?manifold|exhaust_?manifold|inlet_?manifold'
    r'|intercooler|throttle_?body|injector|sparkplug|spark_?plug'
    r'|oil_?(?:pan|sump|filter)|sump'
    r'|gearbox|transmission|bellhousing|driveshaft|differential'
    r'|turbocharger|supercharger'
    r'|alternator|starter_?motor|radiator_?(?:core|fan|hose)',
    re.I)

# Things that LOOK like the above and are not.
TRAP = re.compile(
    r'cayenne|turbo\w*gt|\bturbo\b(?=\s*(?:s|gt|x)?\b.*(?:20\d\d|edition))'
    r'|^cylinder[.\d_]*$|^cylinder\d+$'      # Blender primitive
    r'|motorsport|motorway|motorcycle'
    r'|radiator_?grill', re.I)


def engine_names(names):
    return sorted({n for n in names if STRONG.search(n) and not TRAP.search(n)})


def main():
    SP = sys.argv[1] if len(sys.argv) > 1 else 'parts_audit.json'
    rows = json.load(open(SP))
    cat = json.loads(G.fetch(G.CATALOGUE)[0].decode())
    byid = {x['assetId']: x for x in cat}

    # only re-read the assets the loose sweep flagged — the rest cannot
    # gain an engine by being looked at again with a NARROWER pattern
    cand = [r for r in rows if 'engine' in r.get('broad', {})]
    print(f'{len(cand)} assets flagged by the loose sweep; re-reading each '
          f'with strong tokens only\n')

    real, weak = [], []
    for i, r in enumerate(cand, 1):
        a = byid.get(r['assetId'])
        if not a:
            continue
        try:
            g, _ = G.glb_json(a['desktopGlbUrl'])
        except Exception as e:
            print(f'  {r["assetId"]}: {e}')
            continue
        names = [n.get('name', '') for n in g.get('nodes', [])]
        names += [m.get('name', '') for m in g.get('meshes', [])]
        hits = engine_names(names)
        # COUNT DISTINCT PART STEMS, not name occurrences: this exporter
        # family emits one mesh per material, so `engine_a.001`,
        # `engine_a.001_ENG_BLACK_0` and `engine_a.002` are two parts and
        # three names. A hit count would say six.
        stems = {re.sub(r'[._]\d+.*$', '', h).lower() for h in hits}
        if len(stems) >= 3:
            real.append((r['assetId'], len(stems), sorted(stems)[:8]))
        elif hits:
            weak.append((r['assetId'], sorted(stems)[:5]))
        print(f'{i:>4}/{len(cand)}  {r["assetId"]:<44} '
              f'{len(stems):>3} engine part stems', flush=True)

    print('\n' + '=' * 68)
    print(f'REAL ENGINE GEOMETRY: {len(real)} assets '
          f'(3 or more distinct engine part stems)')
    for aid, n, stems in sorted(real, key=lambda x: -x[1]):
        print(f'  {n:>3}  {aid:<44} {", ".join(stems)}')
    print(f'\nWEAK / ambiguous: {len(weak)} assets with 1-2 stems '
          f'(probably a badge, a grille or a stray primitive)')
    for aid, stems in weak[:15]:
        print(f'       {aid:<44} {", ".join(stems)}')
    json.dump({'real': real, 'weak': weak}, open('engine_hunt.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
